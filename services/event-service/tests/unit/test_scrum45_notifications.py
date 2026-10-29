"""SCRUM-45 Event Organiser Status and Update Notifications: event-service unit tests.

Story: As an Event Organiser, I want to receive an in-app notification when the Lead Coordinator approves or rejects my event request, so that I know the outcome and who is responsible for coordinating my event.
Real: own Flask routes, validation, mutation/outbox logic and SQL construction.
Doubled: PostgreSQL connection/cursor. Event makes no HTTP or broker calls.
Not proven: production authentication, hosted Supabase, cross-service delivery or browser navigation.
Owned: transactionally saved historical intent, mutation guards and owner freeze/lease APIs. Not covered here: coordinator name lookup (Workflow), inbox delivery (Notification), UI/E2E.
AC = acceptance criterion; DR = supporting design rule, not an extra AC.

AC1 A successfully recorded approval sends an in-app approval notification to the submitting Event Organiser.
  Owned: SQL insertion and approval guards only; actual commit and delivery belong to integration/Workflow/Notification.
AC2 A successfully recorded rejection sends an in-app rejection notification to the submitting Event Organiser, including the rejection reason.
  Owned: SQL insertion of rejection facts/reason only; actual commit and inbox delivery are outside this unit boundary.
AC3 Both decision notifications include event name, decision, and a link to the event request and its decision details.
  Owned: Saved decision facts and freeze UPDATE/response contract; real persistence and linked-page rendering are not proven.
AC4 A successfully recorded initial assignment or reassignment sends the submitting Event Organiser an in-app notification with event name, newly assigned coordinator name, and an event-details link.
  Owned: Initial/replacement coordinator IDs and named freeze contract; User name lookup and inbox delivery are outside Event.
"""
from datetime import UTC, datetime

from unittest.mock import MagicMock, patch

import pytest

from app import create_app

from app.models import FIELDS
from tests.unit.factories import signed_in

approval_EVENT = '30000000-0000-0000-0000-000000000001'

approval_ACTOR = '10000000-0000-0000-0000-000000000002'

approval_ORGANISER = '10000000-0000-0000-0000-000000000001'

def approval_row(status='Under Review', organiser=approval_ORGANISER):
    """Build a synthetic database row with the requested approval status and organiser."""
    result = {column: '' for column in FIELDS.values()}
    result.update(event_id=approval_EVENT, event_name='Community Workshop', status=status, coordinator_id=approval_ACTOR, organiser_id=organiser, submission_date=datetime(2026, 10, 1, tzinfo=UTC), preferred_start_date=None, preferred_end_date=None, expected_attendance=30, description='Workshop')
    return result

@pytest.fixture
def boundary():
    """Yield the Flask client, mocked connection and cursor so tests can inspect SQL and
    transaction exit.
    """
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    with patch('psycopg2.connect', return_value=connection):
        client = signed_in(create_app({'TESTING': True, 'DATABASE_URL': 'synthetic', 'INTERNAL_SERVICE_TOKEN': 'test-token'}).test_client())
        yield (client, connection, cursor)

def approval_approve(client, route, actor=approval_ACTOR):
    """Send approval through the dedicated or progress route and return the HTTP response."""
    body = {'coordinatorId': actor}
    if route == 'progress':
        body.update(status='Approved', actionDetails='Ready for approval')
    return client.patch(f'/events/{approval_EVENT}/{route}', json=body)

approval_JOB_ID = '20000000-0000-0000-0000-000000000001'

approval_LEASE = '40000000-0000-0000-0000-000000000001'

approval_HEADERS = {'X-Internal-Token': 'test-token'}

approval_SOURCE = {'eventId': approval_EVENT, 'eventName': 'Community Workshop', 'recipientId': approval_ORGANISER, 'decision': 'Approved'}

approval_ENVELOPE = dict(version=1, id=approval_JOB_ID, recipientId=approval_ORGANISER, type='event.approval', createdAt='2026-10-21T00:00:00+00:00', message='Community Workshop was approved', destination=dict(kind='event-details', eventId=approval_EVENT), details=approval_SOURCE)

initial_assignment_EVENT = '30000000-0000-0000-0000-000000000001'

initial_assignment_COORDINATOR = '10000000-0000-0000-0000-000000000002'

initial_assignment_ORGANISER = '10000000-0000-0000-0000-000000000001'

initial_assignment_LEAD = '10000000-0000-0000-0000-000000000003'

def initial_assignment_assigned_row(organiser=initial_assignment_ORGANISER):
    """Build the database row returned after initial assignment, optionally without an organiser."""
    result = {column: '' for column in FIELDS.values()}
    result.update(event_id=initial_assignment_EVENT, event_name='Community Workshop', status='Under Review', coordinator_id=initial_assignment_COORDINATOR, organiser_id=organiser, submission_date=datetime(2026, 10, 1, tzinfo=UTC), preferred_start_date=None, preferred_end_date=None, expected_attendance=30, description='Workshop')
    return result

def initial_assignment_assign(client):
    """Send the initial assignment to Event's mutation route and return its response; no Lead
    orchestration runs.
    """
    return client.patch(f'/events/{initial_assignment_EVENT}', json={'assignedCoordinatorId': initial_assignment_COORDINATOR, 'assignedBy': initial_assignment_LEAD})

def initial_assignment_intents(cursor):
    """Extract outbox INSERT parameters from cursor calls; these are write requests, not persisted
    rows.
    """
    # SCRUM-45 observes organiser deliveries; SCRUM-166 owns coordinator deliveries.
    return [call.args[1] for call in cursor.execute.call_args_list
            if 'INSERT INTO public."EventNotificationOutbox"' in call.args[0]
            and call.args[1][1] == 'event.coordinator-assignment']

initial_assignment_JOB_ID = '20000000-0000-0000-0000-000000000001'

initial_assignment_LEASE = '40000000-0000-0000-0000-000000000001'

initial_assignment_HEADERS = {'X-Internal-Token': 'test-token'}

initial_assignment_SOURCE = dict(eventId=initial_assignment_EVENT, eventName='Community Workshop', recipientId=initial_assignment_ORGANISER, coordinatorId=initial_assignment_COORDINATOR)

def initial_assignment_pending():
    """Build a claimed assignment row with saved source facts and an active synthetic lease."""
    return dict(source_id=initial_assignment_JOB_ID, source=initial_assignment_SOURCE, type='event.coordinator-assignment', envelope=None, attempts=1, lease_token=initial_assignment_LEASE, lease_valid=True, created_at=datetime(2026, 10, 21, tzinfo=UTC))

reassignment_EVENT = '30000000-0000-0000-0000-000000000001'

reassignment_ORGANISER = '10000000-0000-0000-0000-000000000001'

reassignment_ALICE = '10000000-0000-0000-0000-000000000002'

reassignment_BOB = '10000000-0000-0000-0000-000000000003'

def reassignment_row(coordinator, organiser: str | None=reassignment_ORGANISER):
    """Build a returned Event row for the supplied coordinator and optional organiser."""
    result: dict[str, object] = {column: '' for column in FIELDS.values()}
    result.update(event_id=reassignment_EVENT, event_name='Community Workshop', status='Under Review', coordinator_id=coordinator, organiser_id=organiser, submission_date=datetime(2026, 10, 1, tzinfo=UTC), preferred_start_date=None, preferred_end_date=None, expected_attendance=30, description='Workshop')
    return result

def reassignment_assign(client, coordinator):
    """Send a replacement coordinator to Event's mutation route and return its response;
    caller-role lookup is outside this scope.
    """
    return client.patch(f'/events/{reassignment_EVENT}', json={'assignedCoordinatorId': coordinator, 'assignedBy': reassignment_ORGANISER})

def reassignment_intents(cursor):
    """Extract outbox INSERT parameters so reassignment tests can inspect saved identity or absence
    of work.
    """
    # SCRUM-45 observes organiser deliveries; SCRUM-166 owns coordinator deliveries.
    return [call.args[1] for call in cursor.execute.call_args_list
            if 'INSERT INTO public."EventNotificationOutbox"' in call.args[0]
            and call.args[1][1] == 'event.coordinator-assignment']

rejection_EVENT = '30000000-0000-0000-0000-000000000001'

rejection_ACTOR = '10000000-0000-0000-0000-000000000002'

rejection_ORGANISER = '10000000-0000-0000-0000-000000000001'

rejection_REASON = 'The proposal does not meet the event requirements.'

def rejection_row(status='Under Review', organiser=rejection_ORGANISER):
    """Build a synthetic database row with the requested rejection status and organiser."""
    result = {column: '' for column in FIELDS.values()}
    result.update(event_id=rejection_EVENT, event_name='Community Workshop', status=status, coordinator_id=rejection_ACTOR, organiser_id=organiser, submission_date=datetime(2026, 10, 1, tzinfo=UTC), preferred_start_date=None, preferred_end_date=None, expected_attendance=30, description='Workshop')
    return result

def rejection_reject(client, route):
    """Send the same rejection reason through either supported route and return the HTTP response."""
    body = {'coordinatorId': rejection_ACTOR}
    body.update({'reason': rejection_REASON} if route == 'reject' else {'status': 'Rejected', 'actionDetails': rejection_REASON})
    return client.patch(f'/events/{rejection_EVENT}/{route}', json=body)

rejection_HEADERS = {'X-Internal-Token': 'test-token'}

rejection_SOURCE = {'eventId': rejection_EVENT, 'eventName': 'Community Workshop', 'recipientId': rejection_ORGANISER, 'decision': 'Rejected', 'reason': rejection_REASON}

rejection_JOB_ID = '20000000-0000-0000-0000-000000000001'

rejection_LEASE = '40000000-0000-0000-0000-000000000001'


# AC1 — Approval

@pytest.mark.parametrize('route', ['approve', 'progress'])
def test_ac1_approval_records_saved_organiser_and_event_facts(boundary, route):
    """Normal: approve through either route; SQL captures the original organiser and event name
    despite changed UPDATE results, preserving who and what the decision concerned.
    """
    client, connection, cursor = boundary
    updated = {**approval_row('Approved'), 'event_name': 'Renamed', 'organiser_id': approval_ACTOR}
    cursor.fetchone.side_effect = [approval_row(), updated]
    assert approval_approve(client, route).status_code == 200
    inserts = [call.args[1] for call in cursor.execute.call_args_list if 'INSERT INTO public."EventNotificationOutbox"' in call.args[0]]
    assert len(inserts) == 1, 'Successful approval must save notification intent'
    assert inserts[0][1] == 'event.approval'
    assert inserts[0][-1].adapted == {'eventId': approval_EVENT, 'eventName': 'Community Workshop', 'recipientId': approval_ORGANISER, 'decision': 'Approved'}
    assert connection.__exit__.call_args.args[0] is None


# AC2 — Rejection and reason

@pytest.mark.parametrize('route', ['reject', 'progress'])
def test_ac2_rejection_records_notification_with_reason(boundary, route):
    """Normal: reject through either route; one outbox INSERT includes the exact reason and
    submitting organiser, so a recorded rejection has notification work in the same transaction.
    """
    client, connection, cursor = boundary
    cursor.fetchone.side_effect = [rejection_row(), rejection_row('Rejected')]
    response = rejection_reject(client, route)
    assert response.status_code == 200
    # SCRUM-45 owns the organiser alert; SCRUM-49 separately verifies both recipients.
    inserts = [call.args[1] for call in cursor.execute.call_args_list
               if 'INSERT INTO public."EventNotificationOutbox"' in call.args[0]
               and call.args[1][-1].adapted["recipientId"] == rejection_ORGANISER]
    assert len(inserts) == 1, 'Successful rejection must save exactly one organiser intent'
    source = inserts[0][-1].adapted
    assert source == {'eventId': rejection_EVENT, 'eventName': 'Community Workshop', 'recipientId': rejection_ORGANISER, 'decision': 'Rejected', 'reason': rejection_REASON}
    assert connection.__exit__.call_args.args[0] is None


@pytest.mark.parametrize('reason', ['x' * 40000, '界' * 18000, ('"\\\n' * 10000)],
                         ids=['ascii', 'multibyte', 'escaped'])
def test_ac2_large_accepted_reason_can_cross_freeze_boundary(boundary, reason):
    """Boundary: reject with long ASCII, Unicode or escaped text, then freeze its larger envelope;
    the response preserves every character so an accepted reason does not become undeliverable.
    """
    import json
    client, _, cursor = boundary
    # HTTPX uses compact UTF-8 JSON, not Flask's default ASCII-escaped serializer.
    encode = lambda value: json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
    reason = "x" + reason + "x"
    body = encode(dict(coordinatorId=rejection_ACTOR, reason=reason))
    assert len(body) <= 65536
    cursor.fetchone.side_effect = [{**rejection_row(), 'event_name': '😀' * 255},
                                 {**rejection_row('Rejected'), 'event_name': '😀' * 255}]
    assert client.patch(f'/events/{rejection_EVENT}/reject', data=body,
                        content_type='application/json').status_code == 200
    source = {**rejection_SOURCE, 'reason': reason, 'eventName': '😀' * 255}
    pending = dict(source_id=rejection_JOB_ID, source=source, type='event.rejection', envelope=None,
                   attempts=1, lease_token=rejection_LEASE, lease_valid=True,
                   created_at=datetime(2026, 10, 21, tzinfo=UTC))
    envelope = dict(version=1, id=rejection_JOB_ID, type='event.rejection',
                    recipientId=rejection_ORGANISER, createdAt=pending['created_at'].isoformat(),
                    message=f"{source['eventName']} was rejected: {reason}", details=source,
                    destination=dict(kind='event-details', eventId=rejection_EVENT))
    # Act: freeze the larger delivery envelope after the public rejection was accepted.
    cursor.fetchone.side_effect = [pending, {**pending, 'envelope': envelope}]
    freeze = encode(dict(leaseToken=rejection_LEASE, envelope=envelope))
    assert len(freeze) > 65536
    response = client.post(f'/internal/notification-outbox/{rejection_JOB_ID}/freeze',
                           headers=rejection_HEADERS, data=freeze, content_type='application/json')
    assert response.status_code == 200
    assert response.json['envelope'] == envelope


@pytest.mark.parametrize('action,size,headers,expected', [
    ('freeze', 135168, rejection_HEADERS, 400),
    ('freeze', 135169, rejection_HEADERS, 413),
    ('retry', 65537, rejection_HEADERS, 413),
    ('hold', 65537, rejection_HEADERS, 413),
    ('published', 65537, rejection_HEADERS, 413),
    ('freeze', 135168, {}, 401),
    ('freeze', 135168, {'X-Internal-Token': 'wrong'}, 401),
])
def test_ac2_dr_freeze_allowance_is_bounded_and_authenticated(boundary, action, size, headers, expected):
    """Failure: submit unauthorised, malformed or oversized outbox requests; the expected HTTP
    error occurs without SQL, keeping the larger freeze allowance bounded and private.
    """
    client, connection, cursor = boundary
    response = client.post(f'/internal/notification-outbox/{rejection_JOB_ID}/{action}',
                           headers=headers, data=b' ' * size, content_type='application/json')
    assert response.status_code == expected
    cursor.execute.assert_not_called()
    assert client.application.config['MAX_CONTENT_LENGTH'] == 65536


@pytest.mark.parametrize('size,expected', [(65536, 400), (65537, 413)])
def test_ac2_dr_public_rejection_limit_does_not_change(boundary, size, expected):
    """Boundary: send invalid JSON at and just above the public size limit; parser and size errors
    differ without SQL, so the internal freeze allowance does not enlarge public requests.
    """
    client, _, cursor = boundary
    response = client.patch(f'/events/{rejection_EVENT}/reject', data=b' ' * size,
                            content_type='application/json')
    assert response.status_code == expected
    cursor.execute.assert_not_called()


# AC3 — Decision content and link

def test_ac3_approval_envelope_can_be_frozen_and_read_back(boundary):
    """Normal: freeze a valid approval through the owner API; inspect the envelope UPDATE and
    returned content so accepting a request alone cannot masquerade as saving it.
    """
    client, _, cursor = boundary
    pending = dict(source_id=approval_JOB_ID, source=approval_SOURCE, type='event.approval', envelope=None, attempts=1, lease_token=approval_LEASE, lease_valid=True, created_at=datetime(2026, 10, 21, tzinfo=UTC))
    client.application.config['PROPAGATE_EXCEPTIONS'] = False
    cursor.fetchone.side_effect = [pending, {**pending, 'envelope': approval_ENVELOPE}]
    result = client.post(f'/internal/notification-outbox/{approval_JOB_ID}/freeze', headers=approval_HEADERS, json={'leaseToken': approval_LEASE, 'envelope': approval_ENVELOPE})
    assert result.status_code == 200
    assert result.json['envelope'] == approval_ENVELOPE
    writes = [call.args for call in cursor.execute.call_args_list if call.args[0].lstrip().startswith('UPDATE public."EventNotificationOutbox" SET envelope=')]
    assert len(writes) == 1, 'Freeze must persist, not merely return a configured read fixture'
    assert writes[0][1][0].adapted == approval_ENVELOPE
    assert writes[0][1][1] == approval_JOB_ID


# AC4 — Initial assignment and reassignment

def test_ac4_initial_assignment_saves_historical_notification_on_same_transaction(boundary):
    """Normal: assign an unassigned event; one outbox INSERT contains the coordinator ID, event
    name and submitting organiser before normal transaction exit, preserving the initial change.
    """
    client, connection, cursor = boundary
    cursor.fetchone.side_effect = [dict(coordinator_id=None, status='Submitted'), initial_assignment_assigned_row()]
    response = initial_assignment_assign(client)
    assert response.status_code == 200, response.json
    saved = initial_assignment_intents(cursor)
    assert len(saved) == 1, 'Initial assignment must persist notification intent'
    assert saved[0][1] == 'event.coordinator-assignment'
    assert saved[0][2].adapted == dict(eventId=initial_assignment_EVENT, eventName='Community Workshop', recipientId=initial_assignment_ORGANISER, coordinatorId=initial_assignment_COORDINATOR)
    assert connection.__exit__.call_args.args[0] is None

def test_ac4_claim_exposes_assignment_type_and_freeze_accepts_named_saved_identity(boundary):
    """Normal: claim assignment work and freeze a named envelope; inspect its type, UPDATE and
    response so the owner accepts content tied to the saved coordinator, not a later assignment.
    """
    client, _, cursor = boundary
    cursor.fetchall.return_value = [initial_assignment_pending()]
    job = client.post('/internal/notification-outbox/claim', headers=initial_assignment_HEADERS, json={}).json['jobs'][0]
    assert job.get('type') == 'event.coordinator-assignment'
    envelope = dict(version=1, id=initial_assignment_JOB_ID, type='event.coordinator-assignment', recipientId=initial_assignment_ORGANISER, createdAt=job['createdAt'], message='Alice Tan has been assigned to coordinate Community Workshop.', destination=dict(kind='event-details', eventId=initial_assignment_EVENT), details={**initial_assignment_SOURCE, 'coordinatorName': 'Alice Tan'})
    cursor.fetchone.side_effect = [initial_assignment_pending(), {**initial_assignment_pending(), 'envelope': envelope}]
    result = client.post(f'/internal/notification-outbox/{initial_assignment_JOB_ID}/freeze', headers=initial_assignment_HEADERS, json=dict(leaseToken=initial_assignment_LEASE, envelope=envelope))
    assert result.status_code == 200
    assert result.json['envelope'] == envelope
    writes = [call.args for call in cursor.execute.call_args_list if call.args[0].lstrip().startswith('UPDATE public."EventNotificationOutbox" SET envelope=')]
    assert len(writes) == 1, 'Freeze must persist, not merely return a configured read fixture'
    assert writes[0][1][0].adapted == envelope
    assert writes[0][1][1] == initial_assignment_JOB_ID

def test_ac4_reassignment_records_replacement_coordinator_for_submitting_organiser(boundary):
    """Normal: replace Alice with Bob through Event HTTP; one outbox INSERT names Bob's saved ID
    and the submitting organiser, keeping reassignment distinct from the previous coordinator.
    """
    client, connection, cursor = boundary
    cursor.fetchone.side_effect = [dict(coordinator_id=reassignment_ALICE, status='Under Review'), reassignment_row(reassignment_BOB)]
    response = reassignment_assign(client, reassignment_BOB)
    assert response.status_code == 200, response.json
    saved = reassignment_intents(cursor)
    assert len(saved) == 1, 'A successful reassignment must save notification work'
    assert saved[0][1] == 'event.coordinator-assignment'
    assert saved[0][2].adapted == dict(eventId=reassignment_EVENT, eventName='Community Workshop', recipientId=reassignment_ORGANISER, coordinatorId=reassignment_BOB)
    assert connection.__exit__.call_args.args[0] is None

@pytest.mark.parametrize('details', [None, {}, {**initial_assignment_SOURCE, 'coordinatorName': ' '}, {**initial_assignment_SOURCE, 'coordinatorName': 12}, {**initial_assignment_SOURCE, 'coordinatorName': 'Alice', 'coordinatorId': initial_assignment_ORGANISER}])
def test_ac4_freeze_refuses_nameless_or_substituted_assignment_identity(boundary, details):
    """Failure: AC4/DR4: owning freeze HTTP rejects missing name or substituted saved ID; malformed preparation must not overwrite the historical change."""
    client, _, cursor = boundary
    cursor.fetchone.return_value = initial_assignment_pending()
    envelope = dict(version=1, id=initial_assignment_JOB_ID, type='event.coordinator-assignment', recipientId=initial_assignment_ORGANISER, createdAt='2026-10-21T00:00:00+00:00', message='Alice has been assigned to coordinate Community Workshop.', destination=dict(kind='event-details', eventId=initial_assignment_EVENT), details=details)
    result = client.post(f'/internal/notification-outbox/{initial_assignment_JOB_ID}/freeze', headers=initial_assignment_HEADERS, json=dict(leaseToken=initial_assignment_LEASE, envelope=envelope))
    assert result.status_code == 400
    assert cursor.execute.call_count == 1


# Supporting DR2/DR3/DR4/DR5/DR6/DR8 — transaction, recovery, history and identity

def test_ac4_dr_name_hold_releases_lease_and_excludes_held_work_from_claims(boundary):
    """Normal: DR6: owning HTTP hold records durable diagnosis without retry schedule; claim boundary excludes held jobs so unrelated work remains eligible."""
    client, _, cursor = boundary
    cursor.fetchone.return_value = initial_assignment_pending()
    response = client.post(f'/internal/notification-outbox/{initial_assignment_JOB_ID}/hold', headers=initial_assignment_HEADERS, json=dict(leaseToken=initial_assignment_LEASE, error=f'CoordinatorNameUnavailable coordinatorId={initial_assignment_COORDINATOR}'))
    assert response.status_code == 200
    writes = [call for call in cursor.execute.call_args_list if call.args[0].startswith('UPDATE')]
    assert len(writes) == 1
    assert 'held_at=now()' in writes[0].args[0]
    assert 'lease_until=NULL,lease_token=NULL' in writes[0].args[0]
    assert writes[0].args[1] == (f'CoordinatorNameUnavailable coordinatorId={initial_assignment_COORDINATOR}', initial_assignment_JOB_ID)
    cursor.fetchall.return_value = []
    assert client.post('/internal/notification-outbox/claim', headers=initial_assignment_HEADERS, json={}).json == {'jobs': []}
    assert 'held_at IS NULL' in cursor.execute.call_args.args[0]

def test_ac4_dr_held_work_can_be_inspected_and_released_after_name_repair(boundary):
    """Normal: DR6: authenticated operator reads held source/diagnosis and explicitly releases it for retry after repairing User data; no event rewrite needed."""
    client, _, cursor = boundary
    held_at = datetime(2026, 10, 21, tzinfo=UTC)
    cursor.fetchall.return_value = [{**initial_assignment_pending(), 'held_at': held_at, 'last_error': 'CoordinatorNameUnavailable'}]
    response = client.get('/internal/notification-outbox/held', headers=initial_assignment_HEADERS)
    assert response.status_code == 200
    assert response.json['jobs'] == [dict(id=initial_assignment_JOB_ID, source=initial_assignment_SOURCE, error='CoordinatorNameUnavailable', heldAt=held_at.isoformat())]
    cursor.fetchone.return_value = {'source_id': initial_assignment_JOB_ID}
    release = client.post(f'/internal/notification-outbox/{initial_assignment_JOB_ID}/release', headers=initial_assignment_HEADERS, json={})
    assert release.status_code == 200
    assert release.json == {'id': initial_assignment_JOB_ID, 'status': 'released'}
    assert 'held_at IS NOT NULL' in cursor.execute.call_args.args[0]
    assert 'held_at=NULL' in cursor.execute.call_args.args[0]
    assert 'available_at=now()' in cursor.execute.call_args.args[0]

@pytest.mark.parametrize('action', ['hold', 'release'])
def test_ac4_dr_hold_and_repair_require_internal_authentication(boundary, action):
    """Failure: call hold, release and held-work listing without a token; every request returns 401
    before opening a cursor, so outsiders cannot hide or requeue notifications.
    """
    client, connection, _ = boundary
    assert client.post(f'/internal/notification-outbox/{initial_assignment_JOB_ID}/{action}', json={}).status_code == 401
    assert client.get('/internal/notification-outbox/held').status_code == 401
    connection.cursor.assert_not_called()

def test_ac2_dr_pending_rejection_can_be_claimed_frozen_and_completed(boundary):
    """Normal: claim, freeze and complete rejection work through authenticated HTTP; inspect the
    saved-envelope UPDATE and published response to check the worker-facing lifecycle contract,
    not actual delivery.
    """
    client, _, cursor = boundary
    pending = dict(source_id=rejection_JOB_ID, source=rejection_SOURCE, type='event.rejection', envelope=None, attempts=1, lease_token=rejection_LEASE, lease_valid=True, created_at=datetime(2026, 10, 21, tzinfo=UTC))
    cursor.fetchall.return_value = [pending]
    claim = client.post('/internal/notification-outbox/claim', json={}, headers=rejection_HEADERS)
    assert claim.status_code == 200, 'Event must expose durable pending work to its worker'
    assert claim.json['jobs'][0]['source'] == rejection_SOURCE
    envelope = dict(version=1, id=rejection_JOB_ID, recipientId=rejection_ORGANISER, type='event.rejection', createdAt='2026-10-21T00:00:00+00:00', message=f'Community Workshop was rejected: {rejection_REASON}', destination=dict(kind='event-details', eventId=rejection_EVENT), details=rejection_SOURCE)
    frozen = {**pending, 'envelope': envelope}
    cursor.fetchone.side_effect = [pending, frozen, frozen]
    freeze = client.post(f'/internal/notification-outbox/{rejection_JOB_ID}/freeze', json={'leaseToken': rejection_LEASE, 'envelope': envelope}, headers=rejection_HEADERS)
    assert freeze.status_code == 200
    assert freeze.json['envelope'] == envelope
    writes = [call.args for call in cursor.execute.call_args_list if call.args[0].lstrip().startswith('UPDATE public."EventNotificationOutbox" SET envelope=')]
    assert len(writes) == 1, 'Freeze must persist, not merely return a configured read fixture'
    assert writes[0][1][0].adapted == envelope
    assert writes[0][1][1] == rejection_JOB_ID
    complete = client.post(f'/internal/notification-outbox/{rejection_JOB_ID}/published', json={'leaseToken': rejection_LEASE}, headers=rejection_HEADERS)
    assert complete.status_code == 200
    assert complete.json['status'] == 'published'

@pytest.mark.parametrize('route', ['approve', 'progress'])
def test_ac1_dr_ownerless_approval_is_diagnosed_without_guessing_recipient(boundary, route, caplog):
    """Boundary: approve a legacy event without an organiser; the request succeeds with a
    missing-owner diagnostic and no outbox INSERT, avoiding a guessed recipient.
    """
    client, _, cursor = boundary
    cursor.fetchone.side_effect = [approval_row(organiser=None), approval_row('Approved', organiser=None)]
    assert approval_approve(client, route).status_code == 200
    assert 'missing organiser' in caplog.text
    assert not any(('INSERT INTO public."EventNotificationOutbox"' in call.args[0] for call in cursor.execute.call_args_list))

def test_ac4_dr_ownerless_legacy_reassignment_is_diagnosed_without_recipient_guess(boundary, caplog):
    """Boundary: DR5: ownerless legacy reassignment still succeeds, records diagnosis and creates no publishable work or guessed recipient."""
    client, _, cursor = boundary
    cursor.fetchone.side_effect = [dict(coordinator_id=reassignment_ALICE, status='Under Review'), reassignment_row(reassignment_BOB, None)]
    assert reassignment_assign(client, reassignment_BOB).status_code == 200
    assert 'missing organiser' in caplog.text
    assert reassignment_intents(cursor) == []

@pytest.mark.parametrize('route', ['reject', 'progress'])
def test_ac2_dr_legacy_event_without_organiser_is_diagnosed_without_delivery(boundary, route, caplog):
    """Boundary: DR5: an ownerless rejection is diagnosed without guessing an organiser; its assigned coordinator still receives confirmation."""
    client, _, cursor = boundary
    cursor.fetchone.side_effect = [rejection_row(organiser=None), rejection_row('Rejected', organiser=None)]
    assert rejection_reject(client, route).status_code == 200
    assert 'missing organiser' in caplog.text
    inserts = [call.args[1] for call in cursor.execute.call_args_list
               if 'INSERT INTO public."EventNotificationOutbox"' in call.args[0]]
    assert len(inserts) == 1
    assert inserts[0][1] == "event.rejection"
    assert inserts[0][-1].adapted == dict(eventId=rejection_EVENT, eventName="Community Workshop",
        recipientId=rejection_ACTOR, decision="Rejected", reason=rejection_REASON)

@pytest.mark.parametrize('route', ['approve', 'progress'])
def test_ac1_dr_repeated_approval_does_not_notify_again(boundary, route):
    """Conflict: repeat approval through either route; conflict or unchanged progress creates no
    outbox INSERT, preventing duplicate notification work for the same decision.
    """
    client, _, cursor = boundary
    cursor.fetchone.side_effect = [approval_row('Approved'), approval_row('Approved')]
    assert approval_approve(client, route).status_code == (409 if route == 'approve' else 200)
    assert not any(('INSERT INTO public."EventNotificationOutbox"' in call.args[0] for call in cursor.execute.call_args_list))

@pytest.mark.parametrize('current,status,code', [(initial_assignment_COORDINATOR, 'Under Review', 409), (None, 'Rejected', 409)])
def test_ac4_dr_failed_or_unchanged_assignment_has_no_intent(boundary, current, status, code):
    """Conflict: assign the current coordinator or assign a rejected event; HTTP 409 and no outbox
    INSERT prevent failed or unchanged actions from notifying the organiser.
    """
    client, _, cursor = boundary
    cursor.fetchone.return_value = dict(coordinator_id=current, status=status)
    assert initial_assignment_assign(client).status_code == code
    assert initial_assignment_intents(cursor) == []

@pytest.mark.parametrize('current,status', [(reassignment_BOB, 'Under Review'), (reassignment_ALICE, 'Rejected'), (reassignment_ALICE, 'Cancelled'), (reassignment_ALICE, 'Clarification Requested')])
def test_ac4_dr_unchanged_or_closed_reassignment_creates_no_notification(boundary, current, status):
    """Conflict: reassign to the same person or from a disallowed status; HTTP 409 and no outbox
    INSERT prevent notifications for changes that never happened.
    """
    client, _, cursor = boundary
    cursor.fetchone.return_value = dict(coordinator_id=current, status=status)
    assert reassignment_assign(client, reassignment_BOB).status_code == 409
    assert reassignment_intents(cursor) == []

@pytest.mark.parametrize('route', ['reject', 'progress'])
def test_ac2_dr_repeated_rejection_does_not_create_more_intent(boundary, route):
    """Conflict: DR2: repeat already rejected request at HTTP boundary; observe no new intent on conflict or unchanged-status progress update."""
    client, _, cursor = boundary
    cursor.fetchone.side_effect = [rejection_row('Rejected'), rejection_row('Rejected')]
    assert rejection_reject(client, route).status_code == (409 if route == 'reject' else 200)
    assert not any(('INSERT INTO public."EventNotificationOutbox"' in call.args[0] for call in cursor.execute.call_args_list))

def test_ac2_dr_second_freeze_reads_back_first_frozen_content(boundary):
    """Conflict: freeze an already frozen job with different content; the response returns the
    first envelope without an UPDATE, keeping retry history immutable.
    """
    client, _, cursor = boundary
    cursor.fetchone.return_value = dict(source_id=rejection_JOB_ID, source=rejection_SOURCE, envelope={'first': True}, lease_token=rejection_LEASE, lease_valid=True, attempts=2, created_at=datetime(2026, 10, 21, tzinfo=UTC))
    result = client.post(f'/internal/notification-outbox/{rejection_JOB_ID}/freeze', headers=rejection_HEADERS, json={'leaseToken': rejection_LEASE, 'envelope': {'second': True}})
    assert result.json['envelope'] == {'first': True}
    assert cursor.execute.call_count == 1

@pytest.mark.parametrize('route', ['approve', 'progress'])
def test_ac1_dr_approval_storage_failure_aborts_decision_transaction(boundary, route):
    """Failure: make the approval intent INSERT raise a database error; HTTP 503 and exceptional
    transaction exit require the rollback contract, rather than reporting a decision without
    notification work.
    """
    import psycopg2
    client, connection, cursor = boundary
    cursor.fetchone.side_effect = [approval_row(), approval_row('Approved')]

    def execute(sql, params):
        if 'INSERT INTO public."EventNotificationOutbox"' in sql:
            raise psycopg2.OperationalError('isolated intent failure')
    cursor.execute.side_effect = execute
    assert approval_approve(client, route).status_code == 503
    assert connection.__exit__.call_args.args[0] is psycopg2.OperationalError

@pytest.mark.parametrize('route', ['approve', 'progress'])
def test_ac1_dr_unassigned_actor_cannot_approve_or_notify(boundary, route):
    """Failure: approve as someone other than the assigned coordinator; HTTP 403 after only the
    lookup prevents an unauthorised decision or notification INSERT.
    """
    client, _, cursor = boundary
    cursor.fetchone.return_value = approval_row()
    assert approval_approve(client, route, approval_ORGANISER).status_code == 403
    assert cursor.execute.call_count == 1

@pytest.mark.parametrize('change', [{'recipientId': approval_ACTOR}, {'type': 'event.rejection'}, {'message': 'Community Workshop was rejected'}, {'details': {**approval_SOURCE, 'eventName': 'Renamed'}}, {'destination': {'kind': 'event-details', 'eventId': approval_ORGANISER}}, {'createdAt': '2026-10-22T00:00:00+00:00'}])
def test_ac1_dr_freeze_refuses_rewritten_approval_history(boundary, change):
    """Failure: alter saved approval facts, recipient or destination before freeze; HTTP 400 after
    only the lookup prevents writing a message that rewrites the original decision.
    """
    client, _, cursor = boundary
    cursor.fetchone.return_value = dict(source_id=approval_JOB_ID, source=approval_SOURCE, type='event.approval', envelope=None, lease_valid=True, created_at=datetime(2026, 10, 21, tzinfo=UTC))
    result = client.post(f'/internal/notification-outbox/{approval_JOB_ID}/freeze', headers=approval_HEADERS, json={'leaseToken': approval_LEASE, 'envelope': {**approval_ENVELOPE, **change}})
    assert result.status_code == 400
    assert cursor.execute.call_count == 1

def test_ac4_dr_legacy_assignment_diagnoses_missing_organiser_without_guessing_recipient(boundary, caplog):
    """Failure: DR5: assign legacy ownerless event via HTTP; action succeeds with a diagnostic but no publishable intent or guessed recipient."""
    client, _, cursor = boundary
    cursor.fetchone.side_effect = [dict(coordinator_id=None, status='Submitted'), initial_assignment_assigned_row(None)]
    assert initial_assignment_assign(client).status_code == 200
    assert 'missing organiser' in caplog.text
    assert initial_assignment_intents(cursor) == []

def test_ac4_dr_outbox_failure_aborts_assignment_transaction(boundary):
    """Failure: make the assignment intent INSERT raise a database error; HTTP 503 and exceptional
    transaction exit protect the assignment-and-notification rollback contract.
    """
    import psycopg2
    client, connection, cursor = boundary
    cursor.fetchone.side_effect = [dict(coordinator_id=None, status='Submitted'), initial_assignment_assigned_row()]

    def execute(sql, params):
        if 'INSERT INTO public."EventNotificationOutbox"' in sql:
            raise psycopg2.OperationalError('isolated injected failure')
    cursor.execute.side_effect = execute
    assert initial_assignment_assign(client).status_code == 503
    assert connection.__exit__.call_args.args[0] is psycopg2.OperationalError

def test_ac4_dr_hold_refuses_invalid_diagnosis_or_stale_lease(boundary):
    """Failure: hold work with an invalid diagnosis, then a stale lease; HTTP 400 without a write
    and HTTP 409 respectively prevent invalid or obsolete workers from holding current work.
    """
    client, _, cursor = boundary
    cursor.fetchone.return_value = initial_assignment_pending()
    assert client.post(f'/internal/notification-outbox/{initial_assignment_JOB_ID}/hold', headers=initial_assignment_HEADERS, json=dict(leaseToken=initial_assignment_LEASE, error=None)).status_code == 400
    assert cursor.execute.call_count == 1
    cursor.fetchone.return_value = None
    assert client.post(f'/internal/notification-outbox/{initial_assignment_JOB_ID}/hold', headers=initial_assignment_HEADERS, json=dict(leaseToken=initial_assignment_LEASE, error='missing name')).status_code == 409

def test_ac4_dr_hold_diagnostics_reports_storage_failure_and_repair_requires_held_work(boundary):
    """Failure: release nonexistent held work, then list with broken or missing storage; HTTP 409
    and 503 distinguish a repair conflict from an outage instead of claiming successful
    recovery.
    """
    import psycopg2
    client, _, cursor = boundary
    cursor.fetchone.return_value = None
    assert client.post(f'/internal/notification-outbox/{initial_assignment_JOB_ID}/release', headers=initial_assignment_HEADERS, json={}).status_code == 409
    cursor.execute.side_effect = psycopg2.OperationalError('isolated failure')
    assert client.get('/internal/notification-outbox/held', headers=initial_assignment_HEADERS).status_code == 503
    client.application.config['DATABASE_URL'] = None
    assert client.get('/internal/notification-outbox/held', headers=initial_assignment_HEADERS).status_code == 503

@pytest.mark.parametrize('unavailable_database', [False, True], ids=['invalid-coordinator', 'database-unconfigured'])
def test_ac4_dr_invalid_or_unavailable_reassignment_has_no_database_work(boundary, unavailable_database):
    """Failure: DR2: invalid coordinator or missing DB configuration rejects before any transaction, so failed action cannot create notification work."""
    client, connection, cursor = boundary
    if unavailable_database:
        client.application.config['DATABASE_URL'] = None
    result = reassignment_assign(client, reassignment_BOB if unavailable_database else 'not-a-uuid')
    assert result.status_code == (503 if unavailable_database else 400)
    connection.cursor.assert_not_called()
    assert reassignment_intents(cursor) == []

def test_ac2_dr_publish_outage_releases_claim_for_retry_without_erasing_frozen_content(boundary):
    """Failure: DR3: retry HTTP operation records backoff and releases lease; observe SQL boundary retains envelope and never marks undelivered work published."""
    client, _, cursor = boundary
    cursor.fetchone.return_value = dict(lease_valid=True, attempts=1)
    response = client.post(f'/internal/notification-outbox/{rejection_JOB_ID}/retry', json={'leaseToken': rejection_LEASE, 'error': 'BrokerUnavailable'}, headers=rejection_HEADERS)
    assert response.status_code == 200
    sql, values = cursor.execute.call_args.args
    assert 'available_at' in sql and 'lease_token=NULL' in sql
    assert 'envelope=' not in sql and 'published_at=' not in sql
    assert values == (2, 'BrokerUnavailable', rejection_JOB_ID)

@pytest.mark.parametrize('route', ['reject', 'progress'])
def test_ac2_dr_outbox_failure_aborts_event_transaction(boundary, route):
    """Failure: DR2: inject DB error at intent write; observe 503 and exceptional transaction exit (unit rollback contract; real rollback needs integration)."""
    import psycopg2
    client, connection, cursor = boundary
    cursor.fetchone.side_effect = [rejection_row(), rejection_row('Rejected')]

    def execute(sql, params):
        if 'INSERT INTO public."EventNotificationOutbox"' in sql:
            raise psycopg2.OperationalError('injected intent failure')
    cursor.execute.side_effect = execute
    assert rejection_reject(client, route).status_code == 503
    assert connection.__exit__.call_args.args[0] is psycopg2.OperationalError

@pytest.mark.parametrize('token', [None, 'wrong', 'é'])
def test_ac2_dr_outbox_rejects_unauthenticated_calls_without_db_access(boundary, token):
    """Failure: claim work without the exact internal token; HTTP 401 before opening a cursor
    protects pending organiser notifications from unauthorised access.
    """
    client, connection, _ = boundary
    headers = {} if token is None else {'X-Internal-Token': token}
    assert client.post('/internal/notification-outbox/claim', headers=headers).status_code == 401
    connection.cursor.assert_not_called()

@pytest.mark.parametrize('missing', [True, False])
def test_ac2_dr_expired_or_missing_lease_cannot_complete_work(boundary, missing):
    """Failure: complete work whose lookup is missing or reports an expired lease; HTTP 409 with no
    UPDATE prevents a stale worker from marking delivery complete.
    """
    client, _, cursor = boundary
    cursor.fetchone.return_value = None if missing else dict(lease_valid=False)
    result = client.post(f'/internal/notification-outbox/{rejection_JOB_ID}/published', headers=rejection_HEADERS, json={'leaseToken': rejection_LEASE})
    assert result.status_code == 409
    assert cursor.execute.call_count == 1

@pytest.mark.parametrize('change', [{'version': True}, {'id': rejection_ORGANISER}, {'type': 'event.approval'}, {'recipientId': rejection_ACTOR}, {'createdAt': '2026-10-22T00:00:00+00:00'}, {'destination': {'kind': 'event-details', 'eventId': rejection_ORGANISER}}, {'details': {}}, {'message': 'replacement history'}])
def test_ac2_dr_freeze_refuses_changes_to_historical_rejection(boundary, change):
    """Failure: alter rejection identity, content, recipient or link before freeze; HTTP 400 after
    only the lookup prevents writing a notification inconsistent with the saved decision.
    """
    client, _, cursor = boundary
    pending = dict(source_id=rejection_JOB_ID, source=rejection_SOURCE, type='event.rejection', envelope=None, attempts=1, lease_token=rejection_LEASE, lease_valid=True, created_at=datetime(2026, 10, 21, tzinfo=UTC))
    cursor.fetchone.return_value = pending
    envelope = dict(version=1, id=rejection_JOB_ID, recipientId=rejection_ORGANISER, type='event.rejection', createdAt='2026-10-21T00:00:00+00:00', message=f'Community Workshop was rejected: {rejection_REASON}', destination=dict(kind='event-details', eventId=rejection_EVENT), details=rejection_SOURCE)
    result = client.post(f'/internal/notification-outbox/{rejection_JOB_ID}/freeze', headers=rejection_HEADERS, json={'leaseToken': rejection_LEASE, 'envelope': {**envelope, **change}})
    assert result.status_code == 400
    assert cursor.execute.call_count == 1

@pytest.mark.parametrize('action,body', [('published', {'leaseToken': rejection_LEASE}), ('retry', {'leaseToken': rejection_LEASE, 'error': 17}), ('retry', None), ('retry', {'leaseToken': 'bad'})])
def test_ac2_dr_outbox_refuses_unprepared_completion_and_invalid_inputs(boundary, action, body):
    """Failure: complete unfrozen work or send malformed retry data; HTTP 400 prevents completion
    before preparation and rejects unusable recovery requests.
    """
    client, _, cursor = boundary
    cursor.fetchone.return_value = dict(lease_valid=True, envelope=None)
    assert client.post(f'/internal/notification-outbox/{rejection_JOB_ID}/{action}', headers=rejection_HEADERS, json=body).status_code == 400

def test_ac2_dr_outbox_reports_storage_and_configuration_failures(boundary):
    """Failure: call an unknown operation, then claim with broken or missing storage; HTTP 404 and
    503 keep invalid requests distinct from outages rather than reporting an empty successful
    batch.
    """
    import psycopg2
    client, _, cursor = boundary
    assert client.post(f'/internal/notification-outbox/{rejection_JOB_ID}/unknown', headers=rejection_HEADERS).status_code == 404
    cursor.execute.side_effect = psycopg2.OperationalError('down')
    assert client.post('/internal/notification-outbox/claim', headers=rejection_HEADERS).status_code == 503
    client.application.config['DATABASE_URL'] = None
    assert client.post('/internal/notification-outbox/claim', headers=rejection_HEADERS).status_code == 503
