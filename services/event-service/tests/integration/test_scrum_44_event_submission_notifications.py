"""SCRUM-44 submission notifications: Event service integration checks.

Story: As a Lead Coordinator, I want to receive an in-app notification when an Event Organiser submits an event request, so that I can review it and make a decision.

AC1 Given an Event Organiser submits a new event request, the Lead Coordinator receives an in-app notification that a new request requires review.
AC2 The notification includes the event name, Event Organiser name, proposed event date/time, and a link to review the event request.
AC3 Saving or editing a draft event request does not trigger a submission notification.

Real Flask routes and SQL run against disposable local PostgreSQL.
Lead IDs and organiser names are supplied inputs; no User service is called.
These check saved notification work, not broker delivery, inboxes or browser UI.
Expansion replay is checked, but partial expansion failure is not."""
import pytest
from tests.integration.factories import COMPLETE, ORGANISER_ID, LEAD_ID, make_user

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
HEADERS = {'X-Internal-Token': 'synthetic-submission-token'}


# AC1 — Avoid duplicate deliveries; keep submitted details (AC2).

def test_dr_expansion_replay_cannot_duplicate_persisted_recipients(client, db):
    """AC1/AC2: Duplicate Lead IDs and a repeated request save only one delivery.
    Later event edits leave the submitted name and dates unchanged.
    The organiser name comes from the supplied input, not a User lookup."""
    client.application.config['INTERNAL_SERVICE_TOKEN'] = HEADERS['X-Internal-Token']
    make_user(db, ORGANISER_ID)
    event = client.post('/events', json={**COMPLETE, 'organiserId': ORGANISER_ID})
    assert event.status_code == 201
    root = client.post('/internal/notification-outbox/claim', headers=HEADERS, json={}).json['jobs'][0]
    assert root['source']['startDateTime'] == '2030-03-01T09:00:00+08:00'
    assert root['source']['endDateTime'] == '2030-03-01T17:00:00+08:00'
    endpoint = f"/internal/notification-outbox/{root['id']}/expand"
    body = dict(leaseToken=root['leaseToken'], recipientIds=[LEAD_ID, LEAD_ID], organiserName='Synthetic Organiser')
    assert client.post(endpoint, headers=HEADERS, json=body).status_code == 200
    assert client.post(endpoint, headers=HEADERS, json=body).status_code == 409
    rows = db.execute('SELECT * FROM public."EventNotificationOutbox" WHERE type=\'event.submission\'')
    assert len(rows) == 1
    assert rows[0]['source']['recipientId'] == LEAD_ID
    assert rows[0]['source']['eventName'] == 'Community Workshop'
    assert rows[0]['source']['organiserName'] == 'Synthetic Organiser'
    assert rows[0]['source']['organiserNameCapturedAt']
    assert rows[0]['envelope'] is None
    # Edit the event; saved submission details must stay unchanged.
    db.execute('''UPDATE public."Event" SET event_name='Renamed later',
                  preferred_start_date='2031-04-05T10:00:00+08:00',
                  preferred_end_date='2031-04-06T12:00:00+08:00'
                  WHERE event_id=%s''', [event.json['id']])
    edited = db.event(event.json['id'])
    assert edited['event_name'] == 'Renamed later'
    assert edited['preferred_start_date'].isoformat() == '2031-04-05T02:00:00+00:00'
    assert edited['preferred_end_date'].isoformat() == '2031-04-06T04:00:00+00:00'
    original_facts = {
        'eventId': event.json['id'], 'eventName': 'Community Workshop',
        'organiserId': ORGANISER_ID,
        'startDateTime': '2030-03-01T09:00:00+08:00',
        'endDateTime': '2030-03-01T17:00:00+08:00',
    }
    parent = db.execute('''SELECT source FROM public."EventNotificationOutbox"
                           WHERE source_id=%s''', [root['id']])[0]
    assert parent['source'] == original_facts
    child = client.post('/internal/notification-outbox/claim', headers=HEADERS, json={}).json['jobs'][0]
    assert child['source'] == {
        **original_facts, 'recipientId': LEAD_ID,
        'organiserName': 'Synthetic Organiser',
        'organiserNameCapturedAt': rows[0]['source']['organiserNameCapturedAt'],
    }


# AC1 — Preserve existing data during migration.

from pathlib import Path
import psycopg2
from tests.integration.factories import seed_existing_data

MIGRATIONS = Path(__file__).resolve().parents[4] / "database/supabase/migrations"
# Full SCRUM-49 chain (only the submission migration is delayed below).
EXPECTED_TABLES = {'Equipment', 'EquipmentRequest', 'Event', 'EventChangeReq', 'Notification', 'Registration', 'SafetyCheck', 'SafetyCheckFlag', 'User', 'Venue', 'VenueBooking', 'VenueClosure', 'NotificationFailure', 'VenueNotificationOutbox', 'EventNotificationOutbox', 'EquipmentNotificationOutbox'}
TYPES = ('event.rejection', 'event.approval', 'event.coordinator-assignment')

# Independent schema checks.
def assert_schema_and_types(db):
    """Check disposable PostgreSQL schema, allowed types, security flags and indexes.
    These SQL checks do not prove hosted-role permissions."""
    assert set(db.snapshot()) == EXPECTED_TABLES
    columns = dict(db.query("SELECT column_name, data_type FROM information_schema.columns\n                              WHERE table_schema='public' AND table_name='EventNotificationOutbox' "))
    assert columns == {'source_id': 'uuid', 'type': 'character varying', 'source': 'jsonb', 'envelope': 'jsonb', 'created_at': 'timestamp with time zone', 'published_at': 'timestamp with time zone', 'attempts': 'integer', 'available_at': 'timestamp with time zone', 'lease_token': 'uuid', 'lease_until': 'timestamp with time zone', 'last_error': 'text', 'held_at': 'timestamp with time zone'}
    assert db.query("SELECT is_nullable FROM information_schema.columns\n                      WHERE table_schema='public' AND table_name='EventNotificationOutbox' AND column_name='held_at' ") == [('YES',)]
    for kind in TYPES:
        source_id, held_at = db.query('INSERT INTO public."EventNotificationOutbox"(type,source)\n                                        VALUES (%s,\'{"synthetic":true}\') RETURNING source_id, held_at', (kind,))[0]
        assert held_at is None
        db.query('UPDATE public."EventNotificationOutbox" SET held_at=\'2030-01-01T12:00:00+08:00\'\n                    WHERE source_id=%s', (str(source_id),))
        assert db.query('SELECT held_at=\'2030-01-01T04:00:00Z\'::timestamptz\n                           FROM public."EventNotificationOutbox" WHERE source_id=%s', (str(source_id),)) == [(True,)]
    with pytest.raises(psycopg2.errors.CheckViolation):
        db.query('INSERT INTO public."EventNotificationOutbox"(type,source) VALUES (\'event.invalid\',\'{}\')')
    with pytest.raises(psycopg2.errors.NotNullViolation):
        db.query('INSERT INTO public."EventNotificationOutbox"(type,source) VALUES (\'event.approval\',NULL)')
    row_security = dict(db.query("SELECT c.relname,c.relrowsecurity FROM pg_class c JOIN pg_namespace n\n                                   ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r' "))
    assert row_security == dict.fromkeys(EXPECTED_TABLES, True)
    assert db.query("SELECT count(*) FROM pg_policies WHERE schemaname='public' ") == [(0,)]
    indexes = dict(db.query("SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='public'\n                              AND tablename='EventNotificationOutbox' "))
    assert 'UNIQUE INDEX' in indexes['EventNotificationOutbox_pkey']
    assert 'WHERE (published_at IS NULL)' in indexes['event_outbox_pending']
    print('VERIFIED all tables, exact EventNotificationOutbox column types, three allowed types, invalid-type rejection, nullable/timezone-safe held_at, RLS and indexes', flush=True)

def test_submission_migration_upgrades_current_main_without_changing_existing_rows(migration_database):
    """AC1 support: The migration preserves existing rows and notification types.
    Both new submission types can be saved without changing the existing schema."""
    paths = sorted(MIGRATIONS.glob('*.sql'))
    pending = [path for path in paths if path.name == '20261025000000_event_submission_notifications.sql']
    assert len(pending) == 1
    with migration_database() as db:
        db.apply([path for path in paths if path not in pending])
        seed_existing_data(db)
        for kind in TYPES:
            db.query('INSERT INTO public."EventNotificationOutbox"(type,source) VALUES (%s,%s)', (kind, '{"preserved":true}'))
        before = db.snapshot()
        db.apply(pending)
        assert db.snapshot() == before
        assert_schema_and_types(db)
        for kind in ('event.submission-fanout', 'event.submission'):
            db.query('INSERT INTO public."EventNotificationOutbox"(type,source) VALUES (%s,%s)', (kind, '{"new":true}'))
        assert len(db.query('SELECT * FROM public."EventNotificationOutbox" WHERE type LIKE %s', ('event.submission%',))) == 2


# AC1 — Roll back if notification work cannot be saved.

@pytest.mark.parametrize('submission', ['direct', 'saved-draft'])
def test_ac1_failed_notification_intent_rolls_back_submission(client, db, submission):
    """AC1 support: Rejecting notification work also rolls back submission.
    Direct submission leaves no event; a saved draft stays unchanged."""
    make_user(db, ORGANISER_ID)
    details = {**COMPLETE, 'organiserId': ORGANISER_ID}
    draft = None
    if submission == 'saved-draft':
        response = client.post('/events/drafts', json=details)
        assert response.status_code == 201
        draft = response.json
    before = db.execute('SELECT * FROM public."Event" ORDER BY event_id')
    # Reject notification work only in this disposable database.
    db.execute("""ALTER TABLE public."EventNotificationOutbox" ADD CONSTRAINT synthetic_scrum44_failure CHECK (type <> 'event.submission-fanout')""")
    try:
        path = '/events' if draft is None else f"/events/drafts/{draft['id']}/submit"
        result = client.post(path, json=details)
        assert result.status_code == 503
        assert 'Unable to save or load event requests' in result.json['message']
        assert db.execute('SELECT * FROM public."Event" ORDER BY event_id') == before
        assert db.execute('SELECT * FROM public."EventNotificationOutbox"') == []
        drafts = client.get('/events/drafts', query_string={'organiserId': ORGANISER_ID})
        assert drafts.status_code == 200
        assert [item['id'] for item in drafts.json['events']] == ([] if draft is None else [draft['id']])
        if draft is not None:
            assert drafts.json['events'][0]['status'] == 'Draft'
    finally:
        db.execute('ALTER TABLE public."EventNotificationOutbox" DROP CONSTRAINT synthetic_scrum44_failure')


# AC1 — Save one sending obligation with submitted details (AC2).

@pytest.mark.parametrize('submission', ['direct', 'saved-draft'])
def test_ac1_successful_submission_saves_one_matching_intent(client, db, submission):
    """AC1/AC2: Direct and saved-draft submissions save exactly one sending obligation.
    It contains the submitted name and cross-midnight period with time offsets.
    A submitted draft keeps its ID; no message has been sent yet."""
    make_user(db, ORGANISER_ID)
    details = {**COMPLETE, 'organiserId': ORGANISER_ID,
               'preferredStartDate': '2030-03-01T23:15',
               'preferredEndDate': '2030-03-02T01:45'}
    draft_id = None
    if submission == 'saved-draft':
        saved = client.post('/events/drafts', json={
            'eventName': 'Earlier draft name', 'organiserId': ORGANISER_ID})
        assert saved.status_code == 201
        draft_id = saved.json['id']
    path = '/events' if draft_id is None else f'/events/drafts/{draft_id}/submit'

    response = client.post(path, json=details)

    assert response.status_code == (201 if draft_id is None else 200)
    event_id = response.json['id']
    if draft_id is not None:
        assert event_id == draft_id
    persisted = db.event(event_id)
    assert persisted['status'] == 'Submitted'
    assert persisted['submission_date'] is not None
    assert persisted['event_name'] == 'Community Workshop'
    assert persisted['preferred_start_date'].isoformat() == '2030-03-01T15:15:00+00:00'
    assert persisted['preferred_end_date'].isoformat() == '2030-03-01T17:45:00+00:00'
    intents = db.execute(
        '''SELECT * FROM public."EventNotificationOutbox"
           WHERE source->>'eventId' = %s''', [event_id])
    assert len(intents) == 1
    assert intents[0]['type'] == 'event.submission-fanout'
    assert intents[0]['source'] == {
        'eventId': event_id, 'eventName': 'Community Workshop',
        'organiserId': ORGANISER_ID,
        'startDateTime': '2030-03-01T23:15:00+08:00',
        'endDateTime': '2030-03-02T01:45:00+08:00',
    }
    assert intents[0]['envelope'] is None
    assert intents[0]['published_at'] is None


# AC1 — Reject incomplete submissions.

@pytest.mark.parametrize('submission', ['direct', 'saved-draft'])
def test_ac1_missing_required_details_create_no_submission_or_intent(client, db, submission):
    """AC1 support: Missing Purpose returns 400 with no submission or notification work.
    Existing event rows and any saved draft stay unchanged."""
    make_user(db, ORGANISER_ID)
    details = {**COMPLETE, 'organiserId': ORGANISER_ID}
    details.pop('purpose')
    draft_id = None
    if submission == 'saved-draft':
        saved = client.post('/events/drafts', json={
            'eventName': 'Keep this original draft', 'organiserId': ORGANISER_ID,
            'venueRequirements': 'Preserve the original hall'})
        assert saved.status_code == 201
        draft_id = saved.json['id']
    before = db.execute('SELECT * FROM public."Event" WHERE organiser_id=%s', [ORGANISER_ID])
    path = '/events' if draft_id is None else f'/events/drafts/{draft_id}/submit'

    response = client.post(path, json=details)

    assert response.status_code == 400
    assert response.json['missingFields'] == ['Purpose']
    assert db.execute('SELECT * FROM public."Event" WHERE organiser_id=%s', [ORGANISER_ID]) == before
    assert db.execute(
        '''SELECT * FROM public."EventNotificationOutbox"
           WHERE source->>'organiserId'=%s''', [ORGANISER_ID]) == []
    if draft_id is not None:
        assert db.event(draft_id) == before[0]
        assert db.event(draft_id)['status'] == 'Draft'


# AC3 — Save and edit drafts without notification work.

def test_ac3_saving_and_editing_draft_persists_without_submission_intent(client, db):
    """AC3: Saving then editing a draft preserves the changes without submitting it.
    Both steps leave Draft status, no submission time and no notification work."""
    make_user(db, ORGANISER_ID)
    saved = client.post('/events/drafts', json={
        'eventName': 'Initial draft', 'organiserId': ORGANISER_ID})
    assert saved.status_code == 201
    event_id = saved.json['id']
    row = db.event(event_id)
    assert row['event_name'] == 'Initial draft'
    assert row['status'] == 'Draft'
    assert row['submission_date'] is None
    matching_intents = '''SELECT * FROM public."EventNotificationOutbox"
                          WHERE source->>'eventId'=%s'''
    assert db.execute(matching_intents, [event_id]) == []

    edited = client.patch(f'/events/drafts/{event_id}', json={
        **COMPLETE, 'eventName': 'Complete but not submitted', 'organiserId': ORGANISER_ID})

    assert edited.status_code == 200
    assert edited.json['id'] == event_id
    row = db.event(event_id)
    assert row['event_name'] == 'Complete but not submitted'
    assert row['expected_attendance'] == 25
    assert row['preferred_start_date'].isoformat() == '2030-03-01T01:00:00+00:00'
    assert row['preferred_end_date'].isoformat() == '2030-03-01T09:00:00+00:00'
    assert row['status'] == 'Draft'
    assert row['submission_date'] is None
    assert db.execute(matching_intents, [event_id]) == []
