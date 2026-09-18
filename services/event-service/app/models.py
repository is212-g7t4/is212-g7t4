import json
from contextlib import closing
from datetime import UTC, datetime
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
    description, purpose, decision, _ = unpack_decision(value)
    return description, purpose, decision


def unpack_decision(value):
    # Legacy plain descriptions remain readable. Only unpack our versioned envelope.
    try:
        details = json.loads(value or "")
    except (ValueError, TypeError):
        return value or "", "", None, []
    if (
        isinstance(details, dict)
        and details.get("_connectsphere") == "event-submission-v1"
        and isinstance(details.get("description"), str)
        and isinstance(details.get("purpose"), str)
    ):
        decision = details.get("decision")
        if not isinstance(decision, dict):
            approval = details.get(
                "approval"
            )  ## This can be removed if old format of events are gone/. This was added to support the old format of events that were submitted before the decision field was added.
            if isinstance(approval, dict):
                decision = {
                    "status": "Approved",
                    "coordinatorId": approval.get("coordinatorId"),
                    "decidedAt": approval.get("approvedAt"),
                    "reason": None,
                }
        history = details.get("decisionHistory")
        if not isinstance(history, list):
            history = [decision] if decision else []
        return details["description"], details["purpose"], decision, history
    return value or "", "", None, []


def serialize(row):
    result = {key: row[column] or "" for key, column in FIELDS.items()}
    result["description"], result["purpose"], decision, history = unpack_decision(
        row["description"]
    )
    for key in ("preferredStartDate", "preferredEndDate"):
        result[key] = result[key].isoformat() if result[key] else ""
    result["expectedAttendance"] = str(row["expected_attendance"] or "")
    result.update(
        id=str(row["event_id"]),
        status=row["status"],
        # submission_date is timestamp WITHOUT time zone, stored as UTC by this service.
        submittedAt=row["submission_date"].replace(tzinfo=UTC).isoformat()
        if row["submission_date"]
        else None,
        coordinatorId=str(row["coordinator_id"]) if row.get("coordinator_id") else None,
        decision=decision,
        decisionHistory=history,
    )
    return result


def submit_event(database_url, data):
    event_id = str(uuid4())
    stored = {
        **data,
        "description": json.dumps(
            {
                "_connectsphere": "event-submission-v1",
                "description": data["description"],
                "purpose": data["purpose"],
            },
            ensure_ascii=False,
        ),
        "expectedAttendance": int(data["expectedAttendance"]),
    }
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


class RejectionReasonError(Exception):
    pass


def decide_event(database_url, event_id, coordinator_id, status, reason=None):
    if status == "Rejected" and not isinstance(reason, str):
        raise RejectionReasonError
    reason_text = reason.strip() if isinstance(reason, str) else None
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
            if (
                not event["coordinator_id"]
                or str(event["coordinator_id"]) != coordinator_id
            ):
                raise EventNotAssignedError
            if event["status"] != "Submitted":
                raise EventNotSubmittedError

            description, purpose, _, history = unpack_decision(event["description"])
            if status == "Rejected" and not reason_text:
                raise RejectionReasonError
            decided_at = datetime.now(UTC).isoformat()
            decision = {
                "status": status,
                "coordinatorId": coordinator_id,
                "decidedAt": decided_at,
                "reason": reason_text,
            }
            decision_history = [*history, decision]
            cursor.execute(
                f"""UPDATE public.event_service
                    SET status = %s,
                        description = jsonb_build_object(
                            '_connectsphere', 'event-submission-v1',
                            'description', %s,
                            'purpose', %s,
                            'decision', jsonb_build_object(
                                'status', %s,
                                'coordinatorId', %s,
                                'decidedAt', %s,
                                'reason', %s
                            ),
                            'decisionHistory', %s::jsonb
                        )::text
                    WHERE event_id = %s
                    RETURNING event_id, {COLUMNS}, status, submission_date, coordinator_id""",
                [
                    status,
                    description,
                    purpose,
                    status,
                    coordinator_id,
                    decided_at,
                    reason_text,
                    json.dumps(decision_history),
                    event_id,
                ],
            )
            decided = cursor.fetchone()
    return serialize(decided)


def approve_event(database_url, event_id, coordinator_id):
    return decide_event(database_url, event_id, coordinator_id, "Approved")


def reject_event(database_url, event_id, coordinator_id, reason):
    return decide_event(database_url, event_id, coordinator_id, "Rejected", reason)
