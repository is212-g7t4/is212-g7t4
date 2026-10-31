"""Row builders for Safety Check Record Service's integration tests. Each one inserts and returns the new ID.

SafetyCheck has foreign keys to Event and User (submitted_by, decided_by, withdrawn_by), and
SafetyCheckFlag to VenueBooking and EquipmentRequest. Those tables belong to other services;
the test (not the app) writes the parent rows, so the foreign keys stay real (guide §4, §5).
"""

from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from tests.unit.factories import bearer

COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
OTHER_COORDINATOR_ID = "12121212-1212-4121-8121-121212121212"
OFFICER_ID = "33333333-3333-4333-8333-333333333333"
OTHER_OFFICER_ID = "34343434-3434-4343-8343-343434343434"
ATTENDEE_ID = "77777777-7777-4777-8777-777777777777"
UNKNOWN_ID = "99999999-9999-4999-8999-999999999999"

SINGAPORE = ZoneInfo("Asia/Singapore")
# Fixed, far-future times for rows the test writes itself (guide §5). Times the app stamps
# with SQL now() are asserted relative to the database clock instead.
SUBMITTED = datetime(2030, 3, 1, 9, 0, tzinfo=SINGAPORE)
DECIDED = SUBMITTED + timedelta(days=1)

ROLES = {
    COORDINATOR_ID: "Event Coordinator",
    OTHER_COORDINATOR_ID: "Event Coordinator",
    OFFICER_ID: "Safety Officer",
    OTHER_OFFICER_ID: "Safety Officer",
    ATTENDEE_ID: "Attendee",
}


def as_user(user_id, role=None):
    """A signed-in user's Authorization header (SCRUM-8), as request kwargs."""
    return {"headers": bearer(user_id, role or ROLES[user_id])}


def make_user(db, user_id, role=None):
    db.execute(
        'INSERT INTO public."User" (user_id, username, email, role) VALUES (%s, %s, %s, %s)',
        [user_id, f"user-{user_id[:4]}", f"user-{user_id[:4]}@example.com", role or ROLES[user_id]],
    )
    return user_id


def make_people(db):
    """Every user the tests sign in as, so the submitted_by/decided_by/withdrawn_by FKs hold."""
    for user_id in ROLES:
        make_user(db, user_id)


def make_event(db, status="Approved", coordinator_id=COORDINATOR_ID):
    event_id = str(uuid4())
    db.execute(
        """INSERT INTO public."Event"
           (event_id, event_name, status, coordinator_id, expected_attendance,
            preferred_start_date, preferred_end_date)
           VALUES (%s, 'Harbour Safety Fair', %s, %s, 80, %s, %s)""",
        [event_id, status, coordinator_id, SUBMITTED + timedelta(days=30), SUBMITTED + timedelta(days=30, hours=6)],
    )
    return event_id


def make_round(
    db,
    event_id,
    round_number=1,
    status="Pending",
    submitted_by=COORDINATOR_ID,
    equipment_placement_notes=None,
    crowd_movement_notes=None,
    decided_by=None,
    remarks=None,
    decided_at=None,
    withdrawn_by=None,
    withdrawal_reason=None,
):
    """A SafetyCheck row. Any status other than Pending is stored with its decision fields."""
    decided = status != "Pending"
    row = db.execute(
        """INSERT INTO public."SafetyCheck"
           (event_id, round_number, submitted_by, submitted_at, equipment_placement_notes,
            crowd_movement_notes, status, decided_by, decided_at, remarks,
            withdrawn_by, withdrawn_at, withdrawal_reason)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           RETURNING safety_check_id""",
        [
            event_id,
            round_number,
            submitted_by,
            SUBMITTED,
            equipment_placement_notes,
            crowd_movement_notes,
            status,
            (decided_by or OFFICER_ID) if decided else None,
            (decided_at or DECIDED) if decided else None,
            remarks if remarks is not None else ("Looks safe." if decided else None),
            withdrawn_by,
            DECIDED + timedelta(days=1) if withdrawn_by else None,
            withdrawal_reason,
        ],
    )
    return str(row[0]["safety_check_id"])


def make_flag(db, safety_check_id, area="venue arrangement", change_required="Move the stage."):
    row = db.execute(
        """INSERT INTO public."SafetyCheckFlag" (safety_check_id, area, change_required)
           VALUES (%s, %s, %s) RETURNING flag_id""",
        [safety_check_id, area, change_required],
    )
    return str(row[0]["flag_id"])


def make_booking(db, event_id, status="Approved"):
    """A VenueBooking (and its Venue) that a venue-arrangement flag can point at."""
    venue_id = db.execute(
        """INSERT INTO public."Venue" (venue_name, max_capacity, operational_status)
           VALUES ('Harbour Hall', 120, 'Available') RETURNING venue_id"""
    )[0]["venue_id"]
    start = SUBMITTED + timedelta(days=30)
    return str(db.execute(
        """INSERT INTO public."VenueBooking"
           (event_id, venue_id, requested_start_time, requested_end_time, status,
            requested_by, required_capacity)
           VALUES (%s, %s, %s, %s, %s, %s, 80) RETURNING booking_id""",
        [event_id, venue_id, start, start + timedelta(hours=6), status, COORDINATOR_ID],
    )[0]["booking_id"])


def make_equipment_request(db, event_id, status="Approved"):
    """An EquipmentRequest (and its Equipment) that a technical-arrangement flag can point at."""
    equipment_id = db.execute(
        """INSERT INTO public."Equipment" (equipment_type, total_quantity, operational_status)
           VALUES ('Projector', 4, 'Available') RETURNING equipment_id"""
    )[0]["equipment_id"]
    return str(db.execute(
        """INSERT INTO public."EquipmentRequest"
           (event_id, equipment_id, quantity_requested, status, requested_by)
           VALUES (%s, %s, 2, %s, %s) RETURNING equipment_request_id""",
        [event_id, equipment_id, status, COORDINATOR_ID],
    )[0]["equipment_request_id"])
