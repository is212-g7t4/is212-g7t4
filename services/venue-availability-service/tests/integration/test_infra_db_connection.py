"""Infra: database connection and migrations: Venue Availability integration tests.

Why:        if the app silently pointed at another database, or the migration chain stopped
            loading, every story test in this folder would fail for the wrong reason.
Real:       Flask app, app/models.py SQL, postgres:17.6 with the full migration chain.
Doubled:    nothing.
Not proven: that the hosted Supabase schema matches the migration chain.
"""

import pytest

from tests.integration.factories import (
    at,
    make_booking,
    make_event,
    make_user,
    make_venue,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


def test_migrations_created_the_booking_columns_this_service_reads(db):
    """Normal: requested_at and the hold columns exist, so booking_columns() can select them."""
    columns = {
        row["column_name"]
        for row in db.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'VenueBooking'"""
        )
    }
    assert {"requested_at", "hold_expires_at", "held_for", "rejection_closure_id"} <= columns


def test_app_reads_rows_from_the_test_database(client, db):
    """Normal: a row inserted directly is what the app returns."""
    make_user(db)
    venue_id = make_venue(db)
    event_id = make_event(db)
    booking_id = make_booking(db, event_id, venue_id, at(1, 9), at(1, 11))

    response = client.get(f"/events/{event_id}/venue-bookings")

    assert response.status_code == 200
    assert [booking["id"] for booking in response.get_json()["bookings"]] == [booking_id]
