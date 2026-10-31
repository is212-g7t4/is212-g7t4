"""
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
- An attendee's registration list once a re-checked event is approved again:
  the event's new details come from the confirmed events.
- We check the event details the attendee sees.

Doubled
-------
- Registration and User Services: hold the attendee's registration and profile
  [Stub].
- Event Service: lists the event as confirmed with its new details [Stub]; we
  check its previously approved details are not used [Mock].
- Sign-in: a test key signs the caller's token (tests/unit/conftest.py) [Stub].

Not proven
----------
- That Event Service only lists the event as confirmed after the approval (->
  event-service SCRUM-150 tests).
- AC1-AC3 approval state, history and invalid-state rejection are owned by
  Safety Check and Event Services; this composite owns only AC4's attendee view.
"""

import pytest

from app import create_app, routes
from tests.unit.factories import signed_in

ATTENDEE = "22222222-2222-4222-8222-222222222222"
EVENT = "11111111-1111-4111-8111-111111111111"
REGISTRATION = dict(
    registration_id="33333333-3333-4333-8333-333333333333",
    event_id=EVENT,
    attendee_id=ATTENDEE,
    status="Confirmed",
)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(routes, "get_attendee_registrations", lambda: [dict(REGISTRATION)])
    monkeypatch.setattr(routes, "get_user", lambda attendee: dict(username="Synthetic", email="user@example.com"))
    return signed_in(create_app({"TESTING": True}).test_client(), ATTENDEE, "Attendee")


def test_ac4_list_my_registrations_after_approval_shows_changed_details(client, monkeypatch):
    """
    Summary: Once the Safety Officer approves the safety check that followed a high-impact change, registered attendees see the changed details.
    AC4: Given the safety check I approve follows a high-impact change, when I
        approve it, then the changed details become visible to registered
        Attendees.
    Double: Event Service lists the event as confirmed again, with its new
        date [Stub]; we check the previously approved details are not looked
        up [Mock].
    """
    confirmed = dict(id=EVENT, eventName="Workshop", status="Confirmed",
                     preferredStartDate="2030-03-02T09:00:00", preferredEndDate="2030-03-02T18:00:00")

    def no_history(event_ids):
        raise AssertionError("the previously approved details must not be used once the event is Confirmed")

    monkeypatch.setattr(routes, "get_confirmed_events", lambda: [confirmed])
    monkeypatch.setattr(routes, "get_historical_events", no_history)

    response = client.get("/registrations")

    assert response.status_code == 200
    assert response.json["registrations"][0]["event"] == confirmed
