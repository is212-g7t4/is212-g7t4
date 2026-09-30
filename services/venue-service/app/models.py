from contextlib import closing

import psycopg2
from psycopg2.extras import RealDictCursor

COLUMNS = "venue_id, venue_name, location, max_capacity, facilities, accessibility, supported_layouts, operational_status"


def _names(value):
    """Normalise a jsonb facilities/layouts column into a list of names.

    Live rows store facilities as an object of booleans
    (`{"wifi": true, "kitchen": false}`); the seed script writes a plain
    array. Accept both so the UI only ever sees a list of strings.
    """
    if isinstance(value, dict):
        return sorted(str(key) for key, enabled in value.items() if enabled)
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def serialize(row):
    return {
        "id": str(row["venue_id"]),
        "name": row["venue_name"] or "",
        "location": row["location"] or "",
        "capacity": row["max_capacity"],
        "facilities": _names(row["facilities"]),
        "accessibility": row["accessibility"] or "",
        "supportedLayouts": _names(row["supported_layouts"]),
        "status": row["operational_status"] or "Unknown",
    }


def list_venues(database_url):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {COLUMNS} FROM public."Venue"
                    ORDER BY venue_name ASC, venue_id ASC"""
            )
            return [serialize(row) for row in cursor.fetchall()]


class VenueNotFoundError(Exception):
    pass


def get_venue(database_url, venue_id):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {COLUMNS} FROM public."Venue" WHERE venue_id = %s""",
                [venue_id],
            )
            venue = cursor.fetchone()
    if not venue:
        raise VenueNotFoundError
    return serialize(venue)
