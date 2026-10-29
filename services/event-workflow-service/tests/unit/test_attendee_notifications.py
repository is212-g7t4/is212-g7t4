"""SCRUM-46 Attendee Registration and Update Notifications: Event Workflow unit tests.

Story: As an Attendee, I want to receive notifications about my registration status, so that I can confirm my place and stay updated on event changes.

Real: dispatcher preparation, freeze ordering and retry decisions.
Doubled: owner API and publisher. Not proven: SQL, broker delivery or authentication.
AC1 Given an Attendee successfully registers for an event, the system sends an in-app notification confirming their registration with the event name, date, time, venue, and registration reference number.
AC2 Given an Attendee successfully withdraws their registration, the system sends an in-app notification confirming the withdrawal with the event name.
AC3 Given an event cancellation takes effect, or a change to its date, time or venue is approved and applied, all currently registered Attendees receive an in-app notification with the event name and cancellation status or updated details, as applicable.
AC = acceptance criterion; DR = supporting design rule.
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


# AC1 / AC2 ---- action message preparation
# Supporting AC2 ---- withdrawal message
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
)
def test_ac1_ac2_registration_actions_use_attendee_destination_and_required_content(
    kind, message
):
    """Normal: dispatch a claimed confirmation or withdrawal with display enrichment supplied by an API double.
    Require one readable message, the exact registration destination/reference and
    owner completion. Confirmation includes schedule/venue/reference; withdrawal
    needs the event name. This checks dispatcher content, not owner persistence or
    broker delivery: freeze and publish are recording doubles.
    """
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
    dispatch_once(api, broker)
    assert broker.call_count == 1
    envelope = broker.call_args.args[0]
    assert envelope["message"] == message
    assert envelope["destination"] == dict(
        kind="attendee-registration", registrationId=REF
    )
    assert envelope["details"]["registrationId"] == REF
    api.published.assert_called_once()


# AC3 ---- audience and immutable event content
# --- first successful recipient preparation, never event-time audience history
@pytest.mark.parametrize(
    "kind", ["attendee.cancelled-fanout", "attendee.updated-fanout"]
)
def test_ac3_parent_freezes_the_first_prepared_attendee_list(kind):
    """Normal: dispatch either a cancellation-fanout or update-fanout parent.
    A doubled Registration lookup supplies the current audience; require one exact
    owner expand operation and no parent publication. Only recipient child jobs are
    inbox messages, and the first preparation selects membership. Owner storage and
    publisher are mocked, so atomic audience freezing belongs to Event integration.
    """
    api = Mock()
    api.claim.return_value = [job(kind)]
    recipients = [dict(recipientId=USER, registrationId=REF)]
    api.attendee_recipients.return_value = recipients
    broker = Mock()
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
)
def test_ac3_saved_event_details_publish_without_latest_state_lookup(
    kind, changes, message
):
    """Normal: dispatch child work with cancellation, venue-only, or combined saved changes.
    The dispatcher must publish the specified literal text and registration link
    without querying registration display facts again. This prevents delayed delivery
    from substituting later mutable event state. Claimed work, freeze and publisher
    are doubles; actual SQL/RabbitMQ are exercised in their other tiers.
    """
    item = job(kind)
    item["source"]["eventName"] = "Workshop"
    if changes:
        item["source"]["changes"] = changes
    api = Mock()
    api.claim.return_value = [item]
    api.freeze.side_effect = lambda j, e: e
    broker = Mock()
    dispatch_once(api, broker)
    assert broker.call_args.args[0]["message"] == message
    assert broker.call_args.args[0]["destination"] == dict(
        kind="attendee-registration", registrationId=REF
    )
    api.registration_details.assert_not_called()


# DR ---- actual HTTP contracts and failure isolation
@pytest.mark.parametrize("state", ["confirmed", "withdrawn", "no-approved"])
def test_dr_registration_enrichment_uses_actual_approved_booking_contract(
    attendee_http, state
):
    """Boundary: enrich a legacy registration through the real HTTP client with strict remote doubles.
    confirmed selects the earliest Approved booking, ignoring an earlier Pending row;
    withdrawn needs only the event name; no-approved must raise instead of inventing a
    venue. Expected fields follow each owner's serializer. This protects required
    message content but does not prove the remote services accept or store anything.
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
    "state", ["two-confirmed", "empty", "invalid-list", "wrong-event"]
)
def test_dr_attendee_lookup_filters_withdrawn_and_rejects_incomplete_responses(
    attendee_http, state
):
    """Boundary: read an event-filtered registration response through the real HTTP adapter.
    two-confirmed returns the exact attendee/reference pairs and ignores Withdrawn;
    empty is a valid zero audience. invalid-list supplies an object instead of rows,
    and wrong-event supplies an unrelated row: both must raise, not silently complete
    fanout. HTTP is strictly doubled; this proves filtering, not database membership.
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


def test_dr_registration_owner_mode_targets_registration_outbox(monkeypatch):
    """Configuration: construct the real outbox client with isolated registration-owner settings.
    Expect its base URL to target Registration, normalized without a trailing slash,
    so the additional worker does not poll Event by mistake. Environment changes are
    fixture-restored; constructing this client makes no network or broker request.
    """
    from app.dispatcher import OutboxAPI

    monkeypatch.setenv("OUTBOX_OWNER", "registration")
    monkeypatch.setenv("REGISTRATION_SERVICE_URL", "http://registration.test/")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "synthetic")
    assert OutboxAPI().base == "http://registration.test"


def test_ac1_saved_registration_snapshot_is_not_reconstructed_from_later_event_state():
    """Normal: dispatch an action that already contains its event name, period and Hall A snapshot.
    Make latest-state enrichment raise if called; the dispatcher must instead publish
    once with the exact saved details and never perform that lookup. This protects
    action-time content on delayed delivery, while API freeze and broker publication
    remain doubles rather than evidence of storage or actual delivery.
    """
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
    dispatch_once(api, broker)
    assert broker.call_count == 1
    assert broker.call_args.args[0]["details"] == item["source"]
    api.registration_details.assert_not_called()
