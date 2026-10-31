"""SCRUM-49: Event Change and Modification Notifications

User Story
----------
As an Event Organiser and Event Coordinator, I want to receive notifications about event changes that affect me, so that I can respond to changes promptly.

Acceptance Criteria
-------------------
AC1: Given an Event Organiser submits a change request, the system sends an in-app notification to the Event Coordinator with the event name, proposed changes, and a link to review the request.
AC2: Given an approval or rejection of a change request is successfully recorded, the Event Organiser receives an in-app notification with the event name, decision, and reason if rejected.
AC3: Given an event is cancelled or rejected, the system sends an in-app notification to both the Event Coordinator and Event Organiser confirming the cancellation or rejection, respectively, with the event name.

Real
----
- app.consumer.process(): JSON validation, the story's display-contract
  validator and the inbox/quarantine SQL, with the broker ACK only after the
  database commit.
- Assertions are on the SQL and parameters sent, and the ACK and its order.

Doubled
-------
- psycopg2.connect: Stub - fresh MagicMock connection and cursor per test; SQL
  inspected.
- Broker channel: Mock - asserts basic_ack after the commit.

Not proven
----------
- AC1: Incoming proposed changes/review destination and saved recipient inbox are checked.
- AC2: Incoming decision/reason content and malformed contract quarantine are checked.
- AC3: Cancellation/rejection envelopes for both role recipients are checked; selecting recipients and the business transition belong to producers.
- Real PostgreSQL evidence exists only in the maintained SCRUM-45/47/49/166 integration modules; neither their success nor parser acceptance proves all notification types or producer fan-out.
- Broker delivery, other service code and browser navigation are NOT COVERED ANYWHERE in this module.
- Pagination, read/unread controls, legacy rows, quarantine diagnostics, process wiring and future-type compatibility are useful supporting contracts without their own AC. They are preserved and flagged for a Product Owner decision, not relabelled as new acceptance criteria.
"""
import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.consumer import process
from tests.unit.factories import make_change_envelope, process_change_at_sql_boundary


# AC1 ---- submitted changes must contain a matching, usable review link

@pytest.mark.parametrize("optional_recipient", ["present", "absent"], ids=["explicit-recipient", "recipient-from-envelope"])
def test_process_change_request_alert_stores_for_coordinator_before_ack(optional_recipient):
    """Summary: A change-request notice is stored for the coordinator before acknowledging.
AC1: Given an Event Organiser submits a change request, the system sends an in-app notification to the Event Coordinator with the event name, proposed changes, and a link to review the request.
Double: Stub (connection), Mock (channel ACK)
"""
    # Arrange (Given)
    envelope = make_change_envelope()

    # Act (When)
    if optional_recipient == "absent":
        del envelope["details"]["recipientId"]

    # Assert (Then)
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
def test_process_change_request_alert_missing_content_is_quarantined(field_path, invalid_value, rejection_reason):
    """Summary: A change-request notice missing its event name, changes or review link is kept aside.
AC1: Given an Event Organiser submits a change request, the system sends an in-app notification to the Event Coordinator with the event name, proposed changes, and a link to review the request.
Double: Stub (connection), Mock (channel ACK)
"""
    # Arrange (Given)
    envelope = make_change_envelope("submitted")
    target = envelope
    for key in field_path[:-1]:
        target = target[key]

    # Act (When)
    if invalid_value == "OMIT":
        del target[field_path[-1]]
    else:
        target[field_path[-1]] = invalid_value

    # Assert (Then)
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
def test_process_change_decision_alert_stores_for_organiser_before_ack(kind, optional_fields):
    """Summary: An approval or rejection of a change request is stored for the organiser before acknowledging.
AC2: Given an approval or rejection of a change request is successfully recorded, the Event Organiser receives an in-app notification with the event name, decision, and reason if rejected.
Double: Stub (connection), Mock (channel ACK)
"""
    # Arrange (Given)
    envelope = make_change_envelope(kind)

    # Act (When)
    if optional_fields == "absent":
        envelope["details"].pop("previousEventName", None)
        del envelope["details"]["recipientId"]
        if kind == "approved":
            envelope["message"] = "Change request for Workshop was approved."

    # Assert (Then)
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
def test_process_change_approval_alert_missing_content_is_quarantined(field_path, invalid_value, rejection_reason):
    """Summary: A change approval notice with missing or malformed content is kept aside.
AC2: Given an approval or rejection of a change request is successfully recorded, the Event Organiser receives an in-app notification with the event name, decision, and reason if rejected.
Double: Stub (connection), Mock (channel ACK)
"""
    # Arrange (Given)
    envelope = make_change_envelope("approved")
    target = envelope
    for key in field_path[:-1]:
        target = target[key]

    # Act (When)
    if invalid_value == "OMIT":
        del target[field_path[-1]]
    else:
        target[field_path[-1]] = invalid_value

    # Assert (Then)
    assert process_change_at_sql_boundary(
        envelope, quarantined=True, error=rejection_reason
    ) == ["quarantined", "acknowledged"]


@pytest.mark.parametrize("field_path, invalid_value, rejection_reason", [
    pytest.param(('details', 'decision'), 'Approved', 'Invalid change request decision', id='decision-mismatch'),
    pytest.param(('details', 'reason'), 42, 'Missing change rejection reason', id='reason-not-text'),
    pytest.param(('details', 'reason'), ' \n', 'Missing change rejection reason', id='reason-blank'),
    pytest.param(('details', 'reason'), None, 'Missing change rejection reason', id='reason-null'),
])
def test_process_change_rejection_alert_with_wrong_decision_is_quarantined(field_path, invalid_value, rejection_reason):
    """Summary: A change rejection notice with a mismatched decision or bad content is kept aside.
AC2: Given an approval or rejection of a change request is successfully recorded, the Event Organiser receives an in-app notification with the event name, decision, and reason if rejected.
Double: Stub (connection), Mock (channel ACK)
"""
    # Arrange (Given)
    envelope = make_change_envelope("rejected")
    target = envelope
    for key in field_path[:-1]:
        target = target[key]

    # Act (When)
    if invalid_value == "OMIT":
        del target[field_path[-1]]
    else:
        target[field_path[-1]] = invalid_value

    # Assert (Then)
    assert process_change_at_sql_boundary(
        envelope, quarantined=True, error=rejection_reason
    ) == ["quarantined", "acknowledged"]


# AC2 ---- rejection must retain its reason

def test_process_change_rejection_alert_without_reason_is_quarantined(mocker):
    """Summary: A change rejection notice must carry the reason.
AC2: Given an approval or rejection of a change request is successfully recorded, the Event Organiser receives an in-app notification with the event name, decision, and reason if rejected.
Double: Stub (connection), Mock (channel ACK)
"""
    # Arrange (Given)
    # Arrange
    identifier = "10000000-0000-4000-8000-000000000001"
    envelope = dict(version=1, id=identifier, type="event.change-request-rejected", recipientId=identifier,
        createdAt="2026-10-28T01:00:00+00:00", message="Workshop was rejected",
        details=dict(eventId=identifier,eventName="Workshop",changeRequestId=identifier,decision="Rejected"),
        destination=dict(kind="event-details",eventId=identifier))
    connection, channel = MagicMock(), Mock()
    cursor = connection.cursor.return_value.__enter__.return_value
    # Act
    mocker.patch("psycopg2.connect", return_value=connection)
    process("unused", channel, Mock(delivery_tag=7), json.dumps(envelope).encode())
    # Assert
    inserts = [call.args[0] for call in cursor.execute.call_args_list]

    # Act + Assert (When / Then)
    assert any('INSERT INTO public."NotificationFailure"' in sql for sql in inserts)
    assert not any('INSERT INTO public."Notification" ' in sql for sql in inserts)
    channel.basic_ack.assert_called_once_with(delivery_tag=7)


# AC3 ---- cancellation uses the same safe event/recipient contract, without a decision

@pytest.mark.parametrize("recipient", [
    pytest.param("10000000-0000-4000-8000-000000000001", id="organiser"),
    pytest.param("10000000-0000-4000-8000-000000000002", id="coordinator"),
])
def test_process_cancellation_alert_stores_for_organiser_and_coordinator(recipient):
    """Summary: A cancellation notice is stored for both the organiser and the coordinator.
AC3: Given an event is cancelled or rejected, the system sends an in-app notification to both the Event Coordinator and Event Organiser confirming the cancellation or rejection, respectively, with the event name.
Double: Stub (connection), Mock (channel ACK)
"""
    # Arrange (Given)
    envelope = make_change_envelope("cancelled", recipientId=recipient)
    envelope["recipientId"] = recipient

    # Act + Assert (When / Then)
    assert process_change_at_sql_boundary(envelope) == ["stored", "acknowledged"]


def test_process_cancellation_alert_without_optional_detail_still_stores():
    """Summary: A cancellation notice without its optional recipient detail is still delivered.
AC3: Given an event is cancelled or rejected, the system sends an in-app notification to both the Event Coordinator and Event Organiser confirming the cancellation or rejection, respectively, with the event name.
Double: Stub (connection), Mock (channel ACK)
"""
    # Arrange (Given)
    envelope = make_change_envelope("cancelled")

    # Act (When)
    del envelope["details"]["recipientId"]

    # Assert (Then)
    assert process_change_at_sql_boundary(envelope) == ["stored", "acknowledged"]
