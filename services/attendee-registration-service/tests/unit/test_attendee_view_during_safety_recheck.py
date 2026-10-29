"""SCRUM-153 Re-check Safety After High-Impact Changes and SCRUM-150 Approve Operational Safety Check: Attendee Registration Service unit tests.

Story (SCRUM-153): As an Event Coordinator, I want a safety approval to be withdrawn when a high-impact detail changes afterwards, so that the event is never prepared on the basis of an outdated safety review.
Story (SCRUM-150): As a Safety Officer, I want to approve an event's operational safety arrangements, so that the event can proceed to preparation.
Real:       the /registrations route and clients.get_historical_events.
Doubled:    the Event, Registration and User HTTP adapters (monkeypatched in route tests, respx in adapter tests).
Not proven: the Event Service overlay rule (Event Service's own suites) and the browser.

SCRUM-153
AC1  Given an event is 'Confirmed', when its date/time, expected attendance, venue requirements, equipment requirements or accessibility needs change, then its status returns to 'Pending Safety Check' and the coordinator is told why.
     Not covered here: owned by Event Service's test_event_details_recheck.py.
AC2  Given only a low-impact field changes (name, description, purpose, registration needs), then the event stays 'Confirmed'.
     Not covered here: owned by Event Service's test_event_details_recheck.py.
AC3  Given a safety approval is withdrawn, then it stays visible in the event's safety history.
     Not covered here: owned by Event Service's test_event_details_recheck.py.
AC4  Given a high-impact change to a 'Confirmed' event is waiting for its new safety check, when a registered Attendee views the event, then they still see the previously approved details, and the changed details are shown to them only after the Safety Officer approves the new safety check.
AC5  Given the new safety check ends without approval (changes requested or the event is cancelled), then registered Attendees are never shown the unapproved change, and they continue to see the last approved details or the cancellation.
     Not covered here: which details apply is decided by Event Service; this composite passes them through exactly as in AC4.
SCRUM-150
AC1  Given an event is 'Pending Safety Check', when I approve it, then its status changes to 'Confirmed'.
     Not covered here: owned by Event Service's test_safety_approve_status.py.
AC2  Given I approve an event, then the safety check is recorded with the status 'Safety Approved', together with my identity, the approval timestamp and any optional remarks, in the event's history.
     Not covered here: owned by Event Service's test_safety_approve_status.py.
AC3  Given an event is not 'Pending Safety Check', then the approve action is not available and an API call is rejected without changing the event.
     Not covered here: owned by Event Service's test_safety_approve_status.py.
AC4  Given the safety check I approve follows a high-impact change, when I approve it, then the changed details become visible to registered Attendees.
AC = acceptance criterion; DR = supporting design rule.
"""
import pytest
import respx
from httpx import Response

from app import clients, create_app, routes
from tests.unit.factories import signed_in

ATTENDEE = "22222222-2222-4222-8222-222222222222"
EVENT = "11111111-1111-4111-8111-111111111111"
REFERENCE = "33333333-3333-4333-8333-333333333333"
REGISTRATION = dict(registration_id=REFERENCE, event_id=EVENT, attendee_id=ATTENDEE, status="Confirmed")


def summary(event_id=EVENT, **overrides):
    """GET /events/attendee-summaries item, copied from
    services/event-service/app/models.py::list_attendee_event_summaries (via _summary + attendee_view)."""
    return {"id": event_id, "eventName": "Workshop", "status": "Pending Safety Check", "coordinatorId": None,
            "startTime": "2030-03-01T09:00:00", "endTime": "2030-03-01T17:00:00",
            "attendeeVenueName": "Hall A", **overrides}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(routes, "get_attendee_registrations", lambda: [dict(REGISTRATION)])
    monkeypatch.setattr(routes, "get_user", lambda attendee: dict(username="Synthetic", email="user@example.com"))
    return signed_in(create_app({"TESTING": True, "FRONTEND_ORIGIN": "http://localhost:5174"}).test_client())


def history(*events):
    """Stand-in for clients.get_historical_events, recording which ids it was asked for."""
    asked = []

    def lookup(event_ids):
        asked.append(set(event_ids))
        return list(events)
    lookup.asked = asked
    return lookup


# AC4 ----
def test_ac4_pending_event_is_listed_with_the_approved_details_it_was_given(client, monkeypatch):
    """Normal: the event is Pending Safety Check, so it is not in the Confirmed catalogue and
    comes from the history lookup with its approved details. The route passes them through
    unchanged and leaves the registration itself alone.
    """
    pending = {**summary(), "preferredStartDate": "2030-03-01T09:00:00",
               "preferredEndDate": "2030-03-01T17:00:00", "description": "", "purpose": ""}
    lookup = history(pending)
    monkeypatch.setattr(routes, "get_confirmed_events", lambda: [])
    monkeypatch.setattr(routes, "get_historical_events", lookup)

    response = client.get(f"/registrations")

    assert response.status_code == 200
    [item] = response.json["registrations"]
    assert item["event"] == pending
    assert item["registration"]["status"] == "Confirmed"
    assert lookup.asked == [{EVENT}]


def test_ac4_history_adapter_calls_attendee_summaries_and_keeps_venue_name():
    """Boundary: the real adapter over a respx-stubbed Event Service. It must call the
    attendee-facing endpoint (an unstubbed /events/summaries call would fail the test),
    add the page's date aliases and keep attendeeVenueName.
    """
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        route = router.get(f"{clients.EVENT_SERVICE_URL}/events/attendee-summaries").mock(
            return_value=Response(200, json={"events": [summary()]}))

        events = clients.get_historical_events([EVENT])

    assert dict(route.calls[0].request.url.params) == {"ids": EVENT}
    assert events == [{**summary(), "preferredStartDate": "2030-03-01T09:00:00",
                       "preferredEndDate": "2030-03-01T17:00:00", "description": "", "purpose": ""}]


def test_ac4_history_adapter_batches_more_than_100_ids():
    """Boundary: 101 ids are sent as two sorted batches of 100 and 1."""
    ids = [f"11111111-1111-4111-8111-{index:012d}" for index in range(101)]
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        route = router.get(f"{clients.EVENT_SERVICE_URL}/events/attendee-summaries").mock(
            return_value=Response(200, json={"events": []}))

        clients.get_historical_events(reversed(ids))

    assert [call.request.url.params["ids"].split(",") for call in route.calls] == [ids[:100], ids[100:]]


# SCRUM-150 AC4 ----
def test_scrum150_ac4_confirmed_events_come_from_the_catalogue_without_history_lookup(client, monkeypatch):
    """Normal: once approved the event is back in the Confirmed catalogue with its new
    times, so no history (overlay) lookup happens at all.
    """
    confirmed = dict(id=EVENT, eventName="Workshop", status="Confirmed",
                     preferredStartDate="2030-03-02T09:00:00", preferredEndDate="2030-03-02T18:00:00")

    def no_history(event_ids):
        raise AssertionError("history lookup must not run for a Confirmed event")
    monkeypatch.setattr(routes, "get_confirmed_events", lambda: [confirmed])
    monkeypatch.setattr(routes, "get_historical_events", no_history)

    response = client.get(f"/registrations")

    assert response.status_code == 200
    assert response.json["registrations"][0]["event"] == confirmed


# DR ----
def test_dr_attendee_summaries_failure_returns_502(client, monkeypatch):
    """Failure: the attendee-summaries lookup fails, so the page gets today's 502 message."""
    def broken(event_ids):
        raise RuntimeError("Event Service unavailable")
    monkeypatch.setattr(routes, "get_confirmed_events", lambda: [])
    monkeypatch.setattr(routes, "get_historical_events", broken)

    response = client.get(f"/registrations")

    assert response.status_code == 502
    assert response.json == {"message": "Unable to load your registrations right now."}
