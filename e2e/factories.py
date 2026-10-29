"""Synthetic SCRUM-46 cross-service world; no shared data is read."""

import json
from uuid import uuid4
from psycopg2.extras import Json


def attendee_world(stack):
    """Insert a synthetic Confirmed Workshop, Approved Hall A booking, organiser and coordinator.
    Return their event/round IDs plus three distinct attendees, initially unregistered.
    The owned stack enforces SQL identity; setup bypasses unrelated creation workflows
    so the journey can focus on registration actions and notification delivery.
    """
    users = [str(uuid4()) for _ in range(5)]
    organiser, coordinator, *attendees = users
    for i, user in enumerate(users):
        role = (
            "Event Organiser"
            if i == 0
            else "Event Coordinator"
            if i == 1
            else "Attendee"
        )
        stack.query(
            'INSERT INTO public."User"(user_id,username,email,role) VALUES (%s,%s,%s,%s)',
            [user, f"Synthetic {i}", f"user{i}@example.com", role],
        )
    event, venue, booking, round_id = [str(uuid4()) for _ in range(4)]
    metadata = dict(
        _connectsphere="event-submission-v1",
        description="Workshop",
        purpose="Learning",
        actionHistory=[dict(status="Confirmed", safetyCheckId=round_id)],
    )
    stack.query(
        """INSERT INTO public."Event"(event_id,event_name,description,expected_attendance,preferred_start_date,preferred_end_date,status,organiser_id,coordinator_id,registration_enabled)
        VALUES (%s,'Workshop',%s,20,'2030-03-01T01:00:00Z','2030-03-01T09:00:00Z','Confirmed',%s,%s,true)""",
        [event, json.dumps(metadata), organiser, coordinator],
    )
    stack.query(
        'INSERT INTO public."Venue"(venue_id,venue_name,max_capacity) VALUES (%s,%s,50)',
        [venue, "Hall A"],
    )
    stack.query(
        """INSERT INTO public."VenueBooking"(booking_id,event_id,venue_id,requested_start_time,requested_end_time,status,required_capacity)
        VALUES (%s,%s,%s,'2030-03-01T01:00:00Z','2030-03-01T09:00:00Z','Approved',20)""",
        [booking, event, venue],
    )
    return dict(
        event=event, attendees=attendees, coordinator=coordinator, round_id=round_id
    )
