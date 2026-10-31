"""
SCRUM-153: Re-check Safety After High-Impact Changes

User Story
----------
As an Event Coordinator, I want a safety approval to be withdrawn when a
high-impact detail changes afterwards, so that the event is never prepared on
the basis of an outdated safety review.

Acceptance Criteria
-------------------
AC1: Given an event is 'Confirmed', when its date/time, expected attendance,
     venue requirements, equipment requirements or accessibility needs change,
     then its status returns to 'Pending Safety Check' and the coordinator is
     told why.
AC2: Given only a low-impact field changes (name, description, purpose,
     registration needs), then the event stays 'Confirmed'.
AC3: Given a safety approval is withdrawn, then it stays visible in the event's
     safety history.
AC4: Given a high-impact change to a 'Confirmed' event is waiting for its new
     safety check, when a registered Attendee views the event, then they still
     see the previously approved details, and the changed details are shown to
     them only after the Safety Officer approves the new safety check.
AC5: Given the new safety check ends without approval (changes requested or the
     event is cancelled), then registered Attendees are never shown the
     unapproved change, and they continue to see the last approved details or
     the cancellation.

Real
----
- An attendee's registration list while a high-impact change awaits its safety
  check: the event's previously approved details are shown, taken from Event
  Service's attendee view.
- We check the event details the attendee sees, and which events were looked
  up.

Doubled
-------
- Registration and User Services: hold the attendee's registration and profile
  [Stub].
- Event Service: no longer lists the event as confirmed, and its attendee view
  returns the previously approved details, or fails [Stub]; we check the
  lookups [Mock]. Any unexpected outside call fails the test.
- Sign-in: a test key signs the caller's token (tests/unit/conftest.py) [Stub].

Not proven
----------
- That Event Service keeps the approved details while the change is pending (->
  event-service SCRUM-153 tests).
- What the attendee's browser shows (-> frontend
  AttendeeRegistrationsPage.test.tsx).
- AC1-AC3 and AC5 state transitions/history are owned by Event and Safety Check
  Services; this composite proves AC4's attendee-safe projection.
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


def test_ac4_list_my_registrations_during_recheck_shows_approved_details(client, monkeypatch):
    """
    Summary: While a high-impact change awaits its safety check, a registered attendee still sees the previously approved details, and their registration stays Confirmed.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: The event is no longer among the confirmed events, and Event
        Service's attendee view returns its previously approved details [Stub];
        we check that view was asked for this event [Mock].
    """
    pending = {**summary(), "preferredStartDate": "2030-03-01T09:00:00",
               "preferredEndDate": "2030-03-01T17:00:00", "description": "", "purpose": ""}
    lookup = history(pending)
    monkeypatch.setattr(routes, "get_confirmed_events", lambda: [])
    monkeypatch.setattr(routes, "get_historical_events", lookup)

    response = client.get("/registrations")

    assert response.status_code == 200
    [item] = response.json["registrations"]
    assert item["event"] == pending
    assert item["registration"]["status"] == "Confirmed"
    assert lookup.asked == [{EVENT}]


def test_ac4_history_adapter_uses_attendee_summaries_and_keeps_venue_name():
    """
    Summary: The event details shown to attendees come from Event Service's attendee view, which holds the approved details, venue included.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Event Service's attendee view returns the event [Stub]; any other
        outside call fails the test, and we check which event was asked for
        [Mock].
    """
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        route = router.get(f"{clients.EVENT_SERVICE_URL}/events/attendee-summaries").mock(
            return_value=Response(200, json={"events": [summary()]}))

        events = clients.get_historical_events([EVENT])

    assert dict(route.calls[0].request.url.params) == {"ids": EVENT}
    assert events == [{**summary(), "preferredStartDate": "2030-03-01T09:00:00",
                       "preferredEndDate": "2030-03-01T17:00:00", "description": "", "purpose": ""}]


def test_ac4_list_my_registrations_when_summaries_fail_returns_502(client, monkeypatch):
    """
    Summary: If the approved details cannot be loaded, the attendee gets an error rather than the unapproved changes.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: The event is no longer among the confirmed events, and Event
        Service's attendee view fails [Stub].
    """
    def broken(event_ids):
        raise RuntimeError("Event Service unavailable")
    monkeypatch.setattr(routes, "get_confirmed_events", lambda: [])
    monkeypatch.setattr(routes, "get_historical_events", broken)

    response = client.get("/registrations")

    assert response.status_code == 502
    assert response.json == {"message": "Unable to load your registrations right now."}


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_support_history_adapter_with_101_events_sends_two_batches():
    """
    Summary: Details for many events are fetched 100 at a time, so a long registration history still loads.
    Supporting design check: event lookups are batched to keep each request
        within size limits
    Double: Event Service's attendee view returns nothing [Stub]; any other
        outside call fails the test, and we check how the ids were batched
        [Mock].
    """
    ids = [f"11111111-1111-4111-8111-{index:012d}" for index in range(101)]
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        route = router.get(f"{clients.EVENT_SERVICE_URL}/events/attendee-summaries").mock(
            return_value=Response(200, json={"events": []}))

        clients.get_historical_events(reversed(ids))

    assert [call.request.url.params["ids"].split(",") for call in route.calls] == [ids[:100], ids[100:]]
