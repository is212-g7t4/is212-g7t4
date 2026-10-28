"""Synthetic Event story row builders; never connect to a database."""
from datetime import UTC, datetime
import json
from typing import Any
from app.models import FIELDS

EVENT = '10000000-0000-0000-0000-000000000001'
COORDINATOR = '10000000-0000-0000-0000-000000000002'
ROUND = '10000000-0000-0000-0000-000000000003'
OFFICER = '10000000-0000-0000-0000-000000000004'
HEADERS = {'X-Internal-Service-Token': 'synthetic'}
OUTBOX_HEADERS = {'X-Internal-Token': 'synthetic'}
JOB = '10000000-0000-0000-0000-000000000005'
LEASE = '10000000-0000-0000-0000-000000000006'
OTHER_OFFICER = '10000000-0000-0000-0000-000000000007'


def safety_outbox_row(kind, source):
    """A leased persisted row as returned by app/outbox.py's locking SELECT."""
    return dict(source_id=JOB, type=kind, source=source, envelope=None,
                lease_token=LEASE, lease_valid=True, attempts=1,
                created_at=datetime(2030, 1, 1, tzinfo=UTC))


def safety_envelope(row, message) -> dict[str, Any]:
    """Client contract shape from app/outbox.py; expected text supplied by each case."""
    return dict(version=1, id=JOB, type=row['type'],
                recipientId=row['source']['recipientId'],
                createdAt='2030-01-01T00:00:00+00:00',
                message=message, details=dict(row['source']),
                destination=dict(kind='event-details', eventId=EVENT))


def pending_safety_notification_row(coordinator_id: str | None = COORDINATOR):
    """A pending round, including a nullable legacy coordinator, with no assignment changes."""
    row = safety_notification_row()
    metadata = json.loads(row['description'])
    metadata['actionHistory'] = [dict(status='Pending Safety Check', safetyCheckId=ROUND,
                                      details='Submitted for Operational Safety Check (round 1).')]
    row.update(status='Pending Safety Check', coordinator_id=coordinator_id,
               description=json.dumps(metadata))
    return row



def safety_notification_row() -> dict[str, Any]:
    row = dict.fromkeys(FIELDS.values(), '')
    row.update(event_id=EVENT, event_name='Workshop', status='Approved',
               coordinator_id=COORDINATOR, organiser_id=None, expected_attendance=25,
               submission_date=datetime(2026, 10, 1, tzinfo=UTC),
               preferred_start_date=datetime(2030, 3, 1, 1, tzinfo=UTC),
               preferred_end_date=datetime(2030, 3, 1, 9, tzinfo=UTC),
               description=json.dumps({'_connectsphere': 'event-submission-v1',
                                       'description': 'Workshop', 'purpose': 'Learning'}))
    return row
