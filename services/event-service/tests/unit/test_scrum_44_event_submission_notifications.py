"""
SCRUM-44: Event Coordinator Notification and Alert Workflow

User Story
----------
As a Lead Coordinator, I want to receive an in-app notification when an Event
Organiser submits an event request, so that I can review it and make a
decision.

Acceptance Criteria
-------------------
AC1: Given an Event Organiser submits a new event request, the Lead Coordinator
     receives an in-app notification that a new request requires review.
AC2: The notification includes the event name, Event Organiser name, proposed
     event date/time, and a link to review the event request.
AC3: Saving or editing a draft event request does not trigger a submission
     notification.

Real
----
- The Event Service routes in app/__init__.py and the rules in app/models.py,
  run through a real create_app(): request validation, the caller's role and
  ownership checks from the signed token, the status rules, and the SQL and
  parameters sent to the database (including notification outbox rows).
- Assertions are on the HTTP status, the response body and the queries and
  parameters the cursor received.

Doubled
-------
- psycopg2.connect: Stub (fixture) - a MagicMock connection whose cursor
  returns canned rows; Mock - its execute calls are asserted to prove what was
  (or was not) written.
- Supabase JWKS: Stub (tests/conftest.py) - tokens are signed with a throwaway
  ES256 key.

Not proven
----------
- That the SQL runs against the real Postgres schema, constraints and row locks
  (-> tests/integration/ against a throwaway postgres:17.6).
- That the notification outbox rows are delivered (-> Notification Service
  tests and the E2E journeys).
"""
from datetime import datetime, UTC
from unittest.mock import MagicMock
from uuid import UUID, uuid5

import pytest
from app import create_app
from tests.unit.factories import signed_in

ID = '10000000-0000-0000-0000-000000000001'
RECIPIENT = '10000000-0000-0000-0000-000000000002'
SOURCE = dict(eventId=ID, eventName='Workshop', organiserId=ID,
              startDateTime='2030-06-02T09:15:00+08:00', endDateTime='2030-06-02T12:45:00+08:00')


@pytest.fixture
def boundary(monkeypatch):
    """Return a real Flask client, mock SQL cursor and editable claimed row.
    The mock connection never contacts PostgreSQL."""
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr('app.outbox.psycopg2.connect', lambda *a, **kw: connection)
    client = signed_in(create_app({'TESTING': True, 'DATABASE_URL': 'unused', 'INTERNAL_SERVICE_TOKEN': 'synthetic'}).test_client())
    row = dict(source_id=ID, type='event.submission-fanout', source=SOURCE, envelope=None,
               created_at=datetime(2026, 10, 25, tzinfo=UTC), lease_token=ID, lease_valid=True, attempts=1)
    cursor.fetchone.side_effect = lambda: row
    return client, cursor, row


def operate(client, action, **data):
    """Post an outbox operation with the test lease and internal token.
    Return the Flask response."""
    return client.post(f'/internal/notification-outbox/{ID}/{action}',
                       json={'leaseToken': ID, **data}, headers={'X-Internal-Token': 'synthetic'})


# AC1 — Prepare one delivery per Lead.

@pytest.mark.parametrize('recipients', [[], [RECIPIENT, RECIPIENT]],
                         ids=['no-leads', 'duplicate-lead'])
def test_expansion_saves_unique_recipient_deliveries_and_completes_intent(boundary, recipients):
    """
    Summary: Repeated Lead IDs prepare only one delivery.
    AC1: Given an Event Organiser submits a new event request, the Lead
        Coordinator receives an in-app notification that a new request requires
        review.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, row = boundary

    # Act (When)
    response = operate(client, 'expand', recipientIds=recipients, organiserName='Synthetic Organiser')

    # Assert (Then)
    assert response.status_code == 200
    inserts = [call.args[1] for call in cursor.execute.call_args_list if 'INSERT INTO' in call.args[0]]
    assert len(inserts) == (1 if recipients else 0)
    if inserts:
        identifier, kind, payload, created = inserts[0]
        assert identifier == str(uuid5(UUID(ID), RECIPIENT))
        assert kind == 'event.submission'
        assert payload.adapted['recipientId'] == RECIPIENT
        assert payload.adapted['organiserName'] == 'Synthetic Organiser'
        assert payload.adapted['startDateTime'] == '2030-06-02T09:15:00+08:00'
        assert payload.adapted['endDateTime'] == '2030-06-02T12:45:00+08:00'
        assert datetime.fromisoformat(payload.adapted['organiserNameCapturedAt']).tzinfo
        assert created == row['created_at']
    assert 'published_at=now()' in cursor.execute.call_args.args[0]


# AC1 — Reject invalid delivery inputs.

@pytest.mark.parametrize('kind,recipients,name', [
    ('event.approval', [], 'Synthetic'),
    ('event.submission-fanout', None, 'Synthetic'),
    ('event.submission-fanout', [], None),
    ('event.submission-fanout', [], ''),
    ('event.submission-fanout', ['invalid'], 'Synthetic'),
], ids=['wrong-notification-type', 'missing-recipients', 'missing-organiser-name',
        'blank-organiser-name', 'invalid-recipient-id'])
def test_invalid_expansion_is_refused_without_writes(boundary, kind, recipients, name):
    """
    Summary: Invalid delivery inputs return 400 without write SQL.
    AC1: Given an Event Organiser submits a new event request, the Lead
        Coordinator receives an in-app notification that a new request requires
        review.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, row = boundary
    row['type'] = kind

    # Act + Assert (When / Then)
    assert operate(client, 'expand', recipientIds=recipients, organiserName=name).status_code == 400
    assert len(cursor.execute.call_args_list) == 1


# AC2 — Save matching review details.

def test_submission_freeze_preserves_exact_saved_content(boundary):
    """
    Summary: A matching message is accepted for saving before sending.
    AC2: The notification includes the event name, Event Organiser name,
        proposed event date/time, and a link to review the event request.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, cursor, row = boundary
    row.update(type='event.submission', source={**SOURCE, 'recipientId': RECIPIENT, 'organiserName': 'Synthetic Organiser'})
    envelope = dict(version=1, id=ID, type='event.submission', recipientId=RECIPIENT,
                    createdAt=row['created_at'].isoformat(), details=row['source'],
                    destination={'kind': 'event-details', 'eventId': ID},
                    message='Synthetic Organiser submitted Workshop. Review required.')
    def frozen_row():
        if len(cursor.execute.call_args_list) > 1:
            return {**row, 'envelope': envelope}
        return row
    cursor.fetchone.side_effect = frozen_row
    response = operate(client, 'freeze', envelope=envelope)
    assert response.status_code == 200
    assert response.json['envelope'] == envelope


# AC2 — Reject changed review details.

@pytest.mark.parametrize('changed_field', ['details', 'message', 'destination'])
def test_altered_submission_context_cannot_be_frozen(boundary, changed_field):
    """
    Summary: Changed event details, approval text or another event link are rejected.
    AC2: The notification includes the event name, Event Organiser name,
        proposed event date/time, and a link to review the event request.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, cursor, row = boundary
    row.update(type='event.submission', source={**SOURCE, 'recipientId': RECIPIENT, 'organiserName': 'Synthetic Organiser'})
    envelope = dict(version=1, id=ID, type='event.submission', recipientId=RECIPIENT,
                    createdAt=row['created_at'].isoformat(), details=row['source'],
                    destination={'kind': 'event-details', 'eventId': ID},
                    message='Synthetic Organiser submitted Workshop. Review required.')
    altered = {
        'details': {**row['source'], 'eventName': 'Not the submitted event'},
        'message': 'Request already approved.',
        'destination': {'kind': 'event-details', 'eventId': RECIPIENT},
    }
    response = operate(client, 'freeze', envelope={**envelope, changed_field: altered[changed_field]})
    assert response.status_code == 400
    assert response.json['message'] == 'Invalid outbox input.'
    assert all(not call.args[0].lstrip().startswith(('UPDATE ', 'INSERT '))
               for call in cursor.execute.call_args_list)
