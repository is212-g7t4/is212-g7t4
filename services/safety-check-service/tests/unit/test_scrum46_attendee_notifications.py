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
- The venue named in attendees' update notices when a safety decision changes a
  Confirmed event: the venue the event is actually booked at, never the
  free-text venue requirements.
- We check the venue passed on for the notice.

Doubled
-------
- Event, Safety Check Record, Venue Availability, Venue, Equipment Request and
  User Services: answer as each test needs, fail, or do not answer in time
  [Stub]; we check which were asked, in what order, and what they were sent
  [Mock].
- Sign-in: a test key signs the caller's token (tests/conftest.py) [Stub].

Not proven
----------
- That the notices are created and delivered (-> event-service and
  notification-service SCRUM-46 tests).
"""

import json
import respx
from app import clients


def test_withdrawal_captures_earliest_approved_booking_venue(
    monkeypatch,
):
    """
    Summary: The update notice names the earliest approved booking's venue, not the event's requirements.
    AC3: Given an event cancellation takes effect, or a change to its date,
        time or venue is approved and applied, all currently registered
        Attendees receive an in-app notification with the event name and
        cancellation status or updated details, as applicable.
    Double: Venue Availability and Venue hold the bookings and venues [Stub];
        we check how the event is moved [Mock].
    """
    event = "11111111-1111-4111-8111-111111111111"
    monkeypatch.setattr(clients, "EVENT_SERVICE_URL", "http://event.test")
    monkeypatch.setattr(
        clients, "VENUE_AVAILABILITY_SERVICE_URL", "http://availability.test"
    )
    monkeypatch.setattr(clients, "VENUE_SERVICE_URL", "http://venue.test")
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as http:
        # Venue Availability app/models.py::serialize supplies requestedStartTime, not startDateTime.
        http.get(f"http://availability.test/events/{event}/venue-bookings").respond(
            200,
            json={
                "bookings": [
                    dict(
                        id="late",
                        venueId="b",
                        status="Approved",
                        requestedStartTime="2030-03-01T04:00:00+00:00",
                    ),
                    dict(
                        id="pending",
                        venueId="c",
                        status="Pending Review",
                        requestedStartTime="2030-03-01T00:00:00+00:00",
                    ),
                    dict(
                        id="early",
                        venueId="a",
                        status="Approved",
                        requestedStartTime="2030-03-01T01:00:00+00:00",
                    ),
                ]
            },
        )
        # Venue app/__init__.py::venues returns the catalogue wrapper.
        http.get("http://venue.test/venues").respond(
            200,
            json={"venues": [dict(id="a", name="Hall A"), dict(id="b", name="Hall B")]},
        )
        saved = http.patch(f"http://event.test/events/{event}/safety-status").respond(
            200, json={"status": "Approved"}
        )
        clients.set_event_venue_change_status(
            event, "round", 1, True, "Venue changed"
        )
        assert json.loads(saved.calls[0].request.content)["venueBefore"] == "Hall A"


import pytest
from app import create_app
from tests.unit.factories import (
    EVENT_ID,
    OFFICER_ID,
    RECORD_ID,
    event,
    record,
    user,
    booking,
    venue,
    signed_in,
)


@pytest.mark.parametrize(
    "state", ["final-venue", "lookup-outage", "already-confirmed-history"]
)
def test_approval_carries_final_venue_for_current_review_only(
    monkeypatch, state
):
    """
    Summary: An approval passes on the final venue only for the current review cycle.
    AC3: Given an event cancellation takes effect, or a change to its date,
        time or venue is approved and applied, all currently registered
        Attendees receive an in-app notification with the event name and
        cancellation status or updated details, as applicable.
    Double: Venue Availability and Venue hold the bookings and venues [Stub];
        we check how the event is moved [Mock].
    """
    for key, name in [
        ("EVENT_SERVICE_URL", "event"),
        ("USER_SERVICE_URL", "user"),
        ("VENUE_AVAILABILITY_SERVICE_URL", "availability"),
        ("VENUE_SERVICE_URL", "venue"),
        ("SAFETY_CHECK_RECORD_SERVICE_URL", "record"),
    ]:
        monkeypatch.setattr(clients, key, f"http://{name}.test")
    history = [
        dict(status="Approved", attendeeBaseline=dict(venueName="Hall A")),
        dict(status="Pending Safety Check"),
    ]
    if state == "already-confirmed-history":
        history.append(dict(status="Confirmed"))
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as http:
        # User app/models.py::serialize, Event app/models.py::serialize and Record app/models.py::serialize.
        http.get(f"http://user.test/users/{OFFICER_ID}").respond(200, json=user())
        http.get(f"http://event.test/events/{EVENT_ID}").respond(
            200, json=event("Pending Safety Check", actionHistory=history)
        )
        http.get("http://record.test/safety-check-records").respond(
            200, json={"safetyChecks": [record()]}
        )
        if state != "already-confirmed-history":
            route = http.get(
                f"http://availability.test/events/{EVENT_ID}/venue-bookings"
            )
            if state == "lookup-outage":
                route.respond(503, json={"message": "Synthetic outage"})
            else:
                route.respond(200, json={"bookings": [booking()]})
                http.get("http://venue.test/venues").respond(
                    200, json={"venues": [venue(name="Hall C")]}
                )
        if state != "lookup-outage":
            decision = http.patch(
                f"http://record.test/safety-check-records/{RECORD_ID}/decision"
            ).respond(200, json=record(status="Safety Approved"))
            saved = http.patch(
                f"http://event.test/events/{EVENT_ID}/safety-status"
            ).respond(200, json=event("Confirmed"))
        response = (
            signed_in(create_app().test_client())
            .post(
                "/safety-checks/approve",
                json=dict(eventId=EVENT_ID, safetyOfficerId=OFFICER_ID),
            )
        )
        assert response.status_code == (502 if state == "lookup-outage" else 200)
        if state != "lookup-outage":
            body = json.loads(saved.calls[0].request.content)
            assert body.get("attendeeVenue") == (
                "Hall C" if state == "final-venue" else None
            )
            assert decision.call_count == 1


@pytest.mark.parametrize("state", ["no-approved", "unnamed"])
def test_unusable_approved_venue_is_not_replaced_with_requirements(
    monkeypatch, state
):
    """
    Summary: With no usable approved venue, the requirements text is never shown as the venue.
    AC3: Given an event cancellation takes effect, or a change to its date,
        time or venue is approved and applied, all currently registered
        Attendees receive an in-app notification with the event name and
        cancellation status or updated details, as applicable.
    Double: Venue Availability and Venue hold the bookings and venues [Stub];
        we check how the event is moved [Mock].
    """
    monkeypatch.setattr(
        clients, "VENUE_AVAILABILITY_SERVICE_URL", "http://availability.test"
    )
    monkeypatch.setattr(clients, "VENUE_SERVICE_URL", "http://venue.test")
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as http:
        http.get(f"http://availability.test/events/{EVENT_ID}/venue-bookings").respond(
            200, json={"bookings": [] if state == "no-approved" else [booking()]}
        )
        if state == "unnamed":
            http.get("http://venue.test/venues").respond(
                200, json={"venues": [venue(name="")]}
            )
        with pytest.raises(clients.DownstreamError):
            clients.attendee_venue_name(EVENT_ID)
