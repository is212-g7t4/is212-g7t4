from contextlib import closing

import psycopg2
from psycopg2.extras import Json, RealDictCursor

COLUMNS = "venue_id, venue_name, location, max_capacity, facilities, accessibility, supported_layouts, operational_status"

# SCRUM-26: accessibility is free text in the catalogue, so a checkbox key is
# matched against the phrases the live rows actually use. A key matches when
# any of its phrases appears in the text (case-insensitively).
ACCESSIBILITY_KEYWORDS = {
    "wheelchair": ["wheelchair"],
    "lift": ["lift", "elevator"],
    "step_free": ["level entrance", "no stairs"],
    "hearing_loop": ["hearing loop"],
    "accessible_washroom": ["accessible washroom"],
}


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


def matches(venue, criteria):
    """SCRUM-26: does this serialized venue meet the event's requirements?

    This is the suitability-check computation this service owns. It runs in
    Python rather than SQL: the catalogue is small, every criterion reads
    plainly here, and it can be unit-tested without a database. Criteria keys
    are all optional — `min_capacity`, `location`, `layout`, `facilities`
    (list) and `accessibility` (list of ACCESSIBILITY_KEYWORDS keys).
    """
    min_capacity = criteria.get("min_capacity")
    if min_capacity is not None:
        # A venue with no stated capacity can't be confirmed to fit, so it is out.
        if venue["capacity"] is None or venue["capacity"] < min_capacity:
            return False

    location = criteria.get("location")
    if location and location.casefold() not in venue["location"].casefold():
        return False

    layout = criteria.get("layout")
    if layout and not any(
        layout.casefold() == supported.casefold() for supported in venue["supportedLayouts"]
    ):
        return False

    available = {facility.casefold() for facility in venue["facilities"]}
    if any(required.casefold() not in available for required in criteria.get("facilities") or []):
        return False

    text = venue["accessibility"].casefold()
    return all(
        any(phrase in text for phrase in ACCESSIBILITY_KEYWORDS[key])
        for key in criteria.get("accessibility") or []
    )


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


class DuplicateVenueNameError(Exception):
    pass


def create_venue(database_url, details):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """SELECT 1 FROM public."Venue" WHERE venue_name = %s""",
                [details["name"]],
            )
            if cursor.fetchone():
                raise DuplicateVenueNameError
            cursor.execute(
                f"""INSERT INTO public."Venue"
                    (venue_name, location, max_capacity, facilities,
                     accessibility, supported_layouts, operational_status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING {COLUMNS}""",
                [
                    details["name"],
                    details["location"],
                    details["capacity"],
                    Json({name: True for name in details["facilities"]}),
                    details["accessibility"],
                    Json(details["supportedLayouts"]),
                    details["status"],
                ],
            )
            saved = cursor.fetchone()
    return serialize(saved)


def update_venue(database_url, venue_id, details):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """SELECT 1 FROM public.\"Venue\"
                   WHERE venue_name = %s AND venue_id <> %s""",
                [details["name"], venue_id],
            )
            if cursor.fetchone():
                raise DuplicateVenueNameError
            cursor.execute(
                f"""UPDATE public.\"Venue\"
                    SET venue_name = %s, location = %s, max_capacity = %s,
                        facilities = %s, accessibility = %s,
                        supported_layouts = %s, operational_status = %s
                    WHERE venue_id = %s
                    RETURNING {COLUMNS}""",
                [
                    details["name"],
                    details["location"],
                    details["capacity"],
                    Json({name: True for name in details["facilities"]}),
                    details["accessibility"],
                    Json(details["supportedLayouts"]),
                    details["status"],
                    venue_id,
                ],
            )
            saved = cursor.fetchone()
    if not saved:
        raise VenueNotFoundError
    return serialize(saved)


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
