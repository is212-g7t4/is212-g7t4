"""SCRUM-47 Venue booking notification and decision alerts: consumer unit tests.

Story: As an Event Coordinator and Venue Staff, I want to receive notifications
about venue booking requests and decisions, so that I can coordinate venue
arrangements efficiently.
AC1 Given an Event Coordinator submits a venue booking request, system sends
an in-app notification to Venue Staff with event name, requested venue,
date/time and link to review.
AC2 Given booking approved/rejected, sends an in-app notification to Event
Coordinator with event name, venue, decision.

AC = acceptance criterion; DR = supporting design rule, not an extra AC.
Real: process -> parser/booking validator -> store SQL/transaction adapter.
Doubled: native psycopg2 connection/cursor and broker ACK channel, no live sockets.
AC1: staff envelopes retain event_id despite their ID-less review destination.
AC2: approved/rejected envelopes keep the original submitter, decision and link.
DR: malformed booking contracts quarantine exact bytes before ACK, never deliver.
Not proven: durable SQL commits, actual inbox API visibility, RabbitMQ redelivery,
producer recipient selection, SGT formatting or rendered links; owner/dispatcher
unit modules test production of the contracts, integration proves persisted state.
"""
from copy import deepcopy
import json
from unittest.mock import MagicMock, Mock

import pytest

from app.consumer import process

EVENT = "10000000-0000-0000-0000-000000000001"
BOOKING = "10000000-0000-0000-0000-000000000002"
VENUE = "10000000-0000-0000-0000-000000000003"
SOURCE_ID = "10000000-0000-0000-0000-000000000004"
STAFF = "20000000-0000-0000-0000-000000000001"
SUBMITTER = "30000000-0000-0000-0000-000000000001"
OTHER = "30000000-0000-0000-0000-000000000002"
CREATED = "2026-10-27T00:00:00+00:00"


def booking_envelope(outcome) -> dict:
    submission = outcome == "submission"
    details = dict(eventId=EVENT, bookingId=BOOKING, venueId=VENUE, requestedBy=SUBMITTER,
                   eventName="Community Fair", venueName="Grand Hall",
                   startDateTime="2099-01-01T01:00:00+00:00", endDateTime="2099-01-01T03:00:00+00:00")
    details.update({"recipientId": STAFF} if submission else {"decision": outcome})
    return dict(version=1, id=SOURCE_ID, recipientId=STAFF if submission else SUBMITTER,
                type="venue.booking-submission" if submission else "venue.booking-decision",
                message="Community Fair venue booking update", createdAt=CREATED,
                destination={"kind": "venue-requests"} if submission else
                    {"kind": "event-venue-request", "eventId": EVENT, "bookingId": BOOKING},
                details=details)


@pytest.fixture
def storage(monkeypatch):
    connection, channel = MagicMock(), Mock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("psycopg2.connect", lambda *args, **kwargs: connection)
    order = []
    cursor.execute.side_effect = lambda sql, params: order.append(
        "quarantine" if '"NotificationFailure"' in sql else "inbox")
    connection.__exit__.side_effect = lambda *args: order.append("commit")
    channel.basic_ack.side_effect = lambda **kwargs: order.append("ack")
    return connection, cursor, channel, order


# AC1/AC2 — all three valid outcomes traverse the real consumer and store.
@pytest.mark.parametrize("outcome,recipient,kind", [
    pytest.param("submission", STAFF, "venue.booking-submission", id="staff-submission"),
    pytest.param("Approved", SUBMITTER, "venue.booking-decision", id="approved-original-submitter"),
    pytest.param("Rejected", SUBMITTER, "venue.booking-decision", id="rejected-original-submitter"),
])
def test_ac1_ac2_valid_booking_alert_keeps_exact_sql_contract_before_ack(storage, outcome, recipient, kind):
    """Normal: staff submission or original-submitter decision reaches one exact inbox insert before ACK."""
    connection, cursor, channel, order = storage
    envelope = booking_envelope(outcome)
    expected_payload = deepcopy(envelope)

    process("synthetic", channel, Mock(delivery_tag=47), json.dumps(envelope).encode())

    cursor.execute.assert_called_once()
    sql, params = cursor.execute.call_args.args
    assert 'INSERT INTO public."Notification" ' in sql
    assert "(source_id,notification_id,recipient_id,type,event_id,payload,dedupe_key,created_at)" in sql
    assert "ON CONFLICT (source_id) WHERE source_id IS NOT NULL DO NOTHING" in sql
    assert params[:5] == (SOURCE_ID, SOURCE_ID, recipient, kind, EVENT)
    assert params[5].adapted == expected_payload
    assert params[6:] == (SOURCE_ID, CREATED)
    connection.__exit__.assert_called_once_with(None, None, None)
    connection.close.assert_called_once()
    channel.basic_ack.assert_called_once_with(delivery_tag=47)
    assert order == ["inbox", "commit", "ack"]


# DR supporting AC1/AC2 — each malformed contract must be retained, never delivered.
@pytest.mark.parametrize("outcome,change,details_change", [
    pytest.param("submission", {"details": []}, {}, id="details-not-object"),
    pytest.param("submission", {"destination": {"kind": "event-details", "eventId": EVENT}}, {},
                 id="submission-not-staff-review"),
    pytest.param("submission", {}, {"recipientId": OTHER}, id="staff-recipient-mismatch"),
    pytest.param("Approved", {}, {"decision": "Pending Review"}, id="unsupported-decision"),
    pytest.param("Approved", {"recipientId": OTHER}, {}, id="decision-not-original-submitter"),
    pytest.param("Rejected", {"destination": {"kind": "event-venue-request", "eventId": EVENT,
                                                "bookingId": OTHER}}, {}, id="decision-wrong-booking-link"),
    pytest.param("submission", {}, {"eventName": 42}, id="invalid-event-name"),
    pytest.param("Approved", {}, {"venueName": " "}, id="blank-venue-name"),
    pytest.param("submission", {}, {"startDateTime": "2099-01-01T01:00:00"}, id="start-without-timezone"),
    pytest.param("Rejected", {}, {"endDateTime": "2099-01-01T03:00:00"}, id="end-without-timezone"),
    pytest.param("Approved", {}, {"endDateTime": "2099-01-01T00:00:00+00:00"}, id="reversed-requested-period"),
    pytest.param("submission", {}, {"bookingId": None}, id="missing-required-booking-id"),
    pytest.param("Rejected", {}, {"requestedBy": "not-a-uuid"}, id="malformed-original-submitter"),
])
def test_ac1_ac2_invalid_booking_alert_quarantines_exact_body_before_ack(storage, outcome, change, details_change):
    """Failure: each malformed booking contract is quarantined before ACK with no inbox delivery."""
    connection, cursor, channel, order = storage
    envelope = booking_envelope(outcome)
    if details_change.get("bookingId", "present") is None:
        del envelope["details"]["bookingId"]  # Omission, not an explicit null.
    else:
        envelope["details"].update(details_change)
    envelope.update(change)
    body = json.dumps(envelope).encode()

    process("synthetic", channel, Mock(delivery_tag=48), body)

    cursor.execute.assert_called_once()
    sql, params = cursor.execute.call_args.args
    assert sql == 'INSERT INTO public."NotificationFailure" (body,error) VALUES (%s,%s)'
    assert params[0].adapted == body
    assert isinstance(params[1], str) and params[1]
    connection.__exit__.assert_called_once_with(None, None, None)
    connection.close.assert_called_once()
    channel.basic_ack.assert_called_once_with(delivery_tag=48)
    assert order == ["quarantine", "commit", "ack"]
