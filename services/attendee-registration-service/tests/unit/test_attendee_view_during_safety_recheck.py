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

SCRUM-150: Approve Operational Safety Check

User Story
----------
As a Safety Officer, I want to approve an event's operational safety
arrangements, so that the event can proceed to preparation.

Acceptance Criteria
-------------------
AC1: Given an event is 'Pending Safety Check', when I approve it, then its
     status changes to 'Confirmed'.
AC2: Given I approve an event, then the safety check is recorded with the
     status 'Safety Approved', together with my identity, the approval
     timestamp and any optional remarks, in the event's history.
AC3: Given an event is not 'Pending Safety Check', then the approve action is
     not available and an API call is rejected without changing the event.
AC4: Given the safety check I approve follows a high-impact change, when I
     approve it, then the changed details become visible to registered
     Attendees.

Real
----
- GET /registrations and clients.get_historical_events(): events missing from
  the Confirmed catalogue come from Event Service's attendee-facing summaries
  (the approved details), batched 100 at a time.
- Assertions are on the event details returned and the calls made.

Doubled
-------
- Event, Registration and User adapters: Stub (monkeypatch) in route tests;
  Event Service HTTP: Stub (respx) in adapter tests, so an unexpected call
  fails the test.

Not proven
----------
- That Event Service overlays the approved details while a re-check is pending
  (-> event-service unit tests for SCRUM-153).
- What the attendee's browser shows (-> frontend
  AttendeeRegistrationsPage.test.tsx).
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


def test_list_my_registrations_during_recheck_shows_approved_details(client, monkeypatch):
    """
    Summary: While a high-impact change awaits safety review, attendees still see the approved details.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (event in Pending Safety Check from the history lookup)
    """
    # Arrange (Given)
    pending = {**summary(), "preferredStartDate": "2030-03-01T09:00:00",
               "preferredEndDate": "2030-03-01T17:00:00", "description": "", "purpose": ""}
    lookup = history(pending)
    monkeypatch.setattr(routes, "get_confirmed_events", lambda: [])
    monkeypatch.setattr(routes, "get_historical_events", lookup)

    # Act (When)
    response = client.get(f"/registrations")

    # Assert (Then)
    assert response.status_code == 200
    [item] = response.json["registrations"]
    assert item["event"] == pending
    assert item["registration"]["status"] == "Confirmed"
    assert lookup.asked == [{EVENT}]


def test_history_adapter_uses_attendee_summaries_and_keeps_venue_name():
    """
    Summary: Event details for attendees come from Event Service's attendee-facing summaries, venue included.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (respx Event Service)
    """
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        route = router.get(f"{clients.EVENT_SERVICE_URL}/events/attendee-summaries").mock(
            return_value=Response(200, json={"events": [summary()]}))

        events = clients.get_historical_events([EVENT])

    assert dict(route.calls[0].request.url.params) == {"ids": EVENT}
    assert events == [{**summary(), "preferredStartDate": "2030-03-01T09:00:00",
                       "preferredEndDate": "2030-03-01T17:00:00", "description": "", "purpose": ""}]


def test_history_adapter_with_101_events_sends_two_batches():
    """
    Summary: Details for many events are fetched 100 at a time.
    AC4: (boundary: 101 event ids)
    Double: Stub (respx Event Service)
    """
    ids = [f"11111111-1111-4111-8111-{index:012d}" for index in range(101)]
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        route = router.get(f"{clients.EVENT_SERVICE_URL}/events/attendee-summaries").mock(
            return_value=Response(200, json={"events": []}))

        clients.get_historical_events(reversed(ids))

    assert [call.request.url.params["ids"].split(",") for call in route.calls] == [ids[:100], ids[100:]]


def test_list_my_registrations_after_approval_shows_new_details_from_catalogue(client, monkeypatch):
    """
    Summary: Once the new safety check is approved, attendees see the changed details from the Confirmed catalogue.
    SCRUM-150 AC4: Given the safety check I approve follows a high-impact
        change, when I approve it, then the changed details become visible to
        registered Attendees.
    Double: Stub (confirmed catalogue), Mock (history lookup not called)
    """
    # Arrange (Given)
    confirmed = dict(id=EVENT, eventName="Workshop", status="Confirmed",
                     preferredStartDate="2030-03-02T09:00:00", preferredEndDate="2030-03-02T18:00:00")

    def no_history(event_ids):
        raise AssertionError("history lookup must not run for a Confirmed event")
    monkeypatch.setattr(routes, "get_confirmed_events", lambda: [confirmed])
    monkeypatch.setattr(routes, "get_historical_events", no_history)

    # Act (When)
    response = client.get(f"/registrations")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["registrations"][0]["event"] == confirmed


def test_list_my_registrations_when_summaries_fail_returns_502(client, monkeypatch):
    """
    Summary: If the approved details cannot be looked up, the attendee gets an error, not changed details.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (history lookup raises)
    """
    # Arrange (Given)
    def broken(event_ids):
        raise RuntimeError("Event Service unavailable")
    monkeypatch.setattr(routes, "get_confirmed_events", lambda: [])
    monkeypatch.setattr(routes, "get_historical_events", broken)

    # Act (When)
    response = client.get(f"/registrations")

    # Assert (Then)
    assert response.status_code == 502
    assert response.json == {"message": "Unable to load your registrations right now."}
