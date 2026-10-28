"""SCRUM-49 Event Change and Modification Notifications: Notification unit tests.

Story: As an Event Organiser and Event Coordinator, I want to receive notifications about event changes that affect me, so that I can respond to changes promptly.
Real: consumer parsing, validation, process and store SQL construction.
Doubled: PostgreSQL connection/cursor and broker ACK; no DB or broker runs here.
Not proven: cross-service E2E, live broker delivery, authentication or browser navigation.
AC = acceptance criterion; DR = supporting design rule, not an extra AC.

AC1 Given an Event Organiser submits a change request, the system sends an in-app notification to the Event Coordinator with the event name, proposed changes, and a link to review the request.
AC2 Given an approval or rejection of a change request is successfully recorded, the Event Organiser receives an in-app notification with the event name, decision, and reason if rejected.
AC3 Given an event is cancelled or rejected, the system sends an in-app notification to both the Event Coordinator and Event Organiser confirming the cancellation or rejection respectively with the event name.
Coverage: AC1-3 valid and malformed consumer write contracts; actual persistence belongs to integration tests, mutation/preparation to Event/Workflow.
"""
import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.consumer import process
from tests.unit.factories import make_change_envelope, process_change_at_sql_boundary


# AC1 ---- submitted changes must contain a matching, usable review link

@pytest.mark.parametrize("optional_recipient", ["present", "absent"], ids=["explicit-recipient", "recipient-from-envelope"])
def test_ac1_valid_submission_is_stored_before_ack(optional_recipient):
    """Normal: proposed edits and exact review destination are stored before the broker ACK."""
    envelope = make_change_envelope()
    if optional_recipient == "absent":
        del envelope["details"]["recipientId"]
    assert process_change_at_sql_boundary(envelope) == ["stored", "acknowledged"]


@pytest.mark.parametrize("field_path, invalid_value, rejection_reason", [
    pytest.param(('details',), [], 'Missing event change display content', id='details-not-object'),
    pytest.param(('details', 'eventName'), 42, 'Missing event change display content', id='event-name-not-text'),
    pytest.param(('details', 'eventName'), '  ', 'Missing event change display content', id='event-name-blank'),
    pytest.param(('details', 'eventName'), 'OMIT', 'Missing event change display content', id='event-name-missing'),
    pytest.param(('details', 'eventId'), 'bad', None, id='event-id-invalid'),
    pytest.param(('details', 'changeRequestId'), 'bad', None, id='request-id-invalid'),
    pytest.param(('details', 'eventId'), 'OMIT', None, id='event-id-missing'),
    pytest.param(('details', 'changeRequestId'), 'OMIT', None, id='request-id-missing'),
    pytest.param(('destination',), {'kind': 'event-details', 'eventId': '30000000-0000-4000-8000-000000000001'}, 'Change submission requires matching review destination', id='wrong-destination-kind'),
    pytest.param(('destination', 'eventId'), '30000000-0000-4000-8000-000000000002', 'Change submission requires matching review destination', id='wrong-destination-event'),
    pytest.param(('destination', 'changeRequestId'), '40000000-0000-4000-8000-000000000002', 'Change submission requires matching review destination', id='wrong-destination-request'),
    pytest.param(('details', 'proposedChanges'), [], 'Missing or invalid proposed changes', id='changes-not-object'),
    pytest.param(('details', 'proposedChanges'), {}, 'Missing or invalid proposed changes', id='changes-empty'),
    pytest.param(('details', 'proposedChanges'), {'unknown': 'value'}, 'Missing or invalid proposed changes', id='changes-unknown-field'),
    pytest.param(('details', 'proposedChanges'), {'expectedAttendance': 40}, 'Missing or invalid proposed changes', id='changes-nontext-value'),
    pytest.param(('details', 'proposedChanges'), {'description': None}, 'Missing or invalid proposed changes', id='changes-null-value'),
    pytest.param(('details', 'proposedChanges'), 'OMIT', None, id='changes-missing'),
    pytest.param(('details', 'recipientId'), '10000000-0000-4000-8000-000000000002', 'Inconsistent change recipient', id='recipient-mismatch'),
])
def test_ac1_submitted_malformed_content_is_quarantined_before_ack(field_path, invalid_value, rejection_reason):
    """Failure: malformed submitted content is quarantined, never delivered, before ACK."""
    envelope = make_change_envelope("submitted")
    target = envelope
    for key in field_path[:-1]:
        target = target[key]
    if invalid_value == "OMIT":
        del target[field_path[-1]]
    else:
        target[field_path[-1]] = invalid_value
    assert process_change_at_sql_boundary(
        envelope, quarantined=True, error=rejection_reason
    ) == ["quarantined", "acknowledged"]


# AC2 ---- decisions preserve identity, decision, former name and rejection reason

@pytest.mark.parametrize("kind, optional_fields", [
    pytest.param("approved", "present", id="approved-with-former-name"),
    pytest.param("approved", "absent", id="approved-without-optional-fields"),
    pytest.param("rejected", "present", id="rejected-with-unicode-reason"),
    pytest.param("rejected", "absent", id="rejected-without-optional-fields"),
])
def test_ac2_valid_decision_is_stored_before_ack(kind, optional_fields):
    """Normal: either decision retains exact content and recipient through storage before ACK."""
    envelope = make_change_envelope(kind)
    if optional_fields == "absent":
        envelope["details"].pop("previousEventName", None)
        del envelope["details"]["recipientId"]
        if kind == "approved":
            envelope["message"] = "Change request for Workshop was approved."
    assert process_change_at_sql_boundary(envelope) == ["stored", "acknowledged"]


@pytest.mark.parametrize("field_path, invalid_value, rejection_reason", [
    pytest.param(('details',), None, 'Missing event change display content', id='details-not-object'),
    pytest.param(('details', 'eventName'), 42, 'Missing event change display content', id='event-name-not-text'),
    pytest.param(('details', 'eventName'), '  ', 'Missing event change display content', id='event-name-blank'),
    pytest.param(('details', 'eventId'), 'bad', None, id='event-id-invalid'),
    pytest.param(('details', 'changeRequestId'), 'bad', None, id='request-id-invalid'),
    pytest.param(('details', 'changeRequestId'), 'OMIT', None, id='request-id-missing'),
    pytest.param(('destination', 'eventId'), '30000000-0000-4000-8000-000000000002', 'Event change requires matching event details', id='wrong-destination'),
    pytest.param(('details', 'recipientId'), '10000000-0000-4000-8000-000000000002', 'Inconsistent change recipient', id='recipient-mismatch'),
    pytest.param(('details', 'decision'), 'Rejected', 'Invalid change request decision', id='decision-mismatch'),
    pytest.param(('details', 'decision'), 'OMIT', 'Invalid change request decision', id='decision-missing'),
    pytest.param(('details', 'previousEventName'), 42, 'Invalid previous event name', id='previous-name-not-text'),
    pytest.param(('details', 'previousEventName'), ' ', 'Invalid previous event name', id='previous-name-blank'),
])
def test_ac2_approved_malformed_content_is_quarantined_before_ack(field_path, invalid_value, rejection_reason):
    """Failure: malformed approved content is quarantined, never delivered, before ACK."""
    envelope = make_change_envelope("approved")
    target = envelope
    for key in field_path[:-1]:
        target = target[key]
    if invalid_value == "OMIT":
        del target[field_path[-1]]
    else:
        target[field_path[-1]] = invalid_value
    assert process_change_at_sql_boundary(
        envelope, quarantined=True, error=rejection_reason
    ) == ["quarantined", "acknowledged"]


@pytest.mark.parametrize("field_path, invalid_value, rejection_reason", [
    pytest.param(('details', 'decision'), 'Approved', 'Invalid change request decision', id='decision-mismatch'),
    pytest.param(('details', 'reason'), 42, 'Missing change rejection reason', id='reason-not-text'),
    pytest.param(('details', 'reason'), ' \n', 'Missing change rejection reason', id='reason-blank'),
    pytest.param(('details', 'reason'), None, 'Missing change rejection reason', id='reason-null'),
])
def test_ac2_rejected_malformed_content_is_quarantined_before_ack(field_path, invalid_value, rejection_reason):
    """Failure: malformed rejected content is quarantined, never delivered, before ACK."""
    envelope = make_change_envelope("rejected")
    target = envelope
    for key in field_path[:-1]:
        target = target[key]
    if invalid_value == "OMIT":
        del target[field_path[-1]]
    else:
        target[field_path[-1]] = invalid_value
    assert process_change_at_sql_boundary(
        envelope, quarantined=True, error=rejection_reason
    ) == ["quarantined", "acknowledged"]


# AC2 ---- rejection must retain its reason

def test_ac2_rejection_without_recorded_reason_is_quarantined_not_delivered():
    """Failure: missing rejection reason cannot silently become an incomplete inbox notification."""
    # Arrange
    identifier = "10000000-0000-4000-8000-000000000001"
    envelope = dict(version=1, id=identifier, type="event.change-request-rejected", recipientId=identifier,
        createdAt="2026-10-28T01:00:00+00:00", message="Workshop was rejected",
        details=dict(eventId=identifier,eventName="Workshop",changeRequestId=identifier,decision="Rejected"),
        destination=dict(kind="event-details",eventId=identifier))
    connection, channel = MagicMock(), Mock()
    cursor = connection.cursor.return_value.__enter__.return_value
    # Act
    with patch("psycopg2.connect", return_value=connection):
        process("unused", channel, Mock(delivery_tag=7), json.dumps(envelope).encode())
    # Assert
    inserts = [call.args[0] for call in cursor.execute.call_args_list]
    assert any('INSERT INTO public."NotificationFailure"' in sql for sql in inserts)
    assert not any('INSERT INTO public."Notification" ' in sql for sql in inserts)
    channel.basic_ack.assert_called_once_with(delivery_tag=7)


# AC3 ---- cancellation uses the same safe event/recipient contract, without a decision

@pytest.mark.parametrize("recipient", [
    pytest.param("10000000-0000-4000-8000-000000000001", id="organiser"),
    pytest.param("10000000-0000-4000-8000-000000000002", id="coordinator"),
])
def test_ac3_cancellation_is_stored_for_each_recipient_before_ack(recipient):
    """Normal: each cancellation recipient's independent envelope is stored before ACK."""
    envelope = make_change_envelope("cancelled", recipientId=recipient)
    envelope["recipientId"] = recipient
    assert process_change_at_sql_boundary(envelope) == ["stored", "acknowledged"]


def test_ac3_cancellation_without_optional_recipient_detail_is_stored_before_ack():
    """Boundary: envelope recipient suffices for cancellation without decision/request fields."""
    envelope = make_change_envelope("cancelled")
    del envelope["details"]["recipientId"]
    assert process_change_at_sql_boundary(envelope) == ["stored", "acknowledged"]
