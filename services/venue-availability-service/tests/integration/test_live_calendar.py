"""Opt-in READ ONLY Postgres smoke. Never seed or modify the shared database."""

import os
from contextlib import closing
from datetime import datetime, timedelta

import psycopg2
import pytest

from app import create_app

# Needs a real database, so it is deselected by default and must re-enable the
# sockets that the unit-test run blocks. Run it with:
#   RUN_LIVE_CALENDAR_SMOKE=true uv run pytest -m integration --no-cov
pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_CALENDAR_SMOKE") != "true",
    reason="Explicit live read opt-in required",
)
def test_live_calendar_read_only(monkeypatch):
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not configured")
    real_connect = psycopg2.connect

    def readonly_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connection.set_session(readonly=True)
        return connection

    try:
        with closing(readonly_connect(url, connect_timeout=10)) as connection:
            with connection, connection.cursor() as cursor:
                cursor.execute("SHOW transaction_read_only")
                assert cursor.fetchone()[0] == "on"
                cursor.execute(
                    'SELECT status, count(*) FROM public."VenueBooking" GROUP BY status ORDER BY status'
                )
                status_counts = cursor.fetchall()
                cursor.execute(
                    'SELECT venue_id, requested_start_time FROM public."VenueBooking" WHERE venue_id IS NOT NULL AND requested_start_time IS NOT NULL ORDER BY requested_start_time LIMIT 1'
                )
                sample = cursor.fetchone()
        venue_id, start = sample or (
            "00000000-0000-0000-0000-000000000001",
            datetime(2026, 10, 1),
        )
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        query = {
            "venueId": str(venue_id),
            "dateFrom": start.isoformat(),
            "dateTo": (start + timedelta(days=42)).isoformat(),
        }
        monkeypatch.setattr("app.models.psycopg2.connect", readonly_connect)
        app = create_app(
            {"TESTING": True, "DATABASE_URL": url, "CALENDAR_DEV_MODE": True}
        )
        client = app.test_client()
        outcomes = {}
        for role in (
            "Event Coordinator",
            "Venue Staff",
            "Technical Support",
            "Technical Support Staff",
            "Event Organiser",
            "Attendee",
        ):
            response = client.get(
                "/venue-bookings",
                query_string=query,
                headers={
                    "X-Dev-User-Id": "00000000-0000-0000-0000-000000000001",
                    "X-Dev-Role": role,
                },
            )
            expected = 403 if role in ("Event Organiser", "Attendee") else 200
            assert response.status_code == expected
            bookings = response.json.get("bookings", [])
            assert all(
                b["requestedStartTime"].endswith("+08:00")
                and b["requestedEndTime"].endswith("+08:00")
                and b["blocksSelection"] == (b["status"] == "Approved")
                for b in bookings
            )
            outcomes[role] = {"http": response.status_code, "count": len(bookings)}
        assert client.get("/venue-bookings", query_string=query).status_code == 401
        app.config["CALENDAR_DEV_MODE"] = False
        assert client.get("/venue-bookings", query_string=query).status_code == 503
        print(
            {
                "read_only": "on",
                "status_counts": status_counts,
                "sampled_existing_booking": bool(sample),
                "outcomes": outcomes,
                "missing_identity": 401,
                "disabled": 503,
            }
        )
    except Exception as error:
        # Never expose connection strings, SQL rows or identities in failure output.
        pytest.fail(
            f"Read-only smoke failed ({type(error).__name__}); inspect locally without sharing credentials.",
            pytrace=False,
        )
