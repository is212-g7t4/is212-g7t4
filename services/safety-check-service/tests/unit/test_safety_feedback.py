"""SCRUM-164: Revise Arrangements and Resubmit for Safety Check

Agreed revision from this conversation; pending confirmation that Jira has been updated

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
AC3: Given the technical arrangement is flagged, then the affected equipment requests that were previously 'Approved' return to 'Pending' and must be approved again by Technical Support Staff before the event can be resubmitted. The safety-change action does not reopen existing 'Rejected' requests or clear their rejection reasons, and requests already 'Pending' remain 'Pending'.
AC4: Given an arrangement was not flagged, then it stays confirmed and does not
     need to be reviewed again.
AC5: Given all flagged arrangements are confirmed again, when I resubmit, then
     the status returns to 'Pending Safety Check' as a new review round, and
     earlier rounds remain in the history.

Real
----
- GET /safety-checks/feedback: the assigned-coordinator check and the rounds
  with their decisions, reasons and flags.
- Assertions are on the feedback returned and the status.

Doubled
-------
- Event, Safety Check Record, Venue Availability, Venue, Equipment Request,
  Equipment and User Services: Stub (monkeypatched app.clients functions) -
  canned answers or raised client errors; calls recorded so tests assert the
  order and what was (or was not) called.

Not proven
----------
- That the atomic services behave as stubbed, and that a compensation really
  restores state in the database (-> each atomic service's unit and integration
  tests, and tests/integration/ here with respx).
"""
from unittest.mock import patch

import pytest

from app import create_app, clients
from tests.unit.factories import COORDINATOR_ID, EVENT_ID, event, record, signed_in


@pytest.fixture
def client():
    return signed_in(create_app().test_client())


def feedback_url(event_id=EVENT_ID, coordinator_id=COORDINATOR_ID):
    return f"/safety-checks/feedback?eventId={event_id}&coordinatorId={coordinator_id}"


def test_feedback_for_assigned_coordinator_shows_all_rounds(client, mocker):
    """
    Summary: The assigned coordinator sees the decision, reason, changes and areas, and earlier rounds.
    AC1: Given my event is 'Safety Changes Requested', when I open it, then I
        see the decision, reason, requested changes and affected areas.
    Double: Stub (event and rounds)
    """
    # Arrange (Given)
    rounds = [record(2, "Changes Requested", remarks="Emergency access blocked.", flags=[{
        "area": "venue arrangement", "changeRequired": "Keep the exit clear.",
        "bookingId": None, "equipmentRequestId": None,
    }]), record(1, "Changes Requested", remarks="Earlier feedback.")]

    # Act (When)
    get_event = mocker.patch("app.clients.get_event", return_value=event("Safety Changes Requested"))
    list_records = mocker.patch(
        "app.clients.list_safety_check_records", return_value=rounds
    )
    response = client.get(feedback_url())

    # Assert (Then)
    assert response.status_code == 200
    assert response.json == {"safetyChecks": rounds}
    get_event.assert_called_once_with(EVENT_ID)
    list_records.assert_called_once_with(EVENT_ID)


def test_feedback_without_rounds_returns_empty(client, mocker):
    """
    Summary: With no review rounds, the feedback is empty.
    AC1: Given my event is 'Safety Changes Requested', when I open it, then I
        see the decision, reason, requested changes and affected areas.
    Double: Stub (event and rounds)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    mocker.patch("app.clients.get_event", return_value=event())
    mocker.patch(
        "app.clients.list_safety_check_records", return_value=[]
    )
    response = client.get(feedback_url())

    # Assert (Then)
    assert response.json == {"safetyChecks": []}


@pytest.mark.parametrize("event_id,coordinator_id", [("bad", COORDINATOR_ID), ("", "")], ids=["bad_event_id", "empty_ids"])
def test_feedback_with_bad_ids_returns_400(client, event_id, coordinator_id, mocker):
    """
    Summary: Feedback needs valid event and coordinator ids.
    AC1: Given my event is 'Safety Changes Requested', when I open it, then I
        see the decision, reason, requested changes and affected areas.
    Double: None
    """
    # Arrange (Given): client, event_id, coordinator_id, from fixtures

    # Act (When)
    get_event = mocker.patch("app.clients.get_event")
    assert client.get(feedback_url(event_id, coordinator_id)).status_code == 400

    # Assert (Then)
    get_event.assert_not_called()


@pytest.mark.parametrize("error,status", [
    (clients.EventNotAssignedError, 403), (clients.EventNotFoundError, 404),
    (clients.DownstreamTimeout, 504), (clients.DownstreamError, 502),
])
def test_feedback_when_event_access_fails_reads_no_records(client, error, status, mocker):
    """
    Summary: If the coordinator cannot access the event, no rounds are read.
    AC1: Given my event is 'Safety Changes Requested', when I open it, then I
        see the decision, reason, requested changes and affected areas.
    Double: Stub (event and rounds)
    """
    # Arrange (Given): client, error, status, from fixtures

    # Act (When)
    mocker.patch("app.clients.get_event", side_effect=error)
    list_records = mocker.patch(
        "app.clients.list_safety_check_records"
    )
    assert client.get(feedback_url()).status_code == status

    # Assert (Then)
    list_records.assert_not_called()


@pytest.mark.parametrize("error,status", [(clients.DownstreamTimeout, 504), (clients.DownstreamError, 502)])
def test_feedback_when_records_unavailable_says_so(client, error, status, mocker):
    """
    Summary: If rounds cannot be read, the coordinator is told rather than shown none.
    AC1: Given my event is 'Safety Changes Requested', when I open it, then I
        see the decision, reason, requested changes and affected areas.
    Double: Stub (event and rounds)
    """
    # Arrange (Given): client, error, status, from fixtures

    # Act (When)
    mocker.patch("app.clients.get_event", return_value=event())
    mocker.patch(
        "app.clients.list_safety_check_records", side_effect=error
    )
    response = client.get(feedback_url())

    # Assert (Then)
    assert response.status_code == status
    assert response.json["message"] == "Unable to load safety feedback right now."