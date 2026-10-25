"""Database row builders for registration-withdrawal integration tests."""

from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

ATTENDEE_ID = "11111111-1111-4111-8111-111111111111"
OTHER_ATTENDEE_ID = "22222222-2222-4222-8222-222222222222"
ORGANISER_ID = "33333333-3333-4333-8333-333333333333"
SINGAPORE = ZoneInfo("Asia/Singapore")


def make_user(db, user_id, role):
    db.execute(
        'INSERT INTO public."User" (user_id, username, email, role) VALUES (%s, %s, %s, %s)',
        [user_id, f"user-{user_id[:4]}", f"user-{user_id[:4]}@example.com", role],
    )
    return user_id


def make_event(db, organiser_id=ORGANISER_ID):
    event_id = str(uuid4())
    db.execute(
        '''INSERT INTO public."Event"
           (event_id, event_name, expected_attendance, preferred_start_date,
            preferred_end_date, status, organiser_id, registration_enabled)
           VALUES (%s, 'Community Workshop', 20, %s, %s, 'Confirmed', %s, true)''',
        [
            event_id,
            datetime(2030, 3, 1, 9, tzinfo=SINGAPORE),
            datetime(2030, 3, 1, 17, tzinfo=SINGAPORE),
            organiser_id,
        ],
    )
    return event_id


def make_registration(db, event_id, attendee_id=ATTENDEE_ID, status="Confirmed", withdrawn_at=None):
    registration_id = str(uuid4())
    db.execute(
        '''INSERT INTO public."Registration"
           (registration_id, event_id, attendee_id, registration_date, status, withdrawn_at)
           VALUES (%s, %s, %s, %s, %s, %s)''',
        [
            registration_id,
            event_id,
            attendee_id,
            datetime(2029, 12, 1, 10, tzinfo=SINGAPORE),
            status,
            withdrawn_at,
        ],
    )
    return registration_id


def make_withdrawal_world(db, status="Confirmed", withdrawn_at=None):
    make_user(db, ORGANISER_ID, "Event Organiser")
    make_user(db, ATTENDEE_ID, "Attendee")
    make_user(db, OTHER_ATTENDEE_ID, "Attendee")
    event_id = make_event(db)
    registration_id = make_registration(db, event_id, status=status, withdrawn_at=withdrawn_at)
    return event_id, registration_id
