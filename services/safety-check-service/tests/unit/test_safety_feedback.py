"""Safety revision AC1: assigned coordinators can read feedback and earlier rounds."""
from unittest.mock import patch

import pytest

from app import create_app, clients
from tests.unit.factories import COORDINATOR_ID, EVENT_ID, event, record, signed_in


@pytest.fixture
def client():
    return signed_in(create_app().test_client())


def feedback_url(event_id=EVENT_ID, coordinator_id=COORDINATOR_ID):
    return f"/safety-checks/feedback?eventId={event_id}&coordinatorId={coordinator_id}"


# Safety revision AC1/AC5 (API): return the decision, reason, flags and earlier rounds to the assigned coordinator.
# Record reads are mocked; this test verifies the response contract, not database history persistence.
def test_assigned_coordinator_sees_complete_feedback_and_earlier_rounds(client):
    rounds = [record(2, "Changes Requested", remarks="Emergency access blocked.", flags=[{
        "area": "venue arrangement", "changeRequired": "Keep the exit clear.",
        "bookingId": None, "equipmentRequestId": None,
    }]), record(1, "Changes Requested", remarks="Earlier feedback.")]
    with patch("app.clients.get_event", return_value=event("Safety Changes Requested")) as get_event, patch(
        "app.clients.list_safety_check_records", return_value=rounds
    ) as list_records:
        response = client.get(feedback_url())
    assert response.status_code == 200
    assert response.json == {"safetyChecks": rounds}
    get_event.assert_called_once_with(EVENT_ID)
    list_records.assert_called_once_with(EVENT_ID)


def test_no_review_rounds_returns_empty_feedback(client):
    with patch("app.clients.get_event", return_value=event()), patch(
        "app.clients.list_safety_check_records", return_value=[]
    ):
        response = client.get(feedback_url())
    assert response.json == {"safetyChecks": []}


@pytest.mark.parametrize("event_id,coordinator_id", [("bad", COORDINATOR_ID), ("", "")])
def test_feedback_rejects_invalid_identity(client, event_id, coordinator_id):
    with patch("app.clients.get_event") as get_event:
        assert client.get(feedback_url(event_id, coordinator_id)).status_code == 400
    get_event.assert_not_called()


@pytest.mark.parametrize("error,status", [
    (clients.EventNotAssignedError, 403), (clients.EventNotFoundError, 404),
    (clients.DownstreamTimeout, 504), (clients.DownstreamError, 502),
])
def test_feedback_does_not_read_records_if_event_access_fails(client, error, status):
    with patch("app.clients.get_event", side_effect=error), patch(
        "app.clients.list_safety_check_records"
    ) as list_records:
        assert client.get(feedback_url()).status_code == status
    list_records.assert_not_called()


@pytest.mark.parametrize("error,status", [(clients.DownstreamTimeout, 504), (clients.DownstreamError, 502)])
def test_feedback_explains_unavailable_records(client, error, status):
    with patch("app.clients.get_event", return_value=event()), patch(
        "app.clients.list_safety_check_records", side_effect=error
    ):
        response = client.get(feedback_url())
    assert response.status_code == status
    assert response.json["message"] == "Unable to load safety feedback right now."