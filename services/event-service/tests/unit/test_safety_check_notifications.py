"""
SCRUM-168: Safety Check Notifications

User Story
----------
As an Event Coordinator, I want to be notified of the Safety Officer's decision
on my event, so that I can act on it straight away.

Acceptance Criteria
-------------------
AC1: Given an event is submitted or resubmitted for a safety check, then Safety
     Officers receive an in-app notification with the event name, date and a
     link to the review.
AC2: Given a decision is recorded, then the assigned Event Coordinator receives
     an in-app notification with the event name, the decision and, for
     rejection or requested changes, the reason and affected areas.
AC3: Given notification delivery fails, then the decision remains recorded and
     is not rolled back.
AC4: Given a notification is sent, then it records the event, recipient, type
     and timestamp.

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
import json
from uuid import UUID, uuid5

import pytest

from tests.unit.factories import (
    COORDINATOR, EVENT, HEADERS, JOB, LEASE, OFFICER, OTHER_OFFICER, OUTBOX_HEADERS, ROUND,
    pending_safety_notification_row, safety_envelope, safety_outbox_row,
)

def test_submission_saves_officer_fanout_in_the_business_transaction(safety_notification_boundary):
    """
    Summary: Submitting saves a review intent with the submitted event/date/round.
    AC1: Given an event is submitted or resubmitted for a safety check, then
        Safety Officers receive an in-app notification with the event name,
        date and a link to the review.
    AC4: Given a notification is sent, then it records the event, recipient,
        type and timestamp.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, row = safety_notification_boundary
    cursor.fetchone.side_effect = [row, {**row, 'status': 'Pending Safety Check'}]

    # Act (When)
    response = client.patch(f'/events/{EVENT}/safety-status', headers=HEADERS,
                            json=dict(status='Pending Safety Check', coordinatorId=COORDINATOR,
                                      safetyCheckId=ROUND, roundNumber=1))

    # Assert (Then)
    assert response.status_code == 200
    inserts = [call.args[1] for call in cursor.execute.call_args_list
               if 'INSERT INTO public."EventNotificationOutbox"' in call.args[0]]
    assert len(inserts) == 1
    assert inserts[0][1] == 'safety.review-fanout'
    assert inserts[0][2].adapted == dict(eventId=EVENT, eventName='Workshop', round=1,
                                       startDateTime='2030-03-01T09:00:00+08:00',
                                       endDateTime='2030-03-01T17:00:00+08:00')

@pytest.mark.parametrize('start,end,message', [
    ('2030-03-01T15:59:00+00:00', '2030-03-01T16:00:00+00:00',
     'Workshop requires safety review (round 1). Proposed: 01 Mar 2030, 23:59 SGT – 02 Mar 2030, 00:00 SGT.'),
    (None, None, 'Workshop requires safety review (round 1). Proposed: Not provided.'),
], ids=['singapore-midnight', 'unscheduled'])
def test_review_freezes_original_schedule_and_recipient(safety_notification_boundary, start, end, message):
    """
    Summary: Preserve the original interval, including Singapore midnight or no dates.
    AC1: Given an event is submitted or resubmitted for a safety check, then
        Safety Officers receive an in-app notification with the event name,
        date and a link to the review.
    AC4: Given a notification is sent, then it records the event, recipient,
        type and timestamp.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, _ = safety_notification_boundary
    row = safety_outbox_row('safety.review-submitted', dict(
        eventId=EVENT, eventName='Workshop', round=1, recipientId=OFFICER,
        startDateTime=start, endDateTime=end))
    envelope = safety_envelope(row, message)
    cursor.fetchone.side_effect = [row, {**row, 'envelope': envelope}]

    # Act (When)
    response = client.post(f'/internal/notification-outbox/{JOB}/freeze', headers=OUTBOX_HEADERS,
                           json=dict(leaseToken=LEASE, envelope=envelope))

    # Assert (Then)
    assert response.status_code == 200
    assert response.json['envelope'] == envelope
    assert response.json['source'] == row['source']
    assert response.json['createdAt'] == '2030-01-01T00:00:00+00:00'
    writes = [call.args[1] for call in cursor.execute.call_args_list if 'SET envelope=' in call.args[0]]
    assert len(writes) == 1
    assert writes[0][0].adapted == envelope
    assert writes[0][1] == JOB


@pytest.mark.parametrize('recipients', [[OTHER_OFFICER, OFFICER, OTHER_OFFICER], []],
                         ids=['all-officers-deduplicated', 'no-officers'])
def test_review_fanout_uses_only_supplied_officers_and_completes(safety_notification_boundary, recipients):
    """
    Summary: Expand unique officer jobs or complete an empty lookup without inventing recipients.
    AC1: Given an event is submitted or resubmitted for a safety check, then
        Safety Officers receive an in-app notification with the event name,
        date and a link to the review.
    AC4: Given a notification is sent, then it records the event, recipient,
        type and timestamp.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, _ = safety_notification_boundary
    source = dict(eventId=EVENT, eventName='Workshop', round=1,
                  startDateTime='2030-03-01T09:00:00+08:00', endDateTime='2030-03-01T17:00:00+08:00')
    row = safety_outbox_row('safety.review-fanout', source)
    cursor.fetchone.return_value = row

    # Act (When)
    response = client.post(f'/internal/notification-outbox/{JOB}/expand', headers=OUTBOX_HEADERS,
                           json=dict(leaseToken=LEASE, recipientIds=recipients))

    # Assert (Then)
    assert response.status_code == 200
    expected_recipients = [OFFICER, OTHER_OFFICER] if recipients else []
    assert response.json == dict(id=JOB, status='expanded', recipients=len(expected_recipients))
    inserts = [call.args[1] for call in cursor.execute.call_args_list
               if call.args[0].lstrip().startswith('INSERT')]
    assert len(inserts) == len(expected_recipients)
    for values, recipient in zip(inserts, expected_recipients, strict=True):
        assert values[0] == str(uuid5(UUID(JOB), recipient))
        assert values[1] == 'safety.review-submitted'
        assert values[2].adapted == {**source, 'recipientId': recipient}
        assert values[3] == row['created_at']
    updates = [call for call in cursor.execute.call_args_list
               if call.args[0].lstrip().startswith('UPDATE')]
    assert len(updates) == 1
    assert 'published_at=now(),lease_token=NULL,lease_until=NULL,last_error=NULL' in updates[0].args[0]
    assert updates[0].args[1] == (JOB,)


@pytest.mark.parametrize('decision,reason,areas,message', [
    ('Approved', None, [], 'Workshop safety review: Approved (round 1).'),
    ('Approved', 'Keep exits clear.', [],
     'Workshop safety review: Approved (round 1). Keep exits clear.'),
    ('Rejected', 'Unsafe exits. The full plan must be revised.', [],
     'Workshop safety review: Rejected (round 1). Unsafe exits. The full plan must be revised.'),
    ('Changes Requested', 'Revise both plans.', ['venue arrangement', 'event details'],
     'Workshop safety review: Changes Requested (round 1). Revise both plans. Affected areas: venue arrangement, event details.'),
], ids=['approval-without-remarks', 'approval-with-remarks', 'rejection-reason', 'changes-reason-areas'])
def test_decision_freezes_complete_content_for_captured_recipient(safety_notification_boundary, decision, reason, areas, message):
    """
    Summary: Freeze each decision with its full remarks/reason/areas and original coordinator.
    AC2: Given a decision is recorded, then the assigned Event Coordinator
        receives an in-app notification with the event name, the decision and,
        for rejection or requested changes, the reason and affected areas.
    AC4: Given a notification is sent, then it records the event, recipient,
        type and timestamp.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, _ = safety_notification_boundary
    row = safety_outbox_row('safety.review-decision', dict(
        eventId=EVENT, eventName='Workshop', recipientId=COORDINATOR,
        round=1, decision=decision, reason=reason, areas=areas))
    envelope = safety_envelope(row, message)
    cursor.fetchone.side_effect = [row, {**row, 'envelope': envelope}]

    # Act (When)
    response = client.post(f'/internal/notification-outbox/{JOB}/freeze', headers=OUTBOX_HEADERS,
                           json=dict(leaseToken=LEASE, envelope=envelope))

    # Assert (Then)
    assert response.status_code == 200
    assert response.json['envelope'] == envelope
    assert response.json['source'] == row['source']
    assert response.json['createdAt'] == '2030-01-01T00:00:00+00:00'
    writes = [call.args[1] for call in cursor.execute.call_args_list if 'SET envelope=' in call.args[0]]
    assert len(writes) == 1
    assert writes[0][0].adapted == envelope
    assert writes[0][1] == JOB


@pytest.mark.parametrize('defect', ['missing-reason', 'missing-areas', 'changed-details', 'changed-destination'])
def test_incomplete_or_changed_decision_envelope_is_not_frozen(safety_notification_boundary, defect):
    """
    Summary: Reject lost decision content, changed captured facts or a wrong event link before writing.
    AC2: Given a decision is recorded, then the assigned Event Coordinator
        receives an in-app notification with the event name, the decision and,
        for rejection or requested changes, the reason and affected areas.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, _ = safety_notification_boundary
    row = safety_outbox_row('safety.review-decision', dict(
        eventId=EVENT, eventName='Workshop', recipientId=COORDINATOR, round=1,
        decision='Changes Requested', reason='Revise both plans.',
        areas=['venue arrangement', 'event details']))
    envelope = safety_envelope(row,
        'Workshop safety review: Changes Requested (round 1). Revise both plans. Affected areas: venue arrangement, event details.')
    if defect == 'missing-reason':
        envelope['message'] = 'Workshop safety review: Changes Requested (round 1). Affected areas: venue arrangement, event details.'
    elif defect == 'missing-areas':
        envelope['message'] = 'Workshop safety review: Changes Requested (round 1). Revise both plans.'
    elif defect == 'changed-details':
        envelope['details']['reason'] = 'A later reason.'
    else:
        envelope['destination'] = dict(kind='event-details', eventId=ROUND)
    cursor.fetchone.return_value = row

    # Act (When)
    response = client.post(f'/internal/notification-outbox/{JOB}/freeze', headers=OUTBOX_HEADERS,
                           json=dict(leaseToken=LEASE, envelope=envelope))

    # Assert (Then)
    assert response.status_code == 400
    assert response.json == dict(message='Invalid outbox input.')
    assert not any(call.args[0].lstrip().startswith(('INSERT', 'UPDATE', 'DELETE'))
                   for call in cursor.execute.call_args_list)


# DR ---- missing-recipient compatibility; not coordinator switching

def test_missing_coordinator_does_not_undo_a_valid_safety_decision(safety_notification_boundary, caplog):
    """
    Summary: A legacy pending event without a coordinator records its decision and warns without an invalid alert.
    AC1: Given an event is submitted or resubmitted for a safety check, then
        Safety Officers receive an in-app notification with the event name,
        date and a link to the review.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, _ = safety_notification_boundary
    row = pending_safety_notification_row(coordinator_id=None)
    cursor.fetchone.side_effect = [row, {**row, 'status': 'Confirmed'}]

    # Act (When)
    response = client.patch(f'/events/{EVENT}/safety-status', headers=HEADERS,
                            json=dict(status='Confirmed', decidedBy=OFFICER,
                                      safetyCheckId=ROUND, roundNumber=1))

    # Assert (Then)
    assert response.status_code == 200
    assert response.json['status'] == 'Confirmed'
    updates = [call.args[1] for call in cursor.execute.call_args_list
               if call.args[0].lstrip().startswith('UPDATE')]
    assert len(updates) == 1
    assert updates[0][0] == 'Confirmed'
    history = json.loads(updates[0][1])['actionHistory']
    assert history[-1]['status'] == 'Confirmed'
    assert history[-1]['decidedBy'] == OFFICER
    assert history[-1]['safetyCheckId'] == ROUND
    assert not any(call.args[0].lstrip().startswith('INSERT') for call in cursor.execute.call_args_list)
    assert any(record.levelname == 'WARNING' and
               record.getMessage() == f'Safety decision missing coordinator event={EVENT}'
               for record in caplog.records)
