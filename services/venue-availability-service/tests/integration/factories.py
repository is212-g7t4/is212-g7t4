"""Row builders for Venue Availability's integration tests. Each one inserts and returns the ID.

VenueBooking.venue_id, requested_by and held_by have foreign keys to Venue and User, which
Venue Service and User Service own; the test (not the app) writes those parent rows, so the
foreign keys stay real. event_id has no foreign key, but the Event row is still inserted so
the data looks like production.
"""

from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

SINGAPORE = ZoneInfo("Asia/Singapore")

COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
OTHER_COORDINATOR_ID = "22222222-2222-4222-8222-222222222222"
STAFF_ID = "33333333-3333-4333-8333-333333333333"


def at(day, hour, minute=0):
    """A fixed, timezone-aware Singapore time in March 2030."""
    return datetime(2030, 3, day, hour, minute, tzinfo=SINGAPORE)


def make_user(db, user_id=COORDINATOR_ID, role="Event Coordinator"):
    db.execute(
        'INSERT INTO public."User" (user_id, username, email, role) VALUES (%s, %s, %s, %s)',
        [user_id, f"user-{user_id[:4]}", f"user-{user_id[:4]}@example.com", role],
    )
    return user_id


def make_venue(db, capacity=100, setup_time_minutes=0, turnaround_time_minutes=0, name="Hall A"):
    venue_id = str(uuid4())
    db.execute(
        """INSERT INTO public."Venue"
           (venue_id, venue_name, max_capacity, operational_status,
            setup_time_minutes, turnaround_time_minutes)
           VALUES (%s, %s, %s, 'Available', %s, %s)""",
        [venue_id, name, capacity, setup_time_minutes, turnaround_time_minutes],
    )
    return venue_id


def make_event(db, coordinator_id=COORDINATOR_ID, name="Spring Fair", status="Under Review"):
    event_id = str(uuid4())
    db.execute(
        """INSERT INTO public."Event" (event_id, event_name, status, coordinator_id)
           VALUES (%s, %s, %s, %s)""",
        [event_id, name, status, coordinator_id],
    )
    return event_id


def make_booking(db, event_id, venue_id, start, end, status="Approved", requested_by=COORDINATOR_ID):
    booking_id = str(uuid4())
    db.execute(
        """INSERT INTO public."VenueBooking"
           (booking_id, event_id, venue_id, requested_start_time, requested_end_time,
            required_capacity, venue_requirements, status, requested_by)
           VALUES (%s, %s, %s, %s, %s, 50, '', %s, %s)""",
        [booking_id, event_id, venue_id, start, end, status, requested_by],
    )
    return booking_id


def make_hold(db, venue_id, start, end, expires_at, held_by=STAFF_ID):
    """An 'On Hold' row: a tentative hold not yet tied to an event."""
    booking_id = str(uuid4())
    db.execute(
        """INSERT INTO public."VenueBooking"
           (booking_id, venue_id, requested_start_time, requested_end_time,
            required_capacity, status, held_by, held_at, hold_expires_at)
           VALUES (%s, %s, %s, %s, 1, 'On Hold', %s, now(), %s)""",
        [booking_id, venue_id, start, end, held_by, expires_at],
    )
    return booking_id


def make_closure(db, venue_id, start, end, created_by=STAFF_ID, reason="Roof repair"):
    closure_id = str(uuid4())
    db.execute(
        """INSERT INTO public."VenueClosure"
           (closure_id, venue_id, start_date_time, end_date_time, reason, created_by, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, now())""",
        [closure_id, venue_id, start, end, reason, created_by],
    )
    return closure_id
