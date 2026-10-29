"""SCRUM-47 Venue booking notification and decision alerts: owner integration tests.

Story: As an Event Coordinator and Venue Staff, I want to receive notifications
about venue booking requests and decisions, so that I can coordinate venue
arrangements efficiently.
AC1 Given an Event Coordinator submits a venue booking request, system sends
an in-app notification to Venue Staff with event name, requested venue,
date/time and link to review.
AC2 Given booking approved/rejected, sends an in-app notification to Event
Coordinator with event name, venue, decision.

AC = acceptance criterion; DR = supporting design rule, not another AC.
Real: Flask routes, native SQL, owned postgres:17.6, full unmodified migrations
and synthetic FK parents. Doubled: nothing; a DB trigger injects failure.
AC1 owns captured fanout; AC2 owns first-decision history. DR: atomic rollback,
frozen retries, lease fencing and no extra edit/closure alerts. Existing three
mutation successes remain in submission/review modules, not duplicated here.
Not proven: enrichment, broker/inbox/UI, concurrent workers or migration upgrades;
full-chain empty-schema installation is not upgrade compatibility.
"""
from copy import deepcopy
from uuid import UUID, uuid5

import pytest
from psycopg2.extras import Json

from tests.integration.factories import (
    COORDINATOR_ID, STAFF_ID, at, make_user, make_venue, make_event, make_booking,
)
from tests.unit.factories import bearer

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
OTHER_STAFF = "44444444-4444-4444-8444-444444444444"
HEADERS = {"X-Internal-Token": "synthetic"}


@pytest.fixture
def world(client, db, monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "synthetic")
    make_user(db)
    make_user(db, STAFF_ID, "Venue Staff")
    make_user(db, OTHER_STAFF, "Venue Staff")
    return make_event(db), make_venue(db)


def request_body(world, day=1):
    event, venue = world
    return dict(eventId=event, venueId=venue,
                requestedStartTime=f"2030-03-{day:02d}T13:00",
                requestedEndTime=f"2030-03-{day:02d}T15:00",
                requiredCapacity=50, venueRequirements="Stage")


def intents(db):
    return db.execute('SELECT * FROM public."VenueNotificationOutbox" ORDER BY source_id')


def operate(client, job, action, **data):
    return client.post(f"/internal/notification-outbox/{job['id']}/{action}",
                       headers=HEADERS, json={"leaseToken": job["leaseToken"], **data})


def claim(client):
    response = client.post("/internal/notification-outbox/claim", headers=HEADERS, json={})
    assert response.status_code == 200
    [job] = response.json["jobs"]
    return job


def decide(client, booking, action):
    # Upstream rejection workflow requires input; no notification reason assertion.
    return client.patch(f"/venue-bookings/{booking}/{action}",
                        headers=bearer(STAFF_ID, "Venue Staff"), json={"rejectionReason": "Fixture input"})


# AC1 — durable deduplicated fanout.
def test_ac1_fanout_commits_one_historical_child_per_distinct_staff(client, db, world):
    """Normal: duplicate staff rows produce two durable children and complete only their parent."""
    created = client.post("/venue-bookings", json=request_body(world))
    assert created.status_code == 201
    [parent] = intents(db)
    job = claim(client)

    response = operate(client, job, "expand", recipientIds=[OTHER_STAFF, STAFF_ID, OTHER_STAFF],
                       eventName="Spring Fair", venueName="Hall A")

    assert response.status_code == 200
    assert response.json == {"id": job["id"], "status": "expanded", "recipients": 2}
    rows = intents(db)
    saved_parent = next(row for row in rows if str(row["source_id"]) == job["id"])
    children = [row for row in rows if row != saved_parent]
    assert len(children) == 2
    assert saved_parent["source"] == parent["source"]
    assert saved_parent["published_at"] is not None
    assert saved_parent["lease_token"] is saved_parent["lease_until"] is None
    assert {str(row["source_id"]) for row in children} == {
        str(uuid5(UUID(job["id"]), recipient)) for recipient in (STAFF_ID, OTHER_STAFF)}
    assert {row["source"]["recipientId"] for row in children} == {STAFF_ID, OTHER_STAFF}
    for child in children:
        assert child["type"] == "venue.booking-submission"
        assert str(child["booking_id"]) == created.json["id"]
        assert child["source"] == {**parent["source"], "recipientId": child["source"]["recipientId"],
                                   "eventName": "Spring Fair", "venueName": "Hall A"}
        assert child["created_at"] == parent["created_at"]
        assert child["envelope"] is child["published_at"] is child["lease_token"] is None
    assert operate(client, job, "expand", recipientIds=[STAFF_ID],
                   eventName="Changed", venueName="Changed").status_code == 409
    assert intents(db) == rows


# DR supporting AC1/AC2 — PostgreSQL failure rolls back the business row too.
@pytest.mark.parametrize("action", ["submit", "approve", "reject"],
                         ids=["submission-rollback", "approval-rollback", "rejection-rollback"])
def test_ac1_failed_intent_insert_rolls_back_business_state(client, db, world, action):
    """Failure: database-side intent failure leaves no submitted row or changed decision behind."""
    event, venue = world
    booking = None if action == "submit" else make_booking(
        db, event, venue, at(1, 13), at(1, 15), status="Pending Review")
    before = db.bookings()
    db.execute("""CREATE FUNCTION scrum47_fail_intent() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'synthetic intent failure'; END $$""")
    try:
        db.execute('''CREATE TRIGGER scrum47_fail_intent BEFORE INSERT ON public."VenueNotificationOutbox"
                      FOR EACH ROW EXECUTE FUNCTION scrum47_fail_intent()''')
        result = (client.post("/venue-bookings", json=request_body(world)) if action == "submit"
                  else decide(client, booking, action))
        assert result.status_code == 503
        assert db.bookings() == before
        assert intents(db) == []
    finally:
        db.execute('DROP TRIGGER IF EXISTS scrum47_fail_intent ON public."VenueNotificationOutbox"; '
                   'DROP FUNCTION scrum47_fail_intent()')


# DR supporting AC1/AC2 — freeze survives retry, expiry and ambiguous publication.
@pytest.mark.parametrize("outcome", ["submission", "Approved", "Rejected"],
                         ids=["staff-submission-history", "approved-history", "rejected-history"])
def test_ac1_frozen_history_survives_retry_expiry_and_reclaim(client, db, world, outcome):
    """Boundary: expired and stale tokens are fenced while reclaimed work keeps its frozen envelope."""
    event, venue = world
    booking = make_booking(db, event, venue, at(1, 13), at(1, 15), status="Pending Review")
    source = dict(bookingId=booking, eventId=event, venueId=venue, requestedBy=COORDINATOR_ID,
                  startDateTime="2030-03-01T13:00:00+08:00", endDateTime="2030-03-01T15:00:00+08:00",
                  eventName="Spring Fair", venueName="Hall A")
    source.update({"recipientId": STAFF_ID} if outcome == "submission" else {"decision": outcome})
    kind = "venue.booking-submission" if outcome == "submission" else "venue.booking-decision"
    db.execute('INSERT INTO public."VenueNotificationOutbox" (type,booking_id,source) VALUES (%s,%s,%s)',
               [kind, booking, Json(source)])
    first = claim(client)
    envelope = dict(version=1, id=first["id"], type=kind,
                    recipientId=STAFF_ID if outcome == "submission" else COORDINATOR_ID,
                    createdAt=first["createdAt"], message="Original booking history", details=source,
                    destination={"kind": "venue-requests"} if outcome == "submission" else
                    {"kind": "event-venue-request", "eventId": event, "bookingId": booking})
    frozen = operate(client, first, "freeze", envelope=envelope)
    assert frozen.status_code == 200 and frozen.json["envelope"] == envelope
    assert intents(db)[0]["envelope"] == envelope
    assert operate(client, first, "retry", error="Synthetic publisher outage").status_code == 200
    [waiting] = intents(db)
    assert waiting["last_error"] == "Synthetic publisher outage"
    assert waiting["available_at"] > db.now()
    assert waiting["lease_token"] is waiting["lease_until"] is None
    assert waiting["envelope"] == envelope
    db.execute("UPDATE public.\"VenueNotificationOutbox\" SET available_at=now()-interval '1 second'")
    second = claim(client)
    assert second["id"] == first["id"] and second["attempts"] == 2
    assert second["leaseToken"] != first["leaseToken"]
    # Fixture-owned clock control: no sleeps or mocked lease-valid result.
    db.execute("UPDATE public.\"VenueNotificationOutbox\" SET lease_until=now()-interval '1 second'")
    expired = intents(db)
    assert expired[0]["lease_until"] < db.now()
    altered = {**deepcopy(envelope), "message": "A later draft cannot replace history"}
    for action, data in (("freeze", {"envelope": altered}), ("retry", {"error": "stale"}), ("published", {})):
        assert operate(client, second, action, **data).status_code == 409
    assert intents(db) == expired
    # Accepted publication with lost completion recovers this same frozen job.
    third = claim(client)
    assert third["id"] == first["id"] and third["attempts"] == 3
    assert third["leaseToken"] not in {first["leaseToken"], second["leaseToken"]}
    reclaimed = intents(db)
    for stale in (first, second):
        for action, data in (("freeze", {"envelope": altered}), ("retry", {"error": "stale"}), ("published", {})):
            assert operate(client, stale, action, **data).status_code == 409
    assert intents(db) == reclaimed
    result = operate(client, third, "freeze", envelope=altered)
    assert result.status_code == 200 and result.json["envelope"] == envelope
    assert third["envelope"] == envelope
    assert operate(client, third, "published").status_code == 200
    [done] = intents(db)
    assert done["envelope"] == envelope and done["source"] == source
    assert done["published_at"] is not None
    assert done["lease_token"] is done["lease_until"] is done["last_error"] is None
    assert client.post("/internal/notification-outbox/claim", headers=HEADERS, json={}).json == {"jobs": []}


# AC2 — valid later decisions must not roll back when their first alert exists.
def test_ac2_edit_resubmit_later_decision_and_cancel_do_not_add_alerts(client, db, world):
    """Boundary: editing permits a later decision without replacing history or adding alerts."""
    created = client.post("/venue-bookings", json=request_body(world))
    assert created.status_code == 201
    booking = created.json["id"]
    assert decide(client, booking, "approve").status_code == 200
    before = intents(db)
    assert sorted(row["type"] for row in before) == ["venue.booking-decision", "venue.booking-submission-fanout"]
    decision = next(row for row in before if row["type"] == "venue.booking-decision")
    assert decision["source"]["decision"] == "Approved"

    edited = client.patch(f"/venue-bookings/{booking}", json=request_body(world, day=2))
    assert edited.status_code == 200 and edited.json["status"] == "Pending Review"
    assert db.booking(booking)["requested_start_time"] == at(2, 13)
    assert db.booking(booking)["reviewed_at"] is None
    assert intents(db) == before
    later = decide(client, booking, "reject")
    assert later.status_code == 200 and later.json["status"] == "Rejected"
    assert db.booking(booking)["status"] == "Rejected"
    assert intents(db) == before
    # Rejected rows cannot cancel; use a distinct legitimately cancellable booking.
    second = make_booking(db, world[0], world[1], at(3, 13), at(3, 15), status="Pending Review")
    cancelled = client.patch(f"/venue-bookings/{second}/cancel", json={"eventId": world[0]})
    assert cancelled.status_code == 200 and db.booking(second)["status"] == "Cancelled"
    assert intents(db) == before


def test_ac2_closure_rejection_creates_only_the_existing_closure_alert(client, db, world):
    """Conflict: closure rejects the booking with one closure alert, never a second decision alert."""
    client.application.config.update(CLOSURE_CONFIRMATION_KEY="synthetic-confirmation-key-32-bytes-minimum")
    booking = make_booking(db, world[0], world[1], at(1, 13), at(1, 15), status="Pending Review")
    data = dict(venueId=world[1], startDateTime="2030-03-01T12:00:00+08:00",
                endDateTime="2030-03-01T16:00:00+08:00", reason="Fixture maintenance")
    headers = bearer(STAFF_ID, "Venue Staff")
    preview = client.post("/venue-closures/preview", json=data, headers=headers)
    assert preview.status_code == 200
    result = client.post("/venue-closures", json={**data, "confirmed": True,
                        "confirmationToken": preview.json["confirmationToken"]}, headers=headers)
    assert result.status_code == 201 and result.json["rejectedCount"] == 1
    [row] = intents(db)
    closure = result.json["closure"]["closureId"]
    assert db.booking(booking)["status"] == "Rejected"
    assert str(db.booking(booking)["rejection_closure_id"]) == closure
    assert row["type"] == "venue.closure-rejection"
    assert str(row["booking_id"]) == booking and str(row["closure_id"]) == closure
    # Rejection reason is outside SCRUM-47 assertions; check the closure identity/time contract.
    assert {key: row["source"][key] for key in ("closureId", "bookingId", "eventId", "venueId", "startDateTime", "endDateTime")} == {
        "closureId": closure, "bookingId": booking, "eventId": world[0], "venueId": world[1],
        "startDateTime": data["startDateTime"], "endDateTime": data["endDateTime"]}
