"""SCRUM-46 Attendee Registration and Update Notifications: Registration integration tests.

Story: As an Attendee, I want to receive notifications about my registration status, so that I can confirm my place and stay updated on event changes.

Real: Flask routes, owner SQL, postgres:17.6 session container and full unmodified migrations.
Doubled: external display enrichment supplied as an envelope; no other service/broker runs.
Not proven: external lookup, RabbitMQ/inbox delivery, frontend or authentication.
AC1 Given an Attendee successfully registers for an event, the system sends an in-app notification confirming their registration with the event name, date, time, venue, and registration reference number.
AC2 Given an Attendee successfully withdraws their registration, the system sends an in-app notification confirming the withdrawal with the event name.
AC3 Given an event cancellation takes effect, or a change to its date, time or venue is approved and applied, all currently registered Attendees receive an in-app notification with the event name and cancellation status or updated details, as applicable.
AC1/2 transactional actions and durable retries are covered here; AC3 belongs to Event/Workflow.
AC = acceptance criterion; DR = supporting design rule.
"""

import pytest
from tests.integration.factories import make_user, make_event, ATTENDEE_ID, ORGANISER_ID

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


# AC1 ---- registration confirmation; secondary AC2 withdrawal
def test_ac1_register_withdraw_reregister_keep_reference_and_distinct_action_ids(
    client, db
):
    """Normal: create synthetic parent rows, then register, repeat, withdraw, repeat, and re-register.
    Real HTTP mutations and PostgreSQL must leave one Confirmed registration with
    its original reference, but three different action intents in chronological order.
    Rejected repeats add nothing. Distinct action IDs prevent replay deduplication
    from swallowing a legitimate later action; display enrichment and delivery do not run.
    """
    # Arrange
    make_user(db, ORGANISER_ID, "Event Organiser")
    make_user(db, ATTENDEE_ID, "Attendee")
    event = make_event(db)
    body = dict(eventId=event, attendeeId=ATTENDEE_ID, capacity=2)
    # Act
    first = client.post("/registrations", json=body)
    assert first.status_code == 201, first.json
    ref = first.json["registration"]["registration_id"]
    assert client.post("/registrations", json=body).status_code == 409
    withdrawn = client.patch(
        f"/registrations/{ref}/withdraw", json=dict(attendeeId=ATTENDEE_ID)
    )
    assert withdrawn.status_code == 200, withdrawn.json
    assert (
        client.patch(
            f"/registrations/{ref}/withdraw", json=dict(attendeeId=ATTENDEE_ID)
        ).status_code
        == 409
    )
    again = client.post("/registrations", json=body)
    # Assert
    assert again.status_code == 201
    assert again.json["registration"]["registration_id"] == ref
    rows = db.execute(
        'SELECT source_id,type,source FROM public."RegistrationNotificationOutbox" ORDER BY created_at'
    )
    assert len(rows) == 3
    assert len({str(row["source_id"]) for row in rows}) == 3
    assert [row["type"] for row in rows] == [
        "registration.confirmed",
        "registration.withdrawn",
        "registration.confirmed",
    ]
    assert all(
        row["source"]
        == dict(eventId=event, recipientId=ATTENDEE_ID, registrationId=ref)
        for row in rows
    )
    assert db.registration(ref)["status"] == "Confirmed"


# AC1 ---- supporting DR: action/intent atomicity and durable delivery retries


def test_ac1_outbox_write_failure_rolls_back_registration_without_phantom_work(
    client, db
):
    """Failure: an owned-PostgreSQL trigger refuses the notification-intent insertion.
    Register through the real HTTP route and expect storage failure with neither
    Registration nor outbox rows committed. This checks the all-or-nothing promise,
    not merely a mocked rollback call; no remote service or broker is involved.
    """
    # Arrange: only the owned database receives this temporary failure trigger.
    make_user(db, ORGANISER_ID, "Event Organiser")
    make_user(db, ATTENDEE_ID, "Attendee")
    event = make_event(db)
    db.execute("""CREATE FUNCTION public.scrum46_refuse() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'synthetic intent failure'; END $$;
        CREATE TRIGGER scrum46_refuse BEFORE INSERT ON public."RegistrationNotificationOutbox"
        FOR EACH ROW EXECUTE FUNCTION public.scrum46_refuse();""")
    try:
        # Act: fail intent insertion after the business mutation has begun.
        response = client.post(
            "/registrations",
            json=dict(eventId=event, attendeeId=ATTENDEE_ID, capacity=2),
        )
        # Assert: independent connections observe neither half of the transaction.
        assert response.status_code == 503
        assert db.execute('SELECT * FROM public."Registration"') == []
        assert db.execute('SELECT * FROM public."RegistrationNotificationOutbox"') == []
    finally:
        db.execute(
            'DROP TRIGGER scrum46_refuse ON public."RegistrationNotificationOutbox"; DROP FUNCTION public.scrum46_refuse();'
        )


def test_ac1_frozen_action_survives_retry_and_rejects_stale_leases(client, db):
    """Failure/recovery: save and freeze a real registration intent, then report a publisher failure.
    Through supported owner APIs, wait for natural retry backoff, reclaim a new lease,
    reject the obsolete token before and after reclaim, and complete with the new token.
    Independent PostgreSQL reads must retain the exact envelope and Confirmed place.
    The publisher failure is reported input, not a running broker outage; this proves
    owner persistence/fencing without claiming actual elapsed-time lease expiry.
    """
    # Arrange
    make_user(db, ORGANISER_ID, "Event Organiser")
    make_user(db, ATTENDEE_ID, "Attendee")
    event = make_event(db)
    response = client.post(
        "/registrations", json=dict(eventId=event, attendeeId=ATTENDEE_ID, capacity=2)
    )
    ref = response.json["registration"]["registration_id"]
    client.application.config["INTERNAL_SERVICE_TOKEN"] = "synthetic"
    headers = {"X-Internal-Token": "synthetic"}
    path = "/internal/notification-outbox"
    job = client.post(path + "/claim", headers=headers, json={}).json["jobs"][0]
    details = {
        **job["source"],
        "eventName": "Workshop",
        "startDateTime": "2030-03-01T01:00:00+00:00",
        "endDateTime": "2030-03-01T09:00:00+00:00",
        "venueName": "Hall A",
    }
    envelope = dict(
        version=1,
        id=job["id"],
        type=job["type"],
        createdAt=job["createdAt"],
        recipientId=ATTENDEE_ID,
        destination=dict(kind="attendee-registration", registrationId=ref),
        details=details,
        message=f"Registration confirmed for Workshop. Date/time: 01 Mar 2030, 09:00 SGT – 01 Mar 2030, 17:00 SGT. Venue: Hall A. Registration reference: {ref}.",
    )
    # Act / Assert
    frozen = client.post(
        path + f"/{job['id']}/freeze",
        headers=headers,
        json=dict(leaseToken=job["leaseToken"], envelope=envelope),
    )
    assert frozen.status_code == 200, frozen.json
    assert (
        db.execute('SELECT envelope FROM public."RegistrationNotificationOutbox"')[0][
            "envelope"
        ]
        == envelope
    )
    assert (
        client.post(
            path + f"/{job['id']}/retry",
            headers=headers,
            json=dict(
                leaseToken=job["leaseToken"], error="Synthetic publisher failure"
            ),
        ).status_code
        == 200
    )
    assert db.registration(ref)["status"] == "Confirmed"
    assert (
        client.post(
            path + f"/{job['id']}/published",
            headers=headers,
            json=dict(leaseToken=job["leaseToken"]),
        ).status_code
        == 409
    )
    saved = db.execute(
        'SELECT envelope,published_at,last_error FROM public."RegistrationNotificationOutbox"'
    )[0]
    assert saved["envelope"] == envelope and saved["published_at"] is None
    assert saved["last_error"] == "Synthetic publisher failure"
    import time

    # Act: poll readiness under a deadline, respecting the owner's natural backoff.
    deadline = time.monotonic() + 10
    reclaimed = None
    while reclaimed is None and time.monotonic() < deadline:
        jobs = client.post(path + "/claim", headers=headers, json={}).json["jobs"]
        if jobs:
            reclaimed = jobs[0]
        else:
            time.sleep(0.1)
    assert reclaimed is not None
    assert reclaimed["id"] == job["id"] and reclaimed["leaseToken"] != job["leaseToken"]
    assert reclaimed["envelope"] == envelope
    # Even after reclaim, the obsolete publisher cannot complete the current lease.
    assert (
        client.post(
            path + f"/{job['id']}/published",
            headers=headers,
            json=dict(leaseToken=job["leaseToken"]),
        ).status_code
        == 409
    )
    assert (
        client.post(
            path + f"/{job['id']}/published",
            headers=headers,
            json=dict(leaseToken=reclaimed["leaseToken"]),
        ).status_code
        == 200
    )
    completed = db.execute(
        'SELECT published_at,envelope FROM public."RegistrationNotificationOutbox"'
    )[0]
    assert completed["published_at"] is not None and completed["envelope"] == envelope
    assert db.registration(ref)["status"] == "Confirmed"
