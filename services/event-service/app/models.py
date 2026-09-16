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
        return value or "", "", None
    if (isinstance(details, dict) and details.get("_connectsphere") == "event-submission-v1"
            and isinstance(details.get("description"), str) and isinstance(details.get("purpose"), str)):
        approval = details.get("approval")
        return details["description"], details["purpose"], approval if isinstance(approval, dict) else None
    return value or "", "", None


def serialize(row):
    result = {key: row[column] or "" for key, column in FIELDS.items()}
    result["description"], result["purpose"], approval = unpack_description(row["description"])
    for key in ("preferredStartDate", "preferredEndDate"):
        result[key] = result[key].isoformat() if result[key] else ""
    result["expectedAttendance"] = str(row["expected_attendance"] or "")
    result.update(
        id=str(row["event_id"]),
        status=row["status"],
        # submission_date is timestamp WITHOUT time zone, stored as UTC by this service.
        submittedAt=row["submission_date"].replace(tzinfo=UTC).isoformat()
        if row["submission_date"] else None,
        coordinatorId=str(row["coordinator_id"]) if row.get("coordinator_id") else None,
        approvedBy=approval.get("coordinatorId") if approval else None,
        approvedAt=approval.get("approvedAt") if approval else None,
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
                    RETURNING event_id, {COLUMNS}, status, submission_date, coordinator_id""",
                [event_id, *values],
            )
            saved = cursor.fetchone()
    # The connection context commits before success is returned.
    return serialize(saved)


def list_submitted(database_url):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT event_id, {COLUMNS}, status, submission_date, coordinator_id
                    FROM public.event_service WHERE status = 'Submitted'
                    ORDER BY submission_date ASC NULLS LAST, event_id ASC"""
            )
            return [serialize(row) for row in cursor.fetchall()]


class EventNotFoundError(Exception):
    pass


class EventNotAssignedError(Exception):
    pass


class EventNotSubmittedError(Exception):
    pass


def update_event_coordinator(database_url, event_id, coordinator_id):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""UPDATE public.event_service
                    SET coordinator_id = %s
                    WHERE event_id = %s
                    RETURNING event_id, {COLUMNS}, status, submission_date, coordinator_id""",
                [coordinator_id, event_id],
            )
            assigned = cursor.fetchone()
            if not assigned:
                raise EventNotFoundError
    return serialize(assigned)


def approve_event(database_url, event_id, coordinator_id):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT event_id, {COLUMNS}, status, submission_date, coordinator_id
                    FROM public.event_service
                    WHERE event_id = %s
                    FOR UPDATE""",
                [event_id],
            )
            event = cursor.fetchone()
            if not event:
                raise EventNotFoundError
            if not event["coordinator_id"] or str(event["coordinator_id"]) != coordinator_id:
                raise EventNotAssignedError
            if event["status"] != "Submitted":
                raise EventNotSubmittedError

            description, purpose, _ = unpack_description(event["description"])
            cursor.execute(
                f"""UPDATE public.event_service
                    SET status = 'Approved',
                        description = jsonb_build_object(
                            '_connectsphere', 'event-submission-v1',
                            'description', %s,
                            'purpose', %s,
                            'approval', jsonb_build_object(
                                'coordinatorId', %s,
                                'approvedAt', to_char(
                                    timezone('UTC', CURRENT_TIMESTAMP),
                                    'YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"'
                                )
                            )
                        )::text
                    WHERE event_id = %s
                    RETURNING event_id, {COLUMNS}, status, submission_date, coordinator_id""",
                [description, purpose, coordinator_id, event_id],
            )
            approved = cursor.fetchone()
    return serialize(approved)

