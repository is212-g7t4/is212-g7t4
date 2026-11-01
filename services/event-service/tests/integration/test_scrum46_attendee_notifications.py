"""SCRUM-46 Attendee Registration and Update Notifications: Event integration tests.

Story: As an Attendee, I want to receive notifications about my registration status, so that I can confirm my place and stay updated on event changes.

Real: Event mutation/outbox APIs, SQL and session postgres:17.6 with full unmodified migrations.
Doubled: actual venue and recipient lookup results at the owning HTTP input boundary.
Not proven: other services' rules, broker/inbox delivery, browser or authentication.
AC1 Given an Attendee successfully registers for an event, the system sends an in-app notification confirming their registration with the event name, date, time, venue, and registration reference number.
AC2 Given an Attendee successfully withdraws their registration, the system sends an in-app notification confirming the withdrawal with the event name.
AC3 Given an event cancellation takes effect, or a change to its date, time or venue is approved and applied, all currently registered Attendees receive an in-app notification with the event name and cancellation status or updated details, as applicable.
AC1/2 are covered in Registration/Workflow. AC3 durable business transitions and frozen fanout are covered here.
AC = acceptance criterion; DR = supporting design rule.
"""

from uuid import uuid4, UUID, uuid5
import pytest
from tests.integration.factories import make_event_change_event, SAFETY_COORDINATOR

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
BUSINESS = {"X-Internal-Token": "synthetic"}
INTERNAL = {"X-Internal-Token": "synthetic"}


# AC3 ----
@pytest.mark.parametrize("outcome", ["update", "reverted", "cancelled"])
def test_ac3_venue_and_schedule_changes_wait_for_final_safety_outcome(
    attendee_notification_owner, outcome
):
    """Normal/boundary: reopen a previously Confirmed event using its original Hall A venue.
    Exercise real HTTP/SQL safety transitions; no attendee alert may exist before the
    final decision. update approves changed dates and Hall C as one saved delta;
    reverted returns to original facts and stays silent; cancelled saves cancellation
    instead of an update. Venue facts are supplied inputs, not a running composite,
    so this proves Event persistence but not downstream lookup or delivery.
    """
    # Arrange: the fixture's real Event and full history pass normal safety transitions.
    client, db = attendee_notification_owner
    event = make_event_change_event(db)
    first, second = str(uuid4()), str(uuid4())

    def safety(status, round_id, **extra):
        """Send the named safety transition through the real Event owner HTTP boundary.
        The caller supplies external venue facts and the synthetic review-cycle identity.
        """
        return client.patch(
            f"/events/{event}/safety-status",
            headers=BUSINESS,
            json=dict(
                status=status,
                safetyCheckId=round_id,
                roundNumber=1 if round_id == first else 2,
                **extra,
            ),
        )

    assert (
        safety(
            "Pending Safety Check", first, coordinatorId=SAFETY_COORDINATOR
        ).status_code
        == 200
    )
    assert safety("Confirmed", first, decidedBy=SAFETY_COORDINATOR).status_code == 200
    db.query('DELETE FROM public."EventNotificationOutbox"')
    # Act: actual pre-change venue is supplied by the Safety composite, before booking edits.
    withdrawn = safety(
        "Approved",
        first,
        coordinatorId=SAFETY_COORDINATOR,
        withdrawnSafetyCheckId=first,
        reason="Venue edit",
        venueBefore="Hall A",
    )
    assert withdrawn.status_code == 200, withdrawn.json
    if outcome in ("update", "cancelled"):
        changed = client.patch(
            f"/events/{event}/details",
            headers=BUSINESS,
            json=dict(
                coordinatorId=SAFETY_COORDINATOR,
                changes=dict(
                    preferredStartDate="2030-03-02T09:00:00",
                    preferredEndDate="2030-03-02T18:00:00",
                ),
            ),
        )
        assert changed.status_code == 200, changed.json
    assert (
        safety(
            "Pending Safety Check", second, coordinatorId=SAFETY_COORDINATOR
        ).status_code
        == 200
    )
    assert (
        db.query(
            'SELECT type FROM public."EventNotificationOutbox" WHERE type LIKE %s',
            ["attendee.%"],
        )
        == []
    )
    final = safety(
        "Cancelled" if outcome == "cancelled" else "Confirmed",
        second,
        decidedBy=SAFETY_COORDINATOR,
        remarks="Final review",
        attendeeVenue="Hall C" if outcome == "update" else "Hall A",
    )
    assert final.status_code == 200, final.json
    # Assert: final facts were captured transactionally, not deferred to latest-state lookup.
    rows = db.query(
        'SELECT type,source FROM public."EventNotificationOutbox" WHERE type LIKE %s',
        ["attendee.%"],
    )
    if outcome == "reverted":
        assert rows == []
    elif outcome == "cancelled":
        assert rows == [
            ("attendee.cancelled-fanout", dict(eventId=event, eventName="Workshop"))
        ]
    else:
        assert rows == [
            (
                "attendee.updated-fanout",
                dict(
                    eventId=event,
                    eventName="Workshop",
                    changes=dict(
                        startDateTime=[
                            "2030-03-01T09:00:00+08:00",
                            "2030-03-02T09:00:00+08:00",
                        ],
                        endDateTime=[
                            "2030-03-01T17:00:00+08:00",
                            "2030-03-02T18:00:00+08:00",
                        ],
                        venueName=["Hall A", "Hall C"],
                    ),
                ),
            )
        ]


def test_ac3_recipient_expansion_freezes_the_audience_and_child_content(
    attendee_notification_owner,
):
    """Normal: expand a committed cancellation parent for two attendee/registration pairs.
    Real owner HTTP and PostgreSQL must preserve each UUID5/recipient/reference tuple;
    a repeat with an empty audience is refused and cannot rewrite existing children.
    Freeze a child and read back its exact recipient-specific destination, because
    correct recipient and reference sets alone could conceal swapped private links.
    Recipient lookup and the proposed envelope are supplied inputs; no broker runs.
    """
    from psycopg2.extras import Json

    client, db = attendee_notification_owner
    event = make_event_change_event(db)
    parent = str(uuid4())
    source = dict(eventId=event, eventName="Workshop")
    db.query(
        'INSERT INTO public."EventNotificationOutbox"(source_id,type,source) VALUES (%s,%s,%s)',
        [parent, "attendee.cancelled-fanout", Json(source)],
    )
    path = "/internal/notification-outbox"
    job = client.post(path + "/claim", headers=INTERNAL, json={}).json["jobs"][0]
    users = [str(uuid4()), str(uuid4())]
    registrations = [str(uuid4()), str(uuid4())]
    recipients = [
        dict(recipientId=u, registrationId=r) for u, r in zip(users, registrations)
    ]
    # Act: freeze these two recipient/reference pairs through the owner API.
    response = client.post(
        path + f"/{parent}/expand",
        headers=INTERNAL,
        json=dict(leaseToken=job["leaseToken"], recipients=recipients),
    )
    assert response.status_code == 200, response.json
    # Assert: compare complete tuples; independent sets would allow swapped links.
    children = db.query(
        'SELECT source_id,type,source FROM public."EventNotificationOutbox" WHERE source_id<>%s ORDER BY source_id',
        [parent],
    )
    assert {str(row[0]) for row in children} == {
        str(uuid5(UUID(parent), user)) for user in users
    }
    assert {row[1] for row in children} == {"attendee.event-cancelled"}
    assert {row[2]["registrationId"] for row in children} == set(registrations)
    assert {
        (str(row[0]), row[2]["recipientId"], row[2]["registrationId"])
        for row in children
    } == {
        (str(uuid5(UUID(parent), users[0])), users[0], registrations[0]),
        (str(uuid5(UUID(parent), users[1])), users[1], registrations[1]),
    }
    # Act/Assert: completed parents cannot accept a replacement audience.
    again = client.post(
        path + f"/{parent}/expand",
        headers=INTERNAL,
        json=dict(leaseToken=job["leaseToken"], recipients=[]),
    )
    assert again.status_code == 409
    assert (
        db.query(
            'SELECT source_id,type,source FROM public."EventNotificationOutbox" WHERE source_id<>%s ORDER BY source_id',
            [parent],
        )
        == children
    )
    # Act/Assert: freeze a claimed child and independently read its saved destination.
    claim = client.post(path + "/claim", headers=INTERNAL, json={}).json["jobs"][0]
    envelope = dict(
        version=1,
        id=claim["id"],
        type=claim["type"],
        recipientId=claim["source"]["recipientId"],
        createdAt=claim["createdAt"],
        details=claim["source"],
        message="Workshop was cancelled.",
        destination=dict(
            kind="attendee-registration",
            registrationId=claim["source"]["registrationId"],
        ),
    )
    frozen = client.post(
        path + f"/{claim['id']}/freeze",
        headers=INTERNAL,
        json=dict(leaseToken=claim["leaseToken"], envelope=envelope),
    )
    assert frozen.status_code == 200, frozen.json
    expected_registration = dict(zip(users, registrations))[claim["source"]["recipientId"]]
    assert frozen.json["envelope"]["recipientId"] == claim["source"]["recipientId"]
    assert frozen.json["envelope"]["destination"] == dict(
        kind="attendee-registration", registrationId=expected_registration
    )
    assert db.query(
        'SELECT envelope FROM public."EventNotificationOutbox" WHERE source_id=%s',
        [claim["id"]],
    ) == [(envelope,)]


# AC3 / DR ---- one transaction must freeze the complete audience or no audience.
def test_ac3_partial_fanout_failure_rolls_back_and_recovers_via_owner_retry(
    attendee_notification_owner,
):
    """Failure/recovery: the owned PostgreSQL trigger rejects the second child after the first insert.
    A nontransactional sequence proves both inserts were attempted; an independent
    reader must find no committed children and the unchanged, unpublished leased parent.
    Remove the trigger, retry through the owner API and its normal backoff, reject the
    old token, then expand exactly the original two attendee/reference pairs. This
    proves all-or-nothing audience persistence and recoverability, not broker delivery;
    recipient lookup is supplied and production transaction code is not mocked.
    """
    import time
    from contextlib import closing
    import psycopg2
    from psycopg2.extras import Json

    # Arrange: a committed parent; only this fixture-owned database gets the failure trigger.
    client, db = attendee_notification_owner
    event = make_event_change_event(db)
    parent = str(uuid4())
    users = sorted([str(uuid4()), str(uuid4())])
    registrations = [str(uuid4()), str(uuid4())]
    recipients = [
        dict(recipientId=user, registrationId=registration)
        for user, registration in zip(users, registrations)
    ]
    source = dict(eventId=event, eventName="Workshop")
    db.query(
        'INSERT INTO public."EventNotificationOutbox"(source_id,type,source) VALUES (%s,%s,%s)',
        [parent, "attendee.cancelled-fanout", Json(source)],
    )
    path = "/internal/notification-outbox"
    claimed = client.post(path + "/claim", headers=INTERNAL, json={})
    assert claimed.status_code == 200, claimed.json
    job = claimed.json["jobs"][0]
    assert job["id"] == parent
    db.query('''
        CREATE SEQUENCE public.scrum46_child_attempt;
        CREATE FUNCTION public.scrum46_fail_second_child() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.type = 'attendee.event-cancelled' THEN
                IF nextval('public.scrum46_child_attempt') = 2 THEN
                    IF (SELECT count(*) FROM public."EventNotificationOutbox"
                        WHERE type = 'attendee.event-cancelled') <> 1 THEN
                        RAISE EXCEPTION 'First child was not inserted';
                    END IF;
                    RAISE EXCEPTION 'Controlled second-child failure after first insert';
                END IF;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER scrum46_fail_second_child BEFORE INSERT ON public."EventNotificationOutbox"
        FOR EACH ROW EXECUTE FUNCTION public.scrum46_fail_second_child();
    ''')
    try:
        # Act: the second insert fails after the first has executed in the owner transaction.
        failed = client.post(
            path + f"/{parent}/expand", headers=INTERNAL,
            json=dict(leaseToken=job["leaseToken"], recipients=recipients),
        )
        assert failed.status_code == 503, failed.json
        # Sequence increments survive rollback: both child inserts reached the SQL trigger.
        assert db.query("SELECT last_value,is_called FROM public.scrum46_child_attempt") == [(2, True)]
        # Assert through a separate committed reader, not the owner's failed transaction.
        # db.query rechecks exact live container identity before opening this independent reader.
        assert db.query("SELECT 1") == [(1,)]
        with closing(psycopg2.connect(client.application.config["DATABASE_URL"])) as reader:
            with reader, reader.cursor() as cursor:
                cursor.execute('SELECT source_id FROM public."EventNotificationOutbox" WHERE source_id<>%s', [parent])
                assert cursor.fetchall() == []
                cursor.execute('SELECT published_at,lease_token,attempts,source FROM public."EventNotificationOutbox" WHERE source_id=%s', [parent])
                assert cursor.fetchall() == [(None, job["leaseToken"], 1, source)]
    finally:
        db.query('''
            DROP TRIGGER scrum46_fail_second_child ON public."EventNotificationOutbox";
            DROP FUNCTION public.scrum46_fail_second_child();
            DROP SEQUENCE public.scrum46_child_attempt;
        ''')

    # Recover through supported retry/backoff/claim APIs; never rewrite scheduling/lease SQL.
    retried = client.post(
        path + f"/{parent}/retry", headers=INTERNAL,
        json=dict(leaseToken=job["leaseToken"], error="Controlled second-child failure"),
    )
    assert retried.status_code == 200, retried.json
    deadline = time.monotonic() + 10
    while True:
        response = client.post(path + "/claim", headers=INTERNAL, json={})
        assert response.status_code == 200, response.json
        jobs = response.json["jobs"]
        if jobs:
            break
        assert time.monotonic() < deadline, "Parent did not recover through normal backoff"
        time.sleep(0.1)
    recovered = jobs[0]
    assert recovered["id"] == parent and recovered["attempts"] == 2
    assert recovered["leaseToken"] != job["leaseToken"]
    assert recovered["source"] == source
    stale = client.post(
        path + f"/{parent}/expand", headers=INTERNAL,
        json=dict(leaseToken=job["leaseToken"], recipients=recipients),
    )
    assert stale.status_code == 409
    expanded = client.post(
        path + f"/{parent}/expand", headers=INTERNAL,
        json=dict(leaseToken=recovered["leaseToken"], recipients=recipients),
    )
    assert expanded.status_code == 200, expanded.json
    children = db.query(
        'SELECT source_id,type,source FROM public."EventNotificationOutbox" WHERE source_id<>%s', [parent]
    )
    assert len(children) == 2
    assert {
        (str(identifier), kind, child["recipientId"], child["registrationId"])
        for identifier, kind, child in children
    } == {
        (str(uuid5(UUID(parent), users[0])), "attendee.event-cancelled", users[0], registrations[0]),
        (str(uuid5(UUID(parent), users[1])), "attendee.event-cancelled", users[1], registrations[1]),
    }
    assert all(child == dict(source, recipientId=user, registrationId=dict(zip(users, registrations))[user])
               for _, _, child in children for user in [child["recipientId"]])
    assert db.query(
        'SELECT published_at IS NOT NULL,lease_token,lease_until FROM public."EventNotificationOutbox" WHERE source_id=%s', [parent]
    ) == [(True, None, None)]


# AC3 ---- independently approved later cycles remain separately notifiable.
def test_ac3_later_safety_approval_uses_the_new_confirmed_baseline(
    attendee_notification_owner,
):
    """Normal: approve an A-to-C venue edit, then reopen and approve C-to-D in a later cycle.
    Real Event HTTP transitions and PostgreSQL must retain two distinct intents with
    those exact deltas, not reuse A or suppress the second alert as a duplicate.
    This protects recurring edits after an earlier successful update; external venue
    facts enter as HTTP fields and neither remote lookup nor delivery runs here.
    """
    # Arrange: one owned Event will pass through two independently approved edit cycles.
    client, db = attendee_notification_owner
    event = make_event_change_event(db)
    rounds = [str(uuid4()) for _ in range(3)]

    def safety(status, index, **extra):
        """Send the named safety transition through the real Event owner HTTP boundary.
        The caller supplies external venue facts and the synthetic review-cycle identity.
        """
        response = client.patch(
            f"/events/{event}/safety-status",
            headers=BUSINESS,
            json=dict(
                status=status,
                safetyCheckId=rounds[index],
                roundNumber=index + 1,
                **extra,
            ),
        )
        assert response.status_code == 200, response.json

    safety("Pending Safety Check", 0, coordinatorId=SAFETY_COORDINATOR)
    safety("Confirmed", 0, decidedBy=SAFETY_COORDINATOR)
    # Act: each approval establishes the baseline for the following cycle.
    for cycle, (before, after) in enumerate(
        (("Hall A", "Hall C"), ("Hall C", "Hall D"))
    ):
        safety(
            "Approved",
            cycle,
            coordinatorId=SAFETY_COORDINATOR,
            withdrawnSafetyCheckId=rounds[cycle],
            reason="Venue edit",
            venueBefore=before,
        )
        safety("Pending Safety Check", cycle + 1, coordinatorId=SAFETY_COORDINATOR)
        safety(
            "Confirmed", cycle + 1, decidedBy=SAFETY_COORDINATOR, attendeeVenue=after
        )
    # Assert: the original intent survives and the later cycle has its own identity.
    rows = db.query(
        'SELECT source_id,source FROM public."EventNotificationOutbox" WHERE type=%s ORDER BY created_at',
        ["attendee.updated-fanout"],
    )
    assert len(rows) == 2 and rows[0][0] != rows[1][0]
    assert [row[1]["changes"] for row in rows] == [
        {"venueName": ["Hall A", "Hall C"]},
        {"venueName": ["Hall C", "Hall D"]},
    ]
