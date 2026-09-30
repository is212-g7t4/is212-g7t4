from contextlib import closing

import psycopg2
from psycopg2.extras import RealDictCursor

COLUMNS = "registration_id, event_id, attendee_id, registration_date, status, attendee_name, attendee_email, attendee_organization"


def serialize(row):
    return {
        "registration_id": str(row["registration_id"]),
        "event_id": str(row["event_id"]) if row.get("event_id") else None,
        "attendee_id": str(row["attendee_id"]) if row.get("attendee_id") else None,
        "registration_date": row["registration_date"].isoformat() if row["registration_date"] else None,
        "status": row["status"] or "",
        "attendee_name": row["attendee_name"] or "",
        "attendee_email": row["attendee_email"] or "",
        "attendee_organization": row["attendee_organization"] or "",
    }


def list_registrations(database_url, event_id):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {COLUMNS} FROM public."Registration" WHERE event_id = %s
                    ORDER BY registration_date ASC NULLS LAST, registration_id ASC""",
                [event_id],
            )
            return [serialize(row) for row in cursor.fetchall()]
