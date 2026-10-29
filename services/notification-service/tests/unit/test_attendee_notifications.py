"""SCRUM-46 Attendee Registration and Update Notifications: Notification unit tests.

Story: As an Attendee, I want to receive notifications about my registration status, so that I can confirm my place and stay updated on event changes.

Real: wire parser. Doubled: no storage exercised.
Not proven: inbox SQL/dedup, broker delivery, or authentication.
AC1 Given an Attendee successfully registers for an event, the system sends an in-app notification confirming their registration with the event name, date, time, venue, and registration reference number.
AC2 Given an Attendee successfully withdraws their registration, the system sends an in-app notification confirming the withdrawal with the event name.
AC3 Given an event cancellation takes effect, or a change to its date, time or venue is approved and applied, all currently registered Attendees receive an in-app notification with the event name and cancellation status or updated details, as applicable.
AC1-3 wire acceptance is covered here; business mutations belong to their owners.
AC = acceptance criterion; DR = supporting design rule.
"""

import json
import pytest
from app.consumer import parse


# AC1 / AC2 / AC3 ---- consumer wire acceptance
@pytest.mark.parametrize(
    "kind",
    [
        "registration.confirmed",
        "registration.withdrawn",
        "attendee.event-cancelled",
        "attendee.event-updated",
    ],
)
def test_ac1_ac2_ac3_attendee_envelopes_accept_only_matching_registration_targets(kind):
    """Normal/conflict: parse each of the four attendee message types with a UUID registration link.
    Require unchanged wire content, then replace that link with an internal event
    page and require rejection. Types mean confirmation (AC1), withdrawal (AC2), and
    cancellation/update (AC3). The actual JSON parser runs without storage or broker;
    this checks destination validation, not producer wording or inbox persistence.
    """
    ref = "33333333-3333-4333-8333-333333333333"
    value = dict(
        version=1,
        id="44444444-4444-4444-8444-444444444444",
        type=kind,
        recipientId="22222222-2222-4222-8222-222222222222",
        createdAt="2030-01-01T00:00:00+00:00",
        message="Workshop notification.",
        destination=dict(kind="attendee-registration", registrationId=ref),
        details=dict(
            eventId="11111111-1111-4111-8111-111111111111",
            eventName="Workshop",
            registrationId=ref,
            startDateTime="2030-03-01T01:00:00+00:00",
            endDateTime="2030-03-01T09:00:00+00:00",
            venueName="Hall A",
            changes={"venueName": ["Hall A", "Hall C"]},
        ),
    )
    assert parse(json.dumps(value)) == value
    value["destination"] = {
        "kind": "event-details",
        "eventId": value["details"]["eventId"],
    }
    with pytest.raises(ValueError):
        parse(json.dumps(value))


# Supporting DR ---- reject incomplete wire content before storage
@pytest.mark.parametrize(
    "defect",
    ["no-name", "wrong-recipient", "missing-venue", "empty-changes", "invalid-pair"],
)
def test_dr_malformed_attendee_content_is_rejected_before_storage(defect):
    """Failure: corrupt one required field in an otherwise independent attendee envelope.
    no-name blanks the event name; wrong-recipient disagrees with top-level identity;
    missing-venue removes confirmation context; empty-changes removes an update's
    delta; invalid-pair makes before and after identical. The real wire parser must
    raise before storage can be called, avoiding incomplete/misdirected alerts.
    No broker or SQL runs, so durable quarantine is outside this case's evidence.
    """
    from tests.unit.factories import attendee_envelope

    value = attendee_envelope(
        "attendee.event-updated"
        if defect in ("empty-changes", "invalid-pair")
        else "registration.confirmed"
    )
    if defect == "no-name":
        value["details"]["eventName"] = ""
    elif defect == "wrong-recipient":
        value["details"]["recipientId"] = value["id"]
    elif defect == "missing-venue":
        value["details"].pop("venueName")
    elif defect == "empty-changes":
        value["details"]["changes"] = {}
    else:
        value["details"]["changes"] = {"venueName": ["Hall A", "Hall A"]}
    with pytest.raises(ValueError):
        parse(json.dumps(value))
