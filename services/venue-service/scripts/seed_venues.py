"""Seed the Venue catalogue so a fresh database matches the live one.

Safe to run repeatedly: it upserts by `venue_name` instead of inserting
duplicates on every run.

Shape rules (must match what live Supabase rows and `app/models.py` expect):

- `facilities` is a **jsonb object of booleans** (`{"wifi": true}`), not an
  array. `serialize()` keeps only the keys whose value is true.
- `supported_layouts` is a **jsonb array of lowercase strings**.
- `operational_status` is one of `Available`, `Under Maintenance`, `Booked`.
  The older `Operational` value is not used anywhere any more.

The rows below are the 9 venues in live Supabase as of 30 Sep 2026, copied
verbatim, so running this against the live database changes nothing and a
fresh database gets the same catalogue.

Requires DATABASE_URL in the environment, loaded from
services/venue-service/.env — see .env.example.

Usage:
    cd services/venue-service
    uv run python scripts/seed_venues.py
"""

import os

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import Json

load_dotenv()

STATUSES = ("Available", "Under Maintenance", "Booked")

VENUES = [
    {
        "venue_name": "Auditorium",
        "location": "Level 1, Main Tower",
        "max_capacity": 300,
        "facilities": {"wifi": True, "stage": True, "av_system": True, "sound_system": True},
        "accessibility": "Wheelchair accessible, hearing loop",
        "supported_layouts": ["theatre"],
        "operational_status": "Under Maintenance",
    },
    {
        "venue_name": "Community Hall",
        "location": "Ground Floor, West Wing",
        "max_capacity": 220,
        "facilities": {"stage": True, "kitchen": True, "sound_system": True},
        "accessibility": "Wheelchair accessible, level entrance",
        "supported_layouts": ["theatre", "banquet", "workshop"],
        "operational_status": "Available",
    },
    {
        "venue_name": "Conference Room A",
        "location": "Level 5, Main Tower",
        "max_capacity": 40,
        "facilities": {"wifi": True, "projector": True, "whiteboard": True},
        "accessibility": "Wheelchair accessible",
        "supported_layouts": ["boardroom", "classroom"],
        "operational_status": "Booked",
    },
    {
        "venue_name": "Grand Ballroom",
        "location": "Level 3, Main Tower",
        "max_capacity": 500,
        "facilities": {"wifi": True, "stage": True, "av_system": True},
        "accessibility": "Wheelchair accessible, elevator access",
        "supported_layouts": ["theatre", "banquet", "classroom"],
        "operational_status": "Available",
    },
    {
        "venue_name": "Innovation Lab",
        "location": "Level 7, Main Tower",
        "max_capacity": 60,
        "facilities": {"wifi": True, "whiteboards": True, "movable_furniture": True},
        "accessibility": "Wheelchair accessible",
        "supported_layouts": ["workshop", "classroom"],
        "operational_status": "Available",
    },
    {
        "venue_name": "Rooftop Garden",
        "location": "Level 12, Main Tower",
        "max_capacity": 150,
        "facilities": {"wifi": True, "outdoor": True, "lighting": True},
        "accessibility": "Elevator access, no stairs",
        "supported_layouts": ["standing", "banquet"],
        "operational_status": "Available",
    },
    {
        "venue_name": "Rooftop Terrace",
        "location": "Level 12, Main Tower",
        "max_capacity": 120,
        "facilities": {"wifi": True, "outdoor": True, "power_outlets": True},
        "accessibility": "Lift access; accessible washroom nearby",
        "supported_layouts": ["standing", "banquet"],
        "operational_status": "Available",
    },
    {
        "venue_name": "Seminar Room C",
        "location": "Level 4, East Wing",
        "max_capacity": 100,
        "facilities": {"wifi": True, "projector": True, "sound_system": True},
        "accessibility": "Wheelchair accessible, hearing loop",
        "supported_layouts": ["theatre", "classroom", "boardroom"],
        "operational_status": "Available",
    },
    {
        "venue_name": "Training Room B",
        "location": "Level 5, Main Tower",
        "max_capacity": 80,
        "facilities": {"wifi": True, "projector": True, "whiteboard": True},
        "accessibility": "Wheelchair accessible",
        "supported_layouts": ["classroom", "workshop"],
        "operational_status": "Available",
    },
]

def seed(database_url):
    # Upsert manually by venue_name rather than relying on ON CONFLICT, since
    # there's no guarantee a unique constraint exists on that column yet.
    with psycopg2.connect(database_url, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            for venue in VENUES:
                params = {
                    **venue,
                    "facilities": Json(venue["facilities"]),
                    "supported_layouts": Json(venue["supported_layouts"]),
                }
                cursor.execute(
                    """SELECT venue_id FROM public."Venue" WHERE venue_name = %(venue_name)s""",
                    params,
                )
                existing = cursor.fetchone()
                if existing:
                    cursor.execute(
                        """UPDATE public."Venue" SET
                               location = %(location)s,
                               max_capacity = %(max_capacity)s,
                               facilities = %(facilities)s,
                               accessibility = %(accessibility)s,
                               supported_layouts = %(supported_layouts)s,
                               operational_status = %(operational_status)s
                           WHERE venue_name = %(venue_name)s""",
                        params,
                    )
                else:
                    cursor.execute(
                        """INSERT INTO public."Venue"
                            (venue_name, location, max_capacity, facilities,
                             accessibility, supported_layouts, operational_status)
                           VALUES (%(venue_name)s, %(location)s, %(max_capacity)s,
                                   %(facilities)s, %(accessibility)s,
                                   %(supported_layouts)s, %(operational_status)s)""",
                        params,
                    )


if __name__ == "__main__":
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set — copy .env.example to .env first.")
    seed(url)
    print(f"Seeded {len(VENUES)} venues.")
