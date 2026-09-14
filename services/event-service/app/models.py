import json
from contextlib import closing
from datetime import UTC
from uuid import uuid4

import psycopg2
from psycopg2.extras import RealDictCursor

# Only columns owned by Event Service; no queries to other services' tables.
FIELDS = {
    "eventName": "event_name",
    "description": "description",
    "preferredStartDate": "preferred_start_date",
    "preferredEndDate": "preferred_end_date",
    "expectedAttendance": "expected_attendance",
    "venueRequirements": "venue_requirements",
    "accessibilityNeeds": "accessibility_needs",
    "equipmentRequirements": "equipment_requirements",
    "registrationNeeds": "registration_needs",
}
COLUMNS = ", ".join(FIELDS.values())


def unpack_description(value):
    # Legacy plain descriptions remain readable. Only unpack our versioned envelope.
    try:
        details = json.loads(value or "")
    except (ValueError, TypeError):
        return value or "", ""
    if (isinstance(details, dict) and details.get("_connectsphere") == "event-submission-v1"
            and isinstance(details.get("description"), str) and isinstance(details.get("purpose"), str)):
        return details["description"], details["purpose"]
    return value or "", ""


def serialize(row):
    result = {key: row[column] or "" for key, column in FIELDS.items()}
    result["description"], result["purpose"] = unpack_description(row["description"])
    for key in ("preferredStartDate", "preferredEndDate"):
        result[key] = result[key].isoformat() if result[key] else ""
    result["expectedAttendance"] = str(row["expected_attendance"] or "")
    result.update(
        id=str(row["event_id"]),
        status=row["status"],
        # submission_date is timestamp WITHOUT time zone, stored as UTC by this service.
        submittedAt=row["submission_date"].replace(tzinfo=UTC).isoformat()
        if row["submission_date"] else None,
    )
    return result


def submit_event(database_url, data):
    event_id = str(uuid4())
    stored = {**data, "description": json.dumps({
        "_connectsphere": "event-submission-v1",
        "description": data["description"],
        "purpose": data["purpose"],
    }, ensure_ascii=False), "expectedAttendance": int(data["expectedAttendance"])}
    values = [stored[key] for key in FIELDS]
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""INSERT INTO public.event_service
                    (event_id, {COLUMNS}, status, submission_date)
                    VALUES (%s, {", ".join(["%s"] * len(FIELDS))},
                            'Submitted', timezone('UTC', CURRENT_TIMESTAMP))
                    RETURNING event_id, {COLUMNS}, status, submission_date""",
                [event_id, *values],
            )
            saved = cursor.fetchone()
    # The connection context commits before success is returned.
    return serialize(saved)


def list_submitted(database_url):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT event_id, {COLUMNS}, status, submission_date
                    FROM public.event_service WHERE status = 'Submitted'
                    ORDER BY submission_date ASC NULLS LAST, event_id ASC"""
            )
            return [serialize(row) for row in cursor.fetchall()]

