"""Seed a few dummy venues into the Venue catalogue.

Safe to run repeatedly: it upserts by `venue_name` instead of inserting
duplicates on every run.

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

VENUES = [
    {
        "venue_name": "Innovation Lab",
        "location": "West Wing, Level 3",
        "max_capacity": 60,
        "facilities": ["Projector", "Whiteboards", "Video conferencing"],
        "accessibility": "Wheelchair accessible",
        "supported_layouts": ["Classroom", "Boardroom"],
        "operational_status": "Operational",
    },
    {
        "venue_name": "Rooftop Terrace",
        "location": "Main Building, Rooftop",
        "max_capacity": 150,
        "facilities": ["Outdoor lighting", "PA system"],
        "accessibility": "Lift access, no stairs",
        "supported_layouts": ["Standing reception", "Banquet"],
        "operational_status": "Under Maintenance",
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
