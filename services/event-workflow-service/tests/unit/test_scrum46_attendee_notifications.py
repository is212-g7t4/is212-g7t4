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
- The event-workflow notification workers: they claim jobs from the owning
  service's outbox over HTTP, look up current recipients and display facts, ask
  the owner to freeze the envelope, publish the frozen envelope to RabbitMQ and
  mark it published, retrying or holding on failure.
- Assertions are on the envelopes frozen and published, call order, and
  retry/hold decisions.

Doubled
-------
- Owner outbox and lookup HTTP (Event, User, Registration, Venue Availability):
  Stub (respx / monkeypatched httpx fixtures) - canned replies; requests
  inspected.
- RabbitMQ publisher (pika): Mock - publish arguments, confirms and persistence
  inspected.

Not proven
----------
- That the owner freezes the envelope in the same transaction as the change (->
  the owning service's notification tests and integration tests).
- That Notification Service stores and shows the inbox item (->
  notification-service consumer tests and frontend NotificationCenter tests).
"""

from unittest.mock import Mock
import pytest
from app.dispatcher import dispatch_once

from tests.unit.factories import (
    ATTENDEE_EVENT as EVENT,
    ATTENDEE_USER as USER,
    ATTENDEE_REF as REF,
    ATTENDEE_JOB as JOB,
    attendee_job as job,
)


@pytest.mark.parametrize(
    "kind,message",
    [
        (
            "registration.confirmed",
            "Registration confirmed for Workshop. Date/time: 01 Mar 2030, 09:00 SGT – 01 Mar 2030, 17:00 SGT. Venue: Hall A. Registration reference: "
            + REF
            + ".",
        ),
        ("registration.withdrawn", "Registration withdrawn for Workshop."),
    ],
    ids=["registration_confirmed", "registration_withdrawn"],
)
def test_ac1_ac2_registration_alert_targets_attendee_with_required_content(
    kind, message
):
    """
    Summary: dispatch_once on one claimed registration.confirmed job publishes
        "Registration confirmed for Workshop. Date/time: 01 Mar 2030, 09:00 SGT
        – 01 Mar 2030, 17:00 SGT. Venue: Hall A. Registration reference: <ref>."
        and on a registration.withdrawn job publishes "Registration withdrawn
        for Workshop."; each envelope links to the attendee-registration page
        for the registration id and the job is marked published.
    AC1: Given an Attendee successfully registers for an event, the system
        sends an in-app notification confirming their registration with the
        event name, date, time, venue, and registration reference number.
    AC2: Given an Attendee successfully withdraws their registration, the
        system sends an in-app notification confirming the withdrawal with the
        event name.
    Double: Stub (api.claim returns the registration job; api.registration_details
        returns Workshop, 01 Mar 2030 01:00-09:00 UTC, Hall A; api.freeze echoes
        the draft), Mock (broker called once with the envelope; published
        called once)
    """
    # Arrange (Given)
    api = Mock()
    api.claim.return_value = [job(kind)]
    api.registration_details.return_value = dict(
        eventName="Workshop",
        startDateTime="2030-03-01T01:00:00+00:00",
        endDateTime="2030-03-01T09:00:00+00:00",
        venueName="Hall A",
    )
    api.freeze.side_effect = lambda j, e: e
    broker = Mock()

    # Act (When)
    dispatch_once(api, broker)

    # Assert (Then)
    assert broker.call_count == 1
    envelope = broker.call_args.args[0]
    assert envelope["message"] == message
    assert envelope["destination"] == dict(
        kind="attendee-registration", registrationId=REF
    )
    assert envelope["details"]["registrationId"] == REF
    api.published.assert_called_once()


@pytest.mark.parametrize(
    "kind", ["attendee.cancelled-fanout", "attendee.updated-fanout"],
    ids=["cancelled_fanout", "updated_fanout"],
)
def test_ac3_change_fanout_freezes_first_attendee_list(kind):
    """
    Summary: dispatch_once on one claimed attendee.cancelled-fanout or
        attendee.updated-fanout job looks up the attendee recipients once for
        the event and sends them to the owner in a single "expand" operation;
        nothing is published to the broker at this stage.
    AC3: Given an event cancellation takes effect, or a change to its date,
        time or venue is approved and applied, all currently registered
        Attendees receive an in-app notification with the event name and
        cancellation status or updated details, as applicable.
    Double: Stub (api.claim returns the fan-out job; api.attendee_recipients
        returns one recipient), Mock (attendee_recipients called once with the
        event id; operation called once with "expand" and those recipients;
        broker not called)
    """
    # Arrange (Given)
    api = Mock()
    api.claim.return_value = [job(kind)]
    recipients = [dict(recipientId=USER, registrationId=REF)]
    api.attendee_recipients.return_value = recipients
    broker = Mock()

    # Act + Assert (When / Then)
    assert dispatch_once(api, broker) == 1
    api.attendee_recipients.assert_called_once_with(EVENT)
    api.operation.assert_called_once_with(
        api.claim.return_value[0], "expand", recipients=recipients
    )
    broker.assert_not_called()


@pytest.mark.parametrize(
    "kind,changes,message",
    [
        ("attendee.event-cancelled", None, "Workshop was cancelled."),
        (
            "attendee.event-updated",
            {"venueName": ["Hall A", "Hall C"]},
            "Workshop was updated. Venue: Hall A → Hall C.",
        ),
        (
            "attendee.event-updated",
            {
                "startDateTime": ["2030-03-01T09:00:00", "2030-03-02T09:00:00+08:00"],
                "endDateTime": [
                    "2030-03-01T17:00:00+08:00",
                    "2030-03-02T17:00:00+08:00",
                ],
                "venueName": ["Hall A", "Hall C"],
            },
            "Workshop was updated. Start date/time: 01 Mar 2030, 09:00 SGT → 02 Mar 2030, 09:00 SGT; End date/time: 01 Mar 2030, 17:00 SGT → 02 Mar 2030, 17:00 SGT; Venue: Hall A → Hall C.",
        ),
    ],
    ids=["cancelled", "venue_changed", "schedule_changed"],
)
def test_ac3_change_alert_publishes_saved_details_without_rereading_event(
    kind, changes, message
):
    """
    Summary: dispatch_once on one claimed attendee.event-cancelled or
        attendee.event-updated job publishes "Workshop was cancelled." or
        "Workshop was updated. " followed by the venue and/or start/end
        changes from the saved details (shown in Singapore time), with a link to
        the attendee-registration page, without looking the event up again.
    AC3: Given an event cancellation takes effect, or a change to its date,
        time or venue is approved and applied, all currently registered
        Attendees receive an in-app notification with the event name and
        cancellation status or updated details, as applicable.
    Double: Stub (api.claim returns the job carrying its saved eventName and
        changes; api.freeze echoes the draft), Mock (broker receives the
        message and destination; registration_details not called)
    """
    # Arrange (Given)
    item = job(kind)
    item["source"]["eventName"] = "Workshop"
    if changes:
        item["source"]["changes"] = changes
    api = Mock()
    api.claim.return_value = [item]
    api.freeze.side_effect = lambda j, e: e
    broker = Mock()

    # Act (When)
    dispatch_once(api, broker)

    # Assert (Then)
    assert broker.call_args.args[0]["message"] == message
    assert broker.call_args.args[0]["destination"] == dict(
        kind="attendee-registration", registrationId=REF
    )
    api.registration_details.assert_not_called()


@pytest.mark.parametrize("state", ["confirmed", "withdrawn", "no-approved"], ids=["confirmed", "withdrawn", "no_approved_booking"])
def test_ac1_ac2_registration_alert_names_approved_booking_venue(
    attendee_http, state
):
    """
    Summary: api.registration_details for a confirmed registration returns the
        event name, start/end times and the venue name "Hall A" taken from the
        earliest Approved venue booking (ignoring a later Approved and a
        Pending Review booking); for a withdrawal it returns only the event
        name and reads no booking; with no Approved booking it raises
        ValueError.
    AC1: Given an Attendee successfully registers for an event, the system
        sends an in-app notification confirming their registration with the
        event name, date, time, venue, and registration reference number.
    AC2: Given an Attendee successfully withdraws their registration, the
        system sends an in-app notification confirming the withdrawal with the
        event name.
    Double: Stub (Event Service notification-context returns Workshop with
        its times; Venue Availability returns the parametrized bookings; Venue
        Service returns {"venue": {"name": "Hall A"}}; the withdrawn case
        stubs no booking or venue route)
    """
    api, http = attendee_http
    # Event app/__init__.py::notification_context includeSchedule opt-in.
    http.get(
        f"http://event.test/internal/events/{EVENT}/notification-context",
        params={"includeSchedule": "true"},
    ).respond(
        200,
        json=dict(
            eventName="Workshop",
            startDateTime="2030-03-01T09:00:00",
            endDateTime="2030-03-01T17:00:00",
        ),
    )
    if state != "withdrawn":
        # Venue Availability app/models.py::serialize returns requestedStartTime and /events/<id>/venue-bookings.
        bookings = (
            []
            if state == "no-approved"
            else [
                dict(
                    id="later",
                    venueId=JOB,
                    status="Approved",
                    requestedStartTime="2030-03-01T02:00:00+00:00",
                ),
                dict(
                    id="pending",
                    venueId=JOB,
                    status="Pending Review",
                    requestedStartTime="2030-03-01T00:00:00+00:00",
                ),
                dict(
                    id="first",
                    venueId=REF,
                    status="Approved",
                    requestedStartTime="2030-03-01T01:00:00+00:00",
                ),
            ]
        )
        http.get(f"http://availability.test/events/{EVENT}/venue-bookings").respond(
            200, json={"bookings": bookings}
        )
        if state == "confirmed":
            # Venue app/__init__.py::venue returns a venue wrapper.
            http.get(f"http://venue.test/venues/{REF}").respond(
                200, json={"venue": {"name": "Hall A"}}
            )
    if state == "no-approved":
        with pytest.raises(ValueError):
            api.registration_details(dict(eventId=EVENT))
    else:
        result = api.registration_details(
            dict(eventId=EVENT, withdrawal=state == "withdrawn")
        )
        assert result == (
            {"eventName": "Workshop"}
            if state == "withdrawn"
            else dict(
                eventName="Workshop",
                startDateTime="2030-03-01T09:00:00",
                endDateTime="2030-03-01T17:00:00",
                venueName="Hall A",
            )
        )


@pytest.mark.parametrize(
    "state", ["two-confirmed", "empty", "invalid-list", "wrong-event"],
    ids=["two_confirmed", "empty", "invalid_list", "wrong_event"],
)
def test_ac3_attendee_lookup_skips_withdrawn_and_refuses_bad_responses(
    attendee_http, state
):
    """
    Summary: api.attendee_recipients for an event returns only the Confirmed
        registrations (two recipients, the Withdrawn one skipped); an empty
        registration list returns []; a non-list body, or a registration
        belonging to another event, raises ValueError.
    AC3: Given an event cancellation takes effect, or a change to its date,
        time or venue is approved and applied, all currently registered
        Attendees receive an in-app notification with the event name and
        cancellation status or updated details, as applicable.
    Double: Stub (Registration Service GET /registrations?eventId=<id> returns
        three rows (two Confirmed, one Withdrawn), an empty list, {} or a row
        for another event); no other service is stubbed
    """
    api, http = attendee_http
    rows = [
        dict(event_id=EVENT, attendee_id=USER, registration_id=REF, status="Confirmed"),
        dict(
            event_id=EVENT, attendee_id=JOB, registration_id=EVENT, status="Confirmed"
        ),
        dict(event_id=EVENT, attendee_id=REF, registration_id=JOB, status="Withdrawn"),
    ]
    if state == "empty":
        rows = []
    elif state == "invalid-list":
        rows = {}
    elif state == "wrong-event":
        rows[0]["event_id"] = JOB
    # Registration app/__init__.py::registrations returns all statuses in this wrapper.
    http.get(
        "http://registration.test/registrations", params={"eventId": EVENT}
    ).respond(200, json={"registrations": rows})
    if state in ("invalid-list", "wrong-event"):
        with pytest.raises(ValueError):
            api.attendee_recipients(EVENT)
    else:
        assert api.attendee_recipients(EVENT) == (
            []
            if state == "empty"
            else [
                dict(recipientId=USER, registrationId=REF),
                dict(recipientId=JOB, registrationId=EVENT),
            ]
        )


def test_registration_worker_uses_registration_outbox(monkeypatch):
    """
    Summary: With OUTBOX_OWNER set to registration, OutboxAPI().base is
        http://registration.test (trailing slash removed), so registration
        alerts are claimed from Registration Service's outbox.
    Supporting design check: registration and withdrawal alerts are claimed
        from Registration Service's own outbox, not Event Service's
    Double: Stub (OUTBOX_OWNER, REGISTRATION_SERVICE_URL and
        INTERNAL_SERVICE_TOKEN set with monkeypatch); no HTTP request is made
        and the base URL is asserted
    """
    # Arrange (Given)
    from app.dispatcher import OutboxAPI

    monkeypatch.setenv("OUTBOX_OWNER", "registration")
    monkeypatch.setenv("REGISTRATION_SERVICE_URL", "http://registration.test/")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "synthetic")

    # Act + Assert (When / Then)
    assert OutboxAPI().base == "http://registration.test"


def test_ac1_registration_alert_uses_saved_snapshot_not_later_event():
    """
    Summary: dispatch_once on a claimed registration.confirmed job that carries
        its saved event name, times and venue publishes an envelope whose
        details equal that saved source; the event is never re-read
        (registration_details would raise if called).
    AC1: Given an Attendee successfully registers for an event, the system
        sends an in-app notification confirming their registration with the
        event name, date, time, venue, and registration reference number.
    Double: Stub (api.claim returns the job with the saved snapshot;
        api.registration_details raises RuntimeError if called; api.freeze
        echoes the draft), Mock (broker called once; registration_details not
        called)
    """
    # Arrange (Given)
    item = job("registration.confirmed")
    item["source"].update(
        eventName="Workshop",
        startDateTime="2030-03-01T09:00:00+08:00",
        endDateTime="2030-03-01T17:00:00+08:00",
        venueName="Hall A",
    )
    api = Mock()
    api.claim.return_value = [item]
    api.registration_details.side_effect = RuntimeError("Latest event must not be read")
    api.freeze.side_effect = lambda j, e: e
    broker = Mock()

    # Act (When)
    dispatch_once(api, broker)

    # Assert (Then)
    assert broker.call_count == 1
    assert broker.call_args.args[0]["details"] == item["source"]
    api.registration_details.assert_not_called()
