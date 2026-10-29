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


def baseline_entry(status='Pending Safety Check', start='2030-03-01T09:00:00+08:00',
                   end='2030-03-01T17:00:00+08:00', venue='Hall A', **extra):
    """One actionHistory entry carrying the pre-change attendee facts, as update_event_details writes it."""
    baseline = {key: value for key, value in (('startDateTime', start), ('endDateTime', end)) if value is not None}
    baseline['venueName'] = venue
    return dict(status=status, details='Event details updated.', attendeeBaseline=baseline, **extra)


def approval_entry(round_id=ROUND, **extra):
    """The Safety Officer's approval entry; attendee_baseline stops at it."""
    return dict(status='Confirmed', safetyCheckId=round_id, details='Safety approved.', **extra)


def attendee_summary_row(status, history, start=datetime(2030, 3, 2, 1, tzinfo=UTC),
                         end=datetime(2030, 3, 2, 10, tzinfo=UTC), description=None, **extra):
    """A row as list_attendee_event_summaries selects it; the live window defaults to the *new* 2030-03-02 times."""
    if description is None:
        description = json.dumps({'_connectsphere': 'event-submission-v1', 'description': 'Workshop',
                                  'purpose': 'Learning', 'actionHistory': history})
    row = dict(event_id=EVENT, event_name='Workshop', status=status, coordinator_id=COORDINATOR,
               preferred_start_date=start, preferred_end_date=end, description=description)
    return {**row, **extra}
