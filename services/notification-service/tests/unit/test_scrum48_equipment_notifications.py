"""SCRUM-48: Equipment Request Notification and Decision Alerts

User Story
----------
As an Event Coordinator and Technical Support Staff, I want to receive notifications about equipment requests and decisions, so that I can coordinate equipment arrangements efficiently.

Acceptance Criteria
-------------------
AC1: Given an Event Coordinator submits an equipment request, the system sends an in-app notification to Technical Support Staff with the event name, requested equipment list, and a link to review the request.
AC2: Given Technical Support Staff approves or rejects an Equipment Request, the system sends an in-app notification to the Event Coordinator assigned to that event with the event name, the equipment covered by the decision, and the decision status (Approved or Rejected).
AC3: Given a Technical Support Staff rejects the equipment request, the system sends an in-app notification to the Event Coordinator with the rejection message, event name, equipment request and link to the equipment request.

Real
----
- app.consumer.process(): JSON validation, the equipment envelope validators
  and the inbox/quarantine SQL, with the broker ACK only after storage.
- Assertions are on the SQL sent, the ACK and its order.

Doubled
-------
- psycopg2.connect: Stub (`storage` fixture) - fresh MagicMock connection and
  cursor; SQL inspected.
- Broker channel: Mock - asserts basic_ack after the commit.

Not proven
----------
- AC3 "rejection message" means a statement that the Equipment Request was rejected, not that the whole event was rejected and not the private rejectionReason/why. Existing reason-exclusion assertions are intentional; the private reason remains in the review workflow.
- Incoming SQL/ACK order and envelope validation use database/broker doubles, not committed equipment inbox rows or real broker delivery. Equipment producer/outbox semantics and browser navigation are outside this module.
- Both cases: AC1 relates only to outcome=submission; AC2 to Approved/Rejected; AC3 only to outcome=Rejected, never Approved or submission. Storage preserves a synthetic generic update message: it does not assert the producer-generated request-rejected statement. Malformed-case mapping denotes defensive validation support, not successful delivery.
- Reason exclusion is intentional; the rejection reason is private. Equipment-specific PostgreSQL delivery remains untested here. Maintained SCRUM-45/47/49/166 database suites do not prove equipment-specific delivery or producer fan-out.
- Quarantine diagnostics and exact SQL/ACK/failure contracts are supporting reliability rules without their own explicit Jira AC; Product Owner ownership/acceptance remains pending.
"""
from copy import deepcopy
import json
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest

from app.consumer import process

EVENT = "10000000-0000-0000-0000-000000000001"
REQUEST = "10000000-0000-0000-0000-000000000002"
EQUIPMENT = "10000000-0000-0000-0000-000000000003"
SOURCE = "10000000-0000-0000-0000-000000000004"
OTHER_REQUEST = "10000000-0000-0000-0000-000000000005"
OTHER_EQUIPMENT = "10000000-0000-0000-0000-000000000006"
STAFF = "20000000-0000-0000-0000-000000000001"
COORDINATOR = "30000000-0000-0000-0000-000000000001"
OTHER = "30000000-0000-0000-0000-000000000002"
CREATED = "2026-10-28T00:00:00+00:00"


def equipment_envelope(outcome) -> dict[str, Any]:
    """Fresh synthetic submission or per-request decision; never shared mutable data."""
    submission = outcome == "submission"
    recipient = STAFF if submission else COORDINATOR
    items = [dict(requestId=REQUEST, equipmentId=EQUIPMENT,
                  equipmentName="Microphone", quantityRequested=5)]
    if submission:
        items.append(dict(requestId=OTHER_REQUEST, equipmentId=OTHER_EQUIPMENT,
                          equipmentName="Projector", quantityRequested=2))
    details = dict(eventId=EVENT, eventName="Community Fair", recipientId=recipient,
                   items=items)
    if not submission:
        details["decision"] = outcome
    return dict(version=1, id=SOURCE, recipientId=recipient,
                type="equipment.request-submission" if submission else "equipment.request-decision",
                message="Community Fair equipment request update", createdAt=CREATED,
                destination=dict(kind="equipment-requests", eventId=EVENT,
                                 requestIds=[item["requestId"] for item in items]),
                details=details)


@pytest.fixture
def storage(monkeypatch):
    """Real store adapter, fresh transaction/channel doubles, no native DB call."""
    connection, channel = MagicMock(), Mock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("psycopg2.connect", lambda *args, **kwargs: connection)
    order = []
    cursor.execute.side_effect = lambda sql, params: order.append(
        "quarantine" if '"NotificationFailure"' in sql else "inbox")
    connection.__exit__.side_effect = lambda *args: order.append("transaction-exit")
    channel.basic_ack.side_effect = lambda **kwargs: order.append("ack")
    return connection, cursor, channel, order


@pytest.mark.parametrize("outcome,recipient,kind,request_ids", [
    pytest.param("submission", STAFF, "equipment.request-submission", [REQUEST, OTHER_REQUEST], id="AC1-tss-submission"),
    pytest.param("Approved", COORDINATOR, "equipment.request-decision", [REQUEST], id="AC2-coordinator-approval"),
    pytest.param("Rejected", COORDINATOR, "equipment.request-decision", [REQUEST], id="AC2-coordinator-rejection"),
])
def test_process_equipment_alert_stores_in_inbox_before_ack(
    storage, outcome, recipient, kind, request_ids,
):
    """Summary: Equipment submission and decision alerts are stored in the right inbox before the message is acknowledged.
    AC1: Given an Event Coordinator submits an equipment request, the system sends an in-app notification to Technical Support Staff with the event name, requested equipment list, and a link to review the request.
    AC2: Given Technical Support Staff approves or rejects an Equipment Request, the system sends an in-app notification to the Event Coordinator assigned to that event with the event name, the equipment covered by the decision, and the decision status (Approved or Rejected).
    AC3: Given a Technical Support Staff rejects the equipment request, the system sends an in-app notification to the Event Coordinator with the rejection message, event name, equipment request and link to the equipment request.
    Double: Stub (connection), Mock (channel ACK)
    """
    # Arrange (Given)
    connection, cursor, channel, order = storage
    envelope = equipment_envelope(outcome)
    expected = deepcopy(envelope)

    # Act (When)
    process("synthetic", channel, Mock(delivery_tag=48), json.dumps(envelope).encode())

    # Assert (Then)
    cursor.execute.assert_called_once()
    sql, params = cursor.execute.call_args.args
    assert sql.startswith('INSERT INTO public."Notification" ')
    assert "ON CONFLICT (source_id) WHERE source_id IS NOT NULL DO NOTHING" in sql
    assert params[:5] == (SOURCE, SOURCE, recipient, kind, EVENT)
    assert params[5].adapted == expected
    assert params[6:] == (SOURCE, CREATED)
    stored = params[5].adapted
    assert stored["details"]["eventName"] == "Community Fair"
    assert stored["details"]["items"][0] == dict(
        requestId=REQUEST, equipmentId=EQUIPMENT, equipmentName="Microphone", quantityRequested=5)
    assert stored["destination"] == dict(kind="equipment-requests", eventId=EVENT, requestIds=request_ids)
    if outcome == "submission":
        assert stored["details"]["items"][1] == dict(
            requestId=OTHER_REQUEST, equipmentId=OTHER_EQUIPMENT,
            equipmentName="Projector", quantityRequested=2)
        assert "decision" not in stored["details"]
    else:
        assert stored["details"]["decision"] == outcome
    assert "reason" not in stored["details"]
    connection.__exit__.assert_called_once_with(None, None, None)
    connection.close.assert_called_once()
    channel.basic_ack.assert_called_once_with(delivery_tag=48)
    assert order == ["inbox", "transaction-exit", "ack"]


@pytest.mark.parametrize("outcome,path,value", [
    pytest.param("submission", ("details", "recipientId"), OTHER, id="recipient-mismatch"),
    pytest.param("submission", ("details", "eventName"), 42, id="event-name-not-text"),
    pytest.param("Approved", ("details", "eventName"), " ", id="event-name-blank"),
    pytest.param("Approved", ("details", "decision"), "Pending", id="decision-not-final"),
    pytest.param("Rejected", ("details", "decision"), None, id="decision-null"),
    pytest.param("submission", ("details", "decision"), "Approved", id="submission-has-decision"),
    pytest.param("Rejected", ("details", "reason"), "Workflow-only reason", id="rejection-reason-forbidden"),
    pytest.param("submission", ("details", "items"), [], id="items-empty"),
    pytest.param("submission", ("details", "items"), {}, id="items-not-list"),
    pytest.param("submission", ("details", "items"), [None], id="item-not-object"),
    pytest.param("submission", ("details", "items", 0), {}, id="item-missing-fields"),
    pytest.param("Rejected", ("details", "items", 0, "reason"), "Private", id="item-extra-field"),
    pytest.param("submission", ("details", "items", 0, "requestId"), "bad-id", id="request-id-invalid"),
    pytest.param("Approved", ("details", "items", 0, "equipmentId"), "bad-id", id="equipment-id-invalid"),
    pytest.param("Approved", ("details", "items", 0, "equipmentName"), 42, id="equipment-name-not-text"),
    pytest.param("Rejected", ("details", "items", 0, "equipmentName"), " ", id="equipment-name-blank"),
    pytest.param("submission", ("details", "items", 0, "quantityRequested"), True, id="quantity-bool-not-integer"),
    pytest.param("Approved", ("details", "items", 0, "quantityRequested"), "5", id="quantity-text"),
    pytest.param("Rejected", ("details", "items", 0, "quantityRequested"), 1.5, id="quantity-fractional"),
    pytest.param("submission", ("details", "items", 0, "quantityRequested"), 0, id="quantity-zero"),
    pytest.param("Rejected", ("details", "items", 0, "quantityRequested"), -1, id="quantity-negative"),
    pytest.param("submission", ("destination", "kind"), "event-details", id="destination-wrong-page"),
    pytest.param("Approved", ("destination", "eventId"), OTHER, id="destination-wrong-event"),
    pytest.param("Rejected", ("destination", "requestIds"), [OTHER_REQUEST], id="destination-wrong-request"),
    pytest.param("submission", ("destination", "requestIds"), [REQUEST], id="destination-incomplete-items"),
    pytest.param("submission", ("destination", "eventId"), "bad-id", id="destination-event-id-invalid"),
])
def test_process_malformed_equipment_alert_quarantines_before_ack(storage, outcome, path, value):
    """Summary: A malformed equipment alert is kept aside, not delivered, before acknowledging.
    AC1: Given an Event Coordinator submits an equipment request, the system sends an in-app notification to Technical Support Staff with the event name, requested equipment list, and a link to review the request.
    AC2: Given Technical Support Staff approves or rejects an Equipment Request, the system sends an in-app notification to the Event Coordinator assigned to that event with the event name, the equipment covered by the decision, and the decision status (Approved or Rejected).
    AC3: Given a Technical Support Staff rejects the equipment request, the system sends an in-app notification to the Event Coordinator with the rejection message, event name, equipment request and link to the equipment request.
    Double: Stub (connection), Mock (channel ACK)
    """
    # Arrange (Given)
    connection, cursor, channel, order = storage
    envelope = equipment_envelope(outcome)
    target = envelope
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    body = json.dumps(envelope).encode()

    # Act (When)
    process("synthetic", channel, Mock(delivery_tag=48), body)

    # Assert (Then)
    cursor.execute.assert_called_once()
    sql, params = cursor.execute.call_args.args
    assert sql == 'INSERT INTO public."NotificationFailure" (body,error) VALUES (%s,%s)'
    assert params[0].adapted == body
    assert isinstance(params[1], str) and params[1]
    connection.__exit__.assert_called_once_with(None, None, None)
    connection.close.assert_called_once()
    channel.basic_ack.assert_called_once_with(delivery_tag=48)
    assert order == ["quarantine", "transaction-exit", "ack"]
