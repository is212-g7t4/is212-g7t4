"""Row builders for Event Service's integration tests. Each one inserts and returns the new ID.

Event.organiser_id and coordinator_id have foreign keys to User, which User Service owns;
the test (not the app) writes those parent rows, so the foreign keys stay real.
"""

import json
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

ORGANISER_ID = "33333333-3333-4333-8333-333333333333"
OTHER_ORGANISER_ID = "44444444-4444-4444-8444-444444444444"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
LEAD_ID = "22222222-2222-4222-8222-222222222222"
UNKNOWN_ID = "99999999-9999-4999-8999-999999999999"

SINGAPORE = ZoneInfo("Asia/Singapore")

# What the API accepts: naive Singapore local time, far in the future.
COMPLETE = {
    "eventName": "Community Workshop",
    "description": "A hands-on workshop",
    "purpose": "Learning",
    "preferredStartDate": "2030-03-01T09:00",
    "preferredEndDate": "2030-03-01T17:00",
    "expectedAttendance": "25",
}


def make_user(db, user_id, role="Event Organiser"):
    db.execute(
        'INSERT INTO public."User" (user_id, username, email, role) VALUES (%s, %s, %s, %s)',
        [user_id, f"user-{user_id[:4]}", f"user-{user_id[:4]}@example.com", role],
    )
    return user_id


def make_event(
    db,
    status="Draft",
    organiser_id=ORGANISER_ID,
    coordinator_id=None,
    event_name="Spring Fair",
    description="",
    purpose="",
    start=None,
    end=None,
    expected_attendance=None,
    venue_requirements=None,
    submitted=None,
):
    """An Event row stored the way the app stores it (description in its metadata envelope)."""
    event_id = str(uuid4())
    db.execute(
        """INSERT INTO public."Event"
           (event_id, event_name, description, preferred_start_date, preferred_end_date,
            expected_attendance, venue_requirements, status, organiser_id, coordinator_id,
            submission_date)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        [
            event_id,
            event_name,
            json.dumps({"_connectsphere": "event-submission-v1", "description": description, "purpose": purpose}),
            start,
            end,
            expected_attendance,
            venue_requirements,
            status,
            organiser_id,
            coordinator_id,
            submitted if submitted is not None else (None if status == "Draft" else datetime(2030, 1, 5, 9, tzinfo=SINGAPORE)),
        ],
    )
    return event_id
