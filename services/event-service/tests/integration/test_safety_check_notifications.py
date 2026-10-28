"""SCRUM-168 Safety Check Notifications: event-service integration tests.

Story:      As a Safety Officer or Event Coordinator, I want to receive notifications when a safety review requires my action or a safety decision is recorded, so that I can respond promptly.
Real:       Event Flask routes, validation, models/outbox SQL, postgres:17.6 with the full migration chain.
Doubled:    User recipient lookup supplied as IDs; no other service or broker runs.
Not proven: authentication, hosted permissions, live inbox delivery or browser navigation.

AC1  Given an event is submitted or resubmitted for a safety check, then Safety Officers receive an in-app notification with the event name, date and a link to the review.
Coverage: Review intent/fanout/freezing persists; officer lookup/publication belongs to Workflow unit tests.
AC2  Given a decision is recorded, the assigned Event Coordinator receives an in-app notification containing the event name and decision (approval, rejection, or requested changes). Rejection and requested-changes notifications include the reason. Requested-changes notifications include the affected areas. Approval notifications include remarks when provided.
Coverage: Locked coordinator and complete supplied content persist/freeze; publication belongs to Workflow unit tests.
AC3  Given notification delivery fails, then the decision remains recorded and is not rolled back.
Coverage: Public retry preserves the committed decision; broker failure is doubled in Workflow unit tests.
AC4  Given a notification is sent, then it records the event, recipient, type and timestamp.
Coverage: Persisted Event outbox metadata; inbox receipt belongs to Notification unit tests.

AC = acceptance criterion; DR = supporting design rule. Automatic rechecks and
fixed coordinator recipients and atomic initial intent-save failure are supporting
DRs, not extra ACs or switching scenarios. The legacy test_ac3_initial_intent_save
name is retained for stable collection identity; it verifies a DR, not AC3 delivery.
Fixed 2030 schedules are event facts, not deadlines against the current clock;
server-created timestamps are bracketed by PostgreSQL clock_timestamp() readings.
"""
import time
from datetime import datetime
from threading import Event
from uuid import uuid4

import pytest
from tests.integration.factories import make_safety_event

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
COORDINATOR = '10000000-0000-0000-0000-000000000002'
OFFICER = '10000000-0000-0000-0000-000000000004'
OTHER = '10000000-0000-0000-0000-000000000005'
TOKEN = 'synthetic'
BUSINESS_HEADERS = {'X-Internal-Service-Token': TOKEN}
OUTBOX_HEADERS = {'X-Internal-Token': TOKEN}



def move(client, identifier, round_id, status='Pending Safety Check', number=1, **extra):
    return client.patch(f'/events/{identifier}/safety-status', headers=BUSINESS_HEADERS,
                        json=dict(status=status, safetyCheckId=round_id, roundNumber=number,
                                  **({'coordinatorId': COORDINATOR} if status == 'Pending Safety Check'
                                     else {'decidedBy': OFFICER}), **extra))


def claim(client):
    # Cancellation also creates two independent SCRUM-49 jobs at this timestamp.
    # Leave those leased and select this story's work, without assuming UUID order.
    for _ in range(3):
        response = client.post('/internal/notification-outbox/claim', json={}, headers=OUTBOX_HEADERS)
        assert response.status_code == 200
        job = response.json['jobs'][0]
        if job['type'] != 'event.cancelled':
            return job
    pytest.fail("Safety work was not found within its two cancellation siblings")


# AC1 ---- review persistence and new rounds (AC4 metadata)
def test_ac1_submission_fans_out_to_all_supplied_officers_with_stable_metadata(safety_notification_owner):
    """Normal: AC1/AC4: a saved submission expands into distinct recipient jobs with one timestamp."""
    client, db = safety_notification_owner
    identifier = make_safety_event(db)
    before = db.query('SELECT clock_timestamp()')[0][0]
    assert move(client, identifier, str(uuid4())).status_code == 200
    after = db.query('SELECT clock_timestamp()')[0][0]
    parent = claim(client)
    created = datetime.fromisoformat(parent['createdAt'])
    assert created.utcoffset() is not None
    assert before <= created <= after
    assert parent['type'] == 'safety.review-fanout'
    assert parent['source'] == dict(eventId=identifier, eventName='Workshop', round=1,
                                   startDateTime='2030-03-01T09:00:00+08:00',
                                   endDateTime='2030-03-01T17:00:00+08:00')
    response = client.post(f"/internal/notification-outbox/{parent['id']}/expand",
                           headers=OUTBOX_HEADERS,
                           json=dict(leaseToken=parent['leaseToken'], recipientIds=[OFFICER, OTHER]))
    assert response.status_code == 200
    children = db.query('''SELECT type,source,created_at FROM public."EventNotificationOutbox"
                           WHERE type='safety.review-submitted' ORDER BY source->>'recipientId' ''')
    assert [row[1]['recipientId'] for row in children] == [OFFICER, OTHER]
    for kind, source, created in children:
        assert kind == 'safety.review-submitted'
        assert source == {**parent['source'], 'recipientId': source['recipientId']}
        assert created.isoformat() == parent['createdAt']
    child = claim(client)
    envelope = dict(version=1, id=child['id'], type=child['type'], recipientId=child['source']['recipientId'],
                    createdAt=child['createdAt'], details=child['source'],
                    destination=dict(kind='event-details', eventId=identifier),
                    message='Workshop requires safety review (round 1). Proposed: 01 Mar 2030, 09:00 SGT – 01 Mar 2030, 17:00 SGT.')
    frozen = client.post(f"/internal/notification-outbox/{child['id']}/freeze", headers=OUTBOX_HEADERS,
                         json=dict(leaseToken=child['leaseToken'], envelope=envelope))
    assert frozen.status_code == 200
    assert frozen.json['envelope'] == envelope
    # Independent fixture connection: read the exact committed row, not the HTTP echo.
    assert db.query('SELECT envelope FROM public."EventNotificationOutbox" WHERE source_id=%s',
                    [envelope['id']]) == [(envelope,)]


@pytest.mark.parametrize('trigger', ['resubmit', 'automatic-recheck'])
def test_ac1_each_new_pending_round_saves_a_new_review_with_current_schedule(safety_notification_owner, trigger):
    """Normal: AC1: explicit resubmit and automatic high-impact recheck save round two's review."""
    client, db = safety_notification_owner
    previous, next_round = str(uuid4()), str(uuid4())
    # Arrange a real first-round review through the owner API, not history alone.
    identifier = make_safety_event(db)
    assert move(client, identifier, previous).status_code == 200
    parent = claim(client)
    expanded = client.post(f"/internal/notification-outbox/{parent['id']}/expand",
                           headers=OUTBOX_HEADERS,
                           json=dict(leaseToken=parent['leaseToken'], recipientIds=[OFFICER]))
    assert expanded.status_code == 200
    child = claim(client)
    envelope = dict(version=1, id=child['id'], type='safety.review-submitted', recipientId=OFFICER,
                    createdAt=child['createdAt'], details=child['source'],
                    destination=dict(kind='event-details', eventId=identifier),
                    message='Workshop requires safety review (round 1). Proposed: 01 Mar 2030, 09:00 SGT – 01 Mar 2030, 17:00 SGT.')
    frozen = client.post(f"/internal/notification-outbox/{child['id']}/freeze", headers=OUTBOX_HEADERS,
                         json=dict(leaseToken=child['leaseToken'], envelope=envelope))
    assert frozen.status_code == 200
    assert frozen.json['envelope'] == envelope
    # Independent fixture connection: read the exact committed row, not the HTTP echo.
    assert db.query('SELECT envelope FROM public."EventNotificationOutbox" WHERE source_id=%s',
                    [envelope['id']]) == [(envelope,)]
    published = client.post(f"/internal/notification-outbox/{child['id']}/published", headers=OUTBOX_HEADERS,
                            json=dict(leaseToken=child['leaseToken']))
    assert published.status_code == 200
    decision = move(client, identifier, previous,
                    status='Safety Changes Requested' if trigger == 'resubmit' else 'Confirmed',
                    remarks='Revise the plan.' if trigger == 'resubmit' else 'Safe.',
                    **({'areas': ['event details']} if trigger == 'resubmit' else {}))
    assert decision.status_code == 200
    before = db.query('SELECT source_id,to_jsonb(o) FROM public."EventNotificationOutbox" o')
    previous_rows = {str(row[0]): row[1] for row in before}
    assert previous_rows[child['id']]['envelope'] == envelope
    assert previous_rows[child['id']]['published_at'] is not None
    # Act: a second round must not be suppressed by that saved first-round alert.
    before_round = db.query('SELECT clock_timestamp()')[0][0]
    if trigger == 'resubmit':
        response = move(client, identifier, next_round, number=2)
    else:
        response = client.patch(f'/events/{identifier}/details', headers=BUSINESS_HEADERS,
                                json=dict(coordinatorId=COORDINATOR,
                                          changes={'preferredStartDate': '2030-03-01T10:00'},
                                          safetyRecheck=dict(withdrawnSafetyCheckId=previous,
                                                             safetyCheckId=next_round, roundNumber=2)))
    assert response.status_code == 200
    assert response.json['status'] == 'Pending Safety Check'
    after_round = db.query('SELECT clock_timestamp()')[0][0]
    after = db.query('SELECT source_id,to_jsonb(o) FROM public."EventNotificationOutbox" o')
    saved = {str(row[0]): row[1] for row in after}
    assert {key: saved[key] for key in previous_rows} == previous_rows
    assert len(saved) == len(previous_rows) + 1
    jobs = [(row['type'], row['source']) for key, row in saved.items() if key not in previous_rows]
    assert len(jobs) == 1
    assert jobs[0][0] == 'safety.review-fanout'
    new_row = next(row for key, row in saved.items() if key not in previous_rows)
    created = datetime.fromisoformat(new_row['created_at'])
    assert created.utcoffset() is not None
    assert before_round <= created <= after_round
    assert jobs[0][1]['round'] == 2
    assert jobs[0][1]['eventName'] == 'Workshop'
    assert jobs[0][1]['startDateTime'] == ('2030-03-01T09:00:00+08:00' if trigger == 'resubmit'
                                          else '2030-03-01T10:00:00+08:00')


# AC2 ---- decision persistence/content (AC3 delivery retry; AC4 metadata)
@pytest.mark.parametrize('status,decision,reason,areas', [
    ('Confirmed', 'Approved', 'Safe with the agreed exit plan.', []),
    ('Confirmed', 'Approved', None, []),
    ('Cancelled', 'Rejected', 'Unsafe exits. ' * 99 + 'Unsafe exits.', []),
    ('Safety Changes Requested', 'Changes Requested', 'Revise the crowd and venue plans. ' * 29 + 'Revise the crowd and venue plans.',
     ['venue arrangement', 'event details']),
], ids=['approval-remarks', 'approval-no-remarks', 'rejection-full-reason', 'changes-reason-distinct-areas'])
def test_ac2_decision_saves_the_locked_coordinator_and_complete_content(safety_notification_owner, status, decision, reason, areas):
    """Normal: AC2/AC4: each decision captures the coordinator and full supplied content, then freezes."""
    client, db = safety_notification_owner
    round_id = str(uuid4())
    identifier = make_safety_event(db, 'Pending Safety Check', [dict(status='Pending Safety Check', safetyCheckId=round_id)])
    extra = dict(remarks=reason)
    if areas:
        extra['areas'] = areas
    before = db.query('SELECT clock_timestamp()')[0][0]
    response = move(client, identifier, round_id, status=status, **extra)
    after = db.query('SELECT clock_timestamp()')[0][0]
    assert response.status_code == 200
    job = claim(client)
    created = datetime.fromisoformat(job['createdAt'])
    assert created.utcoffset() is not None
    assert before <= created <= after
    assert job['type'] == 'safety.review-decision'
    assert job['source'] == dict(eventId=identifier, eventName='Workshop', recipientId=COORDINATOR,
                                round=1, decision=decision, reason=reason, areas=areas)
    message = f'Workshop safety review: {decision} (round 1).'
    if reason:
        message += f' {reason}'
    if areas:
        message += ' Affected areas: venue arrangement, event details.'
    envelope = dict(version=1, id=job['id'], type=job['type'], recipientId=COORDINATOR,
                    createdAt=job['createdAt'], details=job['source'],
                    destination=dict(kind='event-details', eventId=identifier), message=message)
    frozen = client.post(f"/internal/notification-outbox/{job['id']}/freeze", headers=OUTBOX_HEADERS,
                         json=dict(leaseToken=job['leaseToken'], envelope=envelope))
    assert frozen.status_code == 200
    assert frozen.json['envelope'] == envelope
    # Independent fixture connection: read the exact committed row, not the HTTP echo.
    assert db.query('SELECT envelope FROM public."EventNotificationOutbox" WHERE source_id=%s',
                    [envelope['id']]) == [(envelope,)]
    assert db.query('SELECT status FROM public."Event" WHERE event_id=%s', [identifier]) == [(status,)]
    # AC3: a later delivery retry cannot roll back a committed business decision.
    if reason == 'Safe with the agreed exit plan.':
        retry = client.post(f"/internal/notification-outbox/{job['id']}/retry", headers=OUTBOX_HEADERS,
                            json=dict(leaseToken=job['leaseToken'], error='BrokerUnavailable'))
        assert retry.status_code == 200
        assert db.query('SELECT status FROM public."Event" WHERE event_id=%s', [identifier]) == [('Confirmed',)]
        # Existing retry policy schedules attempt 1 two seconds later; do not rewrite SQL state.
        deadline = time.monotonic() + 10
        while True:
            response = client.post('/internal/notification-outbox/claim', json={}, headers=OUTBOX_HEADERS)
            assert response.status_code == 200
            if response.json['jobs']:
                reclaimed = response.json['jobs'][0]
                break
            assert time.monotonic() < deadline, 'Retry never became publicly claimable within 10 seconds'
            Event().wait(min(0.1, max(0, deadline - time.monotonic())))
        assert reclaimed['id'] == job['id']
        assert reclaimed['envelope'] == envelope


# Supporting DR ---- atomic initial intent-save failure, NOT AC3 delivery failure
def test_ac3_initial_intent_save_failure_is_not_a_successful_decision(safety_notification_owner):
    """Failure: supporting DR: an unsaved initial intent rolls back the decision, not later delivery."""
    client, db = safety_notification_owner
    round_id = str(uuid4())
    identifier = make_safety_event(db, 'Pending Safety Check', [dict(status='Pending Safety Check', safetyCheckId=round_id)])
    before = db.query('SELECT to_jsonb(e) FROM public."Event" e WHERE event_id=%s', [identifier])
    db.query('''ALTER TABLE public."EventNotificationOutbox" ADD CONSTRAINT synthetic_safety_failure
                CHECK (type <> 'safety.review-decision')''')
    response = move(client, identifier, round_id, status='Confirmed', remarks='Safe.')
    assert response.status_code == 503
    assert db.query('SELECT to_jsonb(e) FROM public."Event" e WHERE event_id=%s', [identifier]) == before
    assert db.query('SELECT * FROM public."EventNotificationOutbox"') == []

