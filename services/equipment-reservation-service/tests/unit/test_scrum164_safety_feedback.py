"""
SCRUM-164: Revise Arrangements and Resubmit for Safety Check

User Story
----------
As an Event Coordinator, I want to see the Safety Officer's feedback and revise
the affected arrangements, so that I can resubmit the event for a safety check
without redoing unaffected planning.

Acceptance Criteria
-------------------
AC1: Given my event is 'Safety Changes Requested', when I open it, then I see
     the decision, reason, requested changes and affected areas.
AC2: Given the venue arrangement is flagged, then the affected venue booking
     must be reviewed again by Venue Staff (revised booking or replacement
     request) before the event can be resubmitted.
AC3: Given the technical arrangement is flagged, then the affected equipment
     request must be reviewed again by Technical Support Staff before the event
     can be resubmitted.
AC4: Given an arrangement was not flagged, then it stays confirmed and does not
     need to be reviewed again.
AC5: Given all flagged arrangements are confirmed again, when I resubmit, then
     the status returns to 'Pending Safety Check' as a new review round, and
     earlier rounds remain in the history.

Real
----
- The Equipment Reservation routes and app.clients run for real against a fake
  world; the two-stage availability rules in app.availability run for real.
- Assertions are on the status, the response body and which downstream calls
  the composite makes.

Doubled
-------
- Event, Equipment and Equipment Request Services: Fake (tests/unit/fakes.py
  `World`, wired in by the `world` fixture) - in-memory events, assignments,
  catalogue and request lines; world.calls records which calls were made.
- httpx.request (client tests): Stub (`sent` fixture) - canned FakeResponse;
  the recorded method, URL and headers are inspected.
- Safety Check Record Service: Fake (world.safety_rounds) - review rounds with
  their flags.

Not proven
----------
- That the coordinator's equipment page shows the feedback (AC1, UI half) (->
  frontend SafetyFeedbackPanel.test.tsx).
- That Safety Check Record Service returns rounds newest last with their flags
  (-> safety-check-record-service unit tests).
"""

import pytest

from app import clients, create_app
from app.availability import RESERVING_EVENT_STATUSES, effective_available_stock, evaluate_request
from app.clients import DownstreamError
from tests.unit.factories import COORDINATOR, CREATE_URL, LEAD, TS, bearer, new_item, rows
from tests.unit.fakes import END, LAPTOP, MIC, OTHER, START, TABLE, TARGET, THIRD, USER, FakeResponse, equipment, line

HEADERS = {"Authorization": "Bearer user-token", "Cookie": "must-not-be-forwarded"}
MIC_STOCK = {"id": "e1", "status": "Available", "totalQuantity": 10}


def test_review_list_when_changes_requested_shows_latest_feedback_per_request(world, client):
    """
    Summary: Each flagged equipment request shows the latest round's reason and requested change.
    AC1: Given my event is 'Safety Changes Requested', when I open it, then I
        see the decision, reason, requested changes and affected areas.
    AC3: Given the technical arrangement is flagged, then the affected
        equipment request must be reviewed again by Technical Support Staff
        before the event can be resubmitted.
    Double: Fake (world: two rounds with item-level flags)
    """
    # Arrange (Given)
    world.events[TARGET]["status"] = "Safety Changes Requested"
    world.requests = [line("r1", TARGET, MIC, 1), line("r2", TARGET, TABLE, 2, "Approved")]
    world.safety_rounds = [
        {"roundNumber": 1, "status": "Changes Requested", "remarks": "Old reason.", "flags": [
            {"area": "technical arrangement", "equipmentRequestId": "r2", "changeRequired": "Old change."}]},
        {"roundNumber": 2, "status": "Changes Requested", "remarks": "Trip hazard.", "flags": [
            {"area": "technical arrangement", "equipmentRequestId": "r1", "changeRequired": "Move microphone cables."},
            {"area": "venue arrangement", "changeRequired": "Change room."}]},
    ]

    # Act (When)
    requests = rows(client)[0]["requests"]

    # Assert (Then)
    assert requests[0]["safetyFeedback"] == {"reason": "Trip hazard.", "requestedChanges": ["Move microphone cables."]}
    assert requests[1]["safetyFeedback"] is None
    assert world.calls.count(("safety_checks", TARGET)) == 1


def test_review_list_when_technical_area_flagged_shows_feedback_on_every_request(world, client):
    """
    Summary: A flag on the whole technical area shows on every equipment request of the event.
    AC3: Given the technical arrangement is flagged, then the affected
        equipment request must be reviewed again by Technical Support Staff
        before the event can be resubmitted.
    Double: Fake (world: one area-wide technical flag)
    """
    # Arrange (Given)
    world.events[TARGET]["status"] = "Safety Changes Requested"
    world.requests = [line("r1", TARGET, MIC, 1), line("r2", TARGET, TABLE, 2)]

    world.safety_rounds = [{"roundNumber": 1, "status": "Changes Requested", "remarks": None, "flags": [
        {"area": "technical arrangement", "equipmentRequestId": None, "changeRequired": "Keep exits clear."}]}]

    # Act + Assert (When / Then)
    assert all(request["safetyFeedback"] == {"reason": None, "requestedChanges": ["Keep exits clear."]}
        for request in rows(client)[0]["requests"])


@pytest.mark.parametrize("rounds", [[], [{"roundNumber": 1, "status": "Pending", "flags": []}]], ids=["no_rounds", "pending_round"])
def test_review_list_when_no_decided_round_shows_no_feedback(world, client, rounds):
    """
    Summary: Without a decided round there is no safety feedback to show.
    AC1: Given my event is 'Safety Changes Requested', when I open it, then I
        see the decision, reason, requested changes and affected areas.
    Double: Fake (world: no rounds / a Pending round)
    """
    # Arrange (Given)
    world.events[TARGET]["status"] = "Safety Changes Requested"
    world.requests = [line("r1", TARGET, MIC, 1)]

    world.safety_rounds = rounds

    # Act + Assert (When / Then)
    assert rows(client)[0]["requests"][0]["safetyFeedback"] is None


def test_review_list_when_event_not_in_revision_fetches_no_safety_records(world, client):
    """
    Summary: Safety records are only read for events with Safety Changes Requested.
    AC4: Given an arrangement was not flagged, then it stays confirmed and does
        not need to be reviewed again.
    Double: Fake (world.calls inspected)
    """
    # Arrange (Given): world, client, from fixtures

    # Act (When)
    world.requests = [line("r1", TARGET, MIC, 1)]

    # Assert (Then)
    assert rows(client)[0]["requests"][0]["safetyFeedback"] is None
    assert not any(call[0] == "safety_checks" for call in world.calls)


def test_review_list_when_safety_records_unavailable_reports_error(world, client, monkeypatch):
    """
    Summary: If safety records cannot be read, that is reported instead of showing the lines as unflagged.
    AC3: Given the technical arrangement is flagged, then the affected
        equipment request must be reviewed again by Technical Support Staff
        before the event can be resubmitted.
    Double: Fake (world), Stub (get_event_safety_checks raises DownstreamError)
    """
    # Arrange (Given)
    world.events[TARGET]["status"] = "Safety Changes Requested"
    world.requests = [line("r1", TARGET, MIC, 1)]
    def unavailable(event_id):
        raise DownstreamError(503, "Safety feedback is unavailable.")
    monkeypatch.setattr("app.clients.get_event_safety_checks", unavailable)

    # Act (When)
    response = client.get("/equipment-reservations", headers=TS)

    # Assert (Then)
    assert response.status_code == 503
    assert response.json["message"] == "Safety feedback is unavailable."


def test_safety_checks_client_reads_only_the_requested_event(sent, monkeypatch):
    """
    Summary: Safety rounds are read for the one event asked about.
    AC1: Given my event is 'Safety Changes Requested', when I open it, then I
        see the decision, reason, requested changes and affected areas.
    Double: Stub (httpx.request returns rounds)
    """
    calls, fake = sent
    monkeypatch.setenv("SAFETY_CHECK_RECORD_SERVICE_URL", "http://records:5000")
    fake.response = FakeResponse(body={"safetyChecks": [{"roundNumber": 2}]})
    assert clients.get_event_safety_checks("event-id") == [{"roundNumber": 2}]
    assert calls[0] == ("GET", "http://records:5000/safety-check-records", {"timeout": 10, "params": {"eventId": "event-id"}, "headers": {}})
