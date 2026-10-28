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
    organiser_id: str | None = ORGANISER_ID,
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




SAFETY_COORDINATOR = '10000000-0000-0000-0000-000000000002'
SAFETY_TOKEN = "synthetic"

def make_safety_coordinator(db):
    db.query('INSERT INTO public."User"(user_id,username,email,role) VALUES (%s,%s,%s,%s)',
             [SAFETY_COORDINATOR, "Coordinator", "coordinator@example.com", "Event Coordinator"])
    return SAFETY_COORDINATOR


def make_safety_event(db, status='Approved', history=None):
    identifier = str(uuid4())
    metadata = dict(_connectsphere='event-submission-v1', description='Workshop', purpose='Learning',
                    actionHistory=history or [])
    db.query('''INSERT INTO public."Event"(event_id,event_name,description,status,coordinator_id,
                preferred_start_date,preferred_end_date,expected_attendance)
                VALUES (%s,'Workshop',%s,%s,%s,'2030-03-01T09:00+08:00','2030-03-01T17:00+08:00',25)''',
             [identifier, json.dumps(metadata), status, SAFETY_COORDINATOR])
    return identifier




def seed_existing_data(db):
    """Synthetic linked legacy rows in EVERY pre-SCRUM45 public table."""
    db.query('\n        INSERT INTO public."User"(user_id,username,email,role) VALUES\n          (\'10000000-0000-0000-0000-000000000001\',\'Synthetic organiser\',\'migration@example.com\',\'Event Organiser\');\n        INSERT INTO public."Event"(event_id,event_name,organiser_id,status) VALUES\n          (\'20000000-0000-0000-0000-000000000001\',\'Synthetic legacy event\',\'10000000-0000-0000-0000-000000000001\',\'Pending Review\');\n        INSERT INTO public."Venue"(venue_id,venue_name) VALUES\n          (\'30000000-0000-0000-0000-000000000001\',\'Synthetic venue\');\n        INSERT INTO public."VenueClosure"(closure_id,venue_id,start_date_time,end_date_time,reason,created_by,created_at) VALUES\n          (\'40000000-0000-0000-0000-000000000001\',\'30000000-0000-0000-0000-000000000001\',\'2030-01-01Z\',\'2030-01-02Z\',\'Synthetic maintenance\',\'10000000-0000-0000-0000-000000000001\',\'2026-01-01Z\');\n        INSERT INTO public."VenueBooking"(booking_id,event_id,venue_id,requested_start_time,requested_end_time,status,required_capacity,held_by,held_for,held_at) VALUES\n          (\'50000000-0000-0000-0000-000000000001\',\'20000000-0000-0000-0000-000000000001\',\'30000000-0000-0000-0000-000000000001\',\'2030-02-01Z\',\'2030-02-02Z\',\'Tentative\',10,\'10000000-0000-0000-0000-000000000001\',\'10000000-0000-0000-0000-000000000001\',\'2026-01-01Z\');\n        INSERT INTO public."Equipment"(equipment_id,equipment_type,total_quantity) VALUES\n          (\'60000000-0000-0000-0000-000000000001\',\'Synthetic chair\',10);\n        INSERT INTO public."EquipmentRequest"(equipment_request_id,event_id,equipment_id,quantity_requested) VALUES\n          (\'70000000-0000-0000-0000-000000000001\',\'20000000-0000-0000-0000-000000000001\',\'60000000-0000-0000-0000-000000000001\',2);\n        INSERT INTO public."SafetyCheck"(safety_check_id,event_id,round_number,status) VALUES\n          (\'80000000-0000-0000-0000-000000000001\',\'20000000-0000-0000-0000-000000000001\',1,\'Approved\');\n        INSERT INTO public."SafetyCheckFlag"(safety_check_id,booking_id,equip_request_id,area) VALUES\n          (\'80000000-0000-0000-0000-000000000001\',\'50000000-0000-0000-0000-000000000001\',\'70000000-0000-0000-0000-000000000001\',\'Synthetic area\');\n        INSERT INTO public."EventChangeReq"(event_id,requested_changes,status) VALUES\n          (\'20000000-0000-0000-0000-000000000001\',\'{"event_name":"Synthetic updated"}\',\'Approved\');\n        INSERT INTO public."Registration"(event_id,attendee_id,status) VALUES\n          (\'20000000-0000-0000-0000-000000000001\',\'10000000-0000-0000-0000-000000000001\',\'Registered\');\n        INSERT INTO public."Notification"(recipient_id,event_id,type,payload,dedupe_key,created_at,read_at) VALUES\n          (\'10000000-0000-0000-0000-000000000001\',\'20000000-0000-0000-0000-000000000001\',\'legacy\',\'{"message":"Synthetic read inbox"}\',\'synthetic-legacy\',\'2026-01-01Z\',\'2026-01-02Z\');\n        INSERT INTO public."NotificationFailure"(body,error) VALUES (\'synthetic\',\'Synthetic legacy failure\');\n        INSERT INTO public."VenueNotificationOutbox"(closure_id,booking_id,source,envelope,published_at,attempts) VALUES\n          (\'40000000-0000-0000-0000-000000000001\',\'50000000-0000-0000-0000-000000000001\',\'{"synthetic":true}\',\'{"frozen":true}\',\'2026-01-01Z\',2);\n    ')
    if db.query("SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='EventChangeReq' AND column_name='requested_by'")[0][0]:
        db.query('UPDATE public."EventChangeReq" SET requested_by=\'10000000-0000-0000-0000-000000000001\',\n                    reason=\'Synthetic change audit reason\' ')
    if db.query('SELECT to_regclass(\'public."EventNotificationOutbox"\')')[0][0]:
        db.query('INSERT INTO public."EventNotificationOutbox"(type,source,envelope,published_at,attempts,last_error)\n                    VALUES (\'event.rejection\',\'{"synthetic":true}\',\'{"frozen":true}\',\'2026-01-01Z\',2,\'Synthetic prior retry\'),\n                           (\'event.rejection\',\'{"pending":true}\',NULL,NULL,0,NULL)')
