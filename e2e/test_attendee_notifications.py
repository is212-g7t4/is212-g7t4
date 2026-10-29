"""SCRUM-46 Attendee Registration and Update Notifications: isolated cross-service E2E.

Story: As an Attendee, I want to receive notifications about my registration status, so that I can confirm my place and stay updated on event changes.

Real: seven HTTP services, Event Workflow dispatcher, RabbitMQ, Notification consumer,
      owned postgres:17.6 and the complete unmodified migrations.
Doubled: none. Safety decisions enter the owning Event API with the existing internal token;
         this is not a browser journey or the complete Safety Check composite journey.
Not proven: production authentication, shared deployment or browser behavior.
AC1 Given an Attendee successfully registers for an event, the system sends an in-app notification confirming their registration with the event name, date, time, venue, and registration reference number.
AC2 Given an Attendee successfully withdraws their registration, the system sends an in-app notification confirming the withdrawal with the event name.
AC3 Given an event cancellation takes effect, or a change to its date, time or venue is approved and applied, all currently registered Attendees receive an in-app notification with the event name and cancellation status or updated details, as applicable.
AC = acceptance criterion; DR = supporting design rule.
"""

import json
import subprocess
from uuid import uuid4
from factories import attendee_world


def test_ac1_ac2_ac3_actions_deliver_through_owned_broker_and_preserve_history(
    attendee_stack,
):
    """Normal/recovery: register, withdraw and re-register synthetic attendees, then approve an edit and cancel.
    Exercise real HTTP owners, dispatcher, RabbitMQ, consumer and inbox in an owned
    stack. Assert exact content and recipient/reference/destination pairing, one
    read-preserving replay, preparation-time membership, immutable prepared children,
    and Cancelled history without rewriting Confirmed registration state. Another
    attendee cannot mark the first user's alert read. These checks catch cross-service
    contract drift that isolated doubles miss; safety decisions enter Event directly,
    so this is neither a browser journey nor the full Safety/Venue orchestration.
    """
    # Arrange
    stack = attendee_stack
    world = attendee_world(stack)
    event = world["event"]
    first, second, withdrawn = world["attendees"]

    def register(user):
        """Register this synthetic attendee through the composite and return the full owner reference.
        """
        return stack.call(
            "attendee-registration",
            "POST",
            "/registrations",
            json=dict(eventId=event, attendeeId=user),
        )["registration"]["registration_id"]

    def intents(owner, kind=None):
        """Read committed owner outbox rows, optionally limited to one exact notification type.
        This is an observation helper; it never claims, retries or edits production work.
        """
        where = " WHERE type=%s" if kind else ""
        return stack.query(
            f'SELECT source_id,type,source,envelope FROM public."{owner}NotificationOutbox"'
            + where
            + " ORDER BY created_at",
            [kind] if kind else [],
        )

    # Act / Assert AC1: actual business action -> durable owner -> worker -> broker -> consumer -> inbox API.
    ref = register(first)
    source = str(intents("Registration")[0]["source_id"])
    stack.dispatch("registration")
    confirmed = stack.delivered(first, source)
    assert confirmed["payload"]["details"]["registrationId"] == ref
    assert confirmed["payload"]["details"]["venueName"] == "Hall A"
    assert (
        confirmed["payload"]["message"]
        == f"Registration confirmed for Workshop. Date/time: 01 Mar 2030, 09:00 SGT – 01 Mar 2030, 17:00 SGT. Venue: Hall A. Registration reference: {ref}."
    )
    assert confirmed["payload"]["destination"] == dict(
        kind="attendee-registration", registrationId=ref
    )
    # DR: published replay must not duplicate or erase read state. The following withdrawal is a FIFO sentinel.
    headers = {"X-Dev-User-Id": first, "X-Dev-Role": "Attendee"}
    marked = stack.call(
        "notification",
        "PATCH",
        f"/notifications/{source}",
        headers=headers,
        json=dict(read=True),
    )["notification"]
    envelope = intents("Registration")[0]["envelope"]
    from conftest import ROOT

    replay = subprocess.run(
        [
            str(ROOT / "services/event-workflow-service/.venv/bin/python"),
            "-c",
            "import json,sys; from app.dispatcher import publish; publish(json.load(sys.stdin))",
        ],
        input=json.dumps(envelope),
        text=True,
        capture_output=True,
        env=stack.env,
        cwd=ROOT / "services/event-workflow-service",
        timeout=20,
    )
    assert replay.returncode == 0, replay.stderr
    # AC2: successful withdrawal remains successful independently of later delivery.
    stack.call(
        "attendee-registration",
        "PATCH",
        f"/registrations/{ref}/withdraw",
        json=dict(attendeeId=first),
    )
    withdrawal = str(intents("Registration", "registration.withdrawn")[0]["source_id"])
    stack.dispatch("registration")
    alert = stack.delivered(first, withdrawal)
    assert alert["payload"]["message"] == "Registration withdrawn for Workshop."
    old = [n for n in stack.inbox(first) if n["id"] == source]
    assert len(old) == 1 and old[0]["readAt"] == marked["readAt"]
    assert register(first) == ref
    second_ref = register(second)
    third_ref = register(withdrawn)
    stack.call(
        "attendee-registration",
        "PATCH",
        f"/registrations/{third_ref}/withdraw",
        json=dict(attendeeId=withdrawn),
    )
    stack.dispatch("registration")
    # AC3: a high-impact edit is silent until final safety approval.
    headers = {"X-Internal-Service-Token": "synthetic"}
    next_round = str(uuid4())
    result = stack.call(
        "event",
        "PATCH",
        f"/events/{event}/details",
        headers=headers,
        json=dict(
            coordinatorId=world["coordinator"],
            changes=dict(preferredEndDate="2030-03-01T18:00:00"),
            safetyRecheck=dict(
                withdrawnSafetyCheckId=world["round_id"],
                safetyCheckId=next_round,
                roundNumber=2,
                venueBefore="Hall A",
            ),
        ),
    )
    assert result["status"] == "Pending Safety Check"
    assert intents("Event", "attendee.updated-fanout") == []
    stack.call(
        "event",
        "PATCH",
        f"/events/{event}/safety-status",
        headers=headers,
        json=dict(
            status="Confirmed",
            safetyCheckId=next_round,
            roundNumber=2,
            attendeeVenue="Hall A",
            decidedBy=world["coordinator"],
        ),
    )
    # DR Option A: membership changes after the business event but before first preparation count.
    stack.call(
        "attendee-registration",
        "PATCH",
        f"/registrations/{second_ref}/withdraw",
        json=dict(attendeeId=second),
    )
    assert register(withdrawn) == third_ref
    stack.dispatch("registration")
    stack.dispatch("event")
    updates = intents("Event", "attendee.event-updated")
    assert {r["source"]["recipientId"] for r in updates} == {first, withdrawn}
    assert len(updates) == 2
    assert {
        (r["source"]["recipientId"], r["source"]["registrationId"]) for r in updates
    } == {(first, ref), (withdrawn, third_ref)}
    for update in updates:
        message = stack.delivered(
            update["source"]["recipientId"], str(update["source_id"])
        )
        assert (
            message["payload"]["message"]
            == "Workshop was updated. End date/time: 01 Mar 2030, 17:00 SGT → 01 Mar 2030, 18:00 SGT."
        )
        expected_ref = {first: ref, withdrawn: third_ref}[update["source"]["recipientId"]]
        assert message["payload"]["details"]["registrationId"] == expected_ref
        assert message["payload"]["destination"] == dict(
            kind="attendee-registration", registrationId=expected_ref
        )
    # Later membership changes cannot rewrite already frozen children/content.
    stack.call(
        "attendee-registration",
        "PATCH",
        f"/registrations/{third_ref}/withdraw",
        json=dict(attendeeId=withdrawn),
    )
    assert register(second) == second_ref
    stack.dispatch("registration")
    assert intents("Event", "attendee.event-updated") == updates
    # Cancellation is a business status change, never a registration mutation.
    final_round = str(uuid4())
    stack.call(
        "event",
        "PATCH",
        f"/events/{event}/details",
        headers=headers,
        json=dict(
            coordinatorId=world["coordinator"],
            changes=dict(preferredEndDate="2030-03-01T19:00:00"),
            safetyRecheck=dict(
                withdrawnSafetyCheckId=next_round,
                safetyCheckId=final_round,
                roundNumber=3,
                venueBefore="Hall A",
            ),
        ),
    )
    before = stack.query('SELECT * FROM public."Registration" ORDER BY registration_id')
    stack.call(
        "event",
        "PATCH",
        f"/events/{event}/safety-status",
        headers=headers,
        json=dict(
            status="Cancelled",
            safetyCheckId=final_round,
            roundNumber=3,
            decidedBy=world["coordinator"],
            remarks="Unsafe",
        ),
    )
    stack.dispatch("event")
    cancellations = intents("Event", "attendee.event-cancelled")
    assert {r["source"]["recipientId"] for r in cancellations} == {first, second}
    assert len(cancellations) == 2
    assert {
        (r["source"]["recipientId"], r["source"]["registrationId"]) for r in cancellations
    } == {(first, ref), (second, second_ref)}
    for item in cancellations:
        message = stack.delivered(item["source"]["recipientId"], str(item["source_id"]))
        expected_ref = {first: ref, second: second_ref}[item["source"]["recipientId"]]
        assert message["payload"]["details"]["registrationId"] == expected_ref
        assert message["payload"]["destination"] == dict(
            kind="attendee-registration", registrationId=expected_ref
        )
        assert (
            stack.delivered(item["source"]["recipientId"], str(item["source_id"]))[
                "payload"
            ]["message"]
            == "Workshop was cancelled."
        )
    assert (
        stack.query('SELECT * FROM public."Registration" ORDER BY registration_id')
        == before
    )
    history = stack.call(
        "attendee-registration", "GET", f"/registrations?attendeeId={first}"
    )["registrations"]
    assert (
        history[0]["event"]["status"] == "Cancelled"
        and history[0]["registration"]["status"] == "Confirmed"
    )
    denied = __import__("httpx").patch(
        stack.urls["notification"] + f"/notifications/{source}",
        headers={"X-Dev-User-Id": second, "X-Dev-Role": "Attendee"},
        json=dict(read=True),
    )
    assert denied.status_code == 404
    assert (
        stack.query('SELECT count(*) AS n FROM public."NotificationFailure"')[0]["n"]
        == 0
    )
