"""SCRUM-46 Attendee Registration and Update Notifications: Safety Check unit tests.

Story: As an Attendee, I want to receive notifications about my registration status, so that I can confirm my place and stay updated on event changes.

Real: composite HTTP request construction. Doubled: other services via respx.
Not proven: Event storage, approval authorization or broker delivery.
AC1 Given an Attendee successfully registers for an event, the system sends an in-app notification confirming their registration with the event name, date, time, venue, and registration reference number.
AC2 Given an Attendee successfully withdraws their registration, the system sends an in-app notification confirming the withdrawal with the event name.
AC3 Given an event cancellation takes effect, or a change to its date, time or venue is approved and applied, all currently registered Attendees receive an in-app notification with the event name and cancellation status or updated details, as applicable.
AC1/2 are covered by Registration/Workflow. AC3 captures actual pre-change venues here.
AC = acceptance criterion; DR = supporting design rule.
"""

import json
import httpx
import respx
from app import clients


# AC3 ----
def test_ac3_venue_withdrawal_captures_earliest_approved_booking_not_requirements(
    monkeypatch,
):
    """Normal: withdraw safety with late/early Approved bookings and an earlier Pending booking.
    The actual HTTP adapter must send Hall A, the earliest Approved venue, as
    venueBefore before the booking changes. Strict respx responses control the remote
    APIs; request construction is real. This prevents requirement text or the wrong
    booking from becoming the immutable comparison baseline, without proving a commit.
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
            event, "coord", "round", 1, True, "Venue changed"
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
)


@pytest.mark.parametrize(
    "state", ["final-venue", "lookup-outage", "already-confirmed-history"]
)
def test_ac3_safety_approval_carries_final_venue_only_for_the_current_review_cycle(
    monkeypatch, state
):
    """Boundary: approve through the real Safety route and HTTP adapters with strict remote doubles.
    final-venue sends Hall C with the Event decision; lookup-outage returns 502 before
    saving a decision; already-confirmed-history has a completed cycle after the
    baseline and must not reuse that stale venue context. This protects final facts
    and cycle boundaries, not Event's SQL transaction or concurrent booking writes.
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
            create_app()
            .test_client()
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
def test_dr_unusable_approved_venue_is_not_replaced_with_requirements(
    monkeypatch, state
):
    """Failure: enrich venue facts when no Approved booking exists or its venue name is blank.
    The real HTTP adapter must raise DownstreamError in no-approved and unnamed cases,
    rather than fabricate a hall from requirements. Strict HTTP doubles supply the
    upstream responses; this guards snapshot quality, not the remote venue database.
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
