"""
SCRUM-46: Attendee Registration and Update Notifications

User Story
----------
As an Attendee, I want to receive notifications about my registration status,
so that I can confirm my place and stay updated on event changes.

Acceptance Criteria
-------------------
AC1: Given an Attendee successfully registers for an event, the system sends an
     in-app notification confirming their registration with the event name,
     date, time, venue, and registration reference number.
AC2: Given an Attendee successfully withdraws their registration, the system
     sends an in-app notification confirming the withdrawal with the event
     name.
AC3: Given an event cancellation takes effect, or a change to its date, time or
     venue is approved and applied, all currently registered Attendees receive
     an in-app notification with the event name and cancellation status or
     updated details, as applicable.

Real
----
- app.consumer envelope parsing and the attendee notification validators
  (registration confirmed/withdrawn, event cancelled/updated) run for real.
- Assertions are on whether an envelope is accepted or rejected.

Doubled
-------
- Nothing: the parser is called directly; no storage is exercised.

Not proven
----------
- That the inbox row is committed and de-duplicated in real PostgreSQL (->
  tests/integration/, throwaway postgres:17.6).
- That the producer publishes this envelope to RabbitMQ and the UI shows it
  with a working link (-> the producing service's dispatcher tests and the
  frontend NotificationCenter tests).
"""

import json
import pytest
from app.consumer import parse


@pytest.mark.parametrize(
    "kind",
    [
        "registration.confirmed",
        "registration.withdrawn",
        "attendee.event-cancelled",
        "attendee.event-updated",
    ],
    ids=["registration_confirmed", "registration_withdrawn", "event_cancelled", "event_updated"],
)
def test_parse_attendee_envelope_accepts_each_kind_for_its_registration(kind):
    """
    Summary: Registration, withdrawal, cancellation and change notices are accepted only when they point at the attendee's registration.
    AC1: Given an Attendee successfully registers for an event, the system
        sends an in-app notification confirming their registration with the
        event name, date, time, venue, and registration reference number.
    AC2: Given an Attendee successfully withdraws their registration, the
        system sends an in-app notification confirming the withdrawal with the
        event name.
    AC3: Given an event cancellation takes effect, or a change to its date,
        time or venue is approved and applied, all currently registered
        Attendees receive an in-app notification with the event name and
        cancellation status or updated details, as applicable.
    Double: None
    """
    # Arrange (Given)
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

    # Act + Assert (When / Then)
    assert parse(json.dumps(value)) == value
    value["destination"] = {
        "kind": "event-details",
        "eventId": value["details"]["eventId"],
    }
    with pytest.raises(ValueError):
        parse(json.dumps(value))


@pytest.mark.parametrize(
    "defect",
    ["no-name", "wrong-recipient", "missing-venue", "empty-changes", "invalid-pair"],
    ids=["no_event_name", "wrong_recipient", "missing_venue", "empty_changes", "invalid_pair"],
)
def test_parse_attendee_envelope_with_malformed_content_is_rejected(defect):
    """
    Summary: An attendee notice missing its event name, venue or changes, or for someone else, is rejected.
    AC1: Given an Attendee successfully registers for an event, the system
        sends an in-app notification confirming their registration with the
        event name, date, time, venue, and registration reference number.
    AC3: Given an event cancellation takes effect, or a change to its date,
        time or venue is approved and applied, all currently registered
        Attendees receive an in-app notification with the event name and
        cancellation status or updated details, as applicable.
    Double: None
    """
    # Arrange (Given)
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

    # Act + Assert (When / Then)
    with pytest.raises(ValueError):
        parse(json.dumps(value))
