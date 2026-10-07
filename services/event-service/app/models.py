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
    "venueId": "venue_id",
    "venueRequirements": "venue_requirements",
    "accessibilityNeeds": "accessibility_needs",
    "equipmentRequirements": "equipment_requirements",
    "registrationNeeds": "registration_needs",
}
COLUMNS = ", ".join(FIELDS.values())
ROW_COLUMNS = (
    f"event_id, {COLUMNS}, status, submission_date, coordinator_id, organiser_id"
)

# Event lifecycle, in order. Defined once here so the safety-check stories
# (SCRUM-149/150/151/153) reuse these names instead of re-typing the strings.
PRE_SAFETY_STATUSES = ("Submitted", "Under Review", "Approved", "Rejected")
# Set only by the safety-check workflow (SCRUM-149/150/151), never by PATCH /progress.
SAFETY_STATUSES = (
    "Pending Safety Check",
    "Confirmed",  # passed the Operational Safety Check — this is the preparation stage
    "Safety Changes Requested",
    "Cancelled",  # safety rejection
)
ALL_STATUSES = (*PRE_SAFETY_STATUSES, *SAFETY_STATUSES)

# SCRUM-152: 'Confirmed' *is* "in preparation" — an event that has passed its
# Operational Safety Check is the one that may proceed. So the gate is simply
# that nothing here can move an event into 'Confirmed'; only the safety
# workflow does that (SCRUM-150, and SCRUM-153 AC2).
PREPARATION_STATUS = "Confirmed"

# What PATCH /progress accepts, keyed by the event's current status. A "self"
# transition is a save that keeps the status and updates the action details, so
# every status lists itself. The frontend's src/features/event/eventStatus.ts
# mirrors this table.
ALLOWED_TRANSITIONS = {
    "Submitted": {"Submitted", "Under Review"},
    "Under Review": {"Under Review", "Approved", "Rejected"},
    # SCRUM-152: `Approved -> Confirmed` was removed. The next step is
    # SCRUM-149's submit-for-safety-check, not this endpoint.
    "Approved": {"Approved"},
    "Rejected": {"Rejected"},
    "Pending Safety Check": {"Pending Safety Check"},
    "Confirmed": {"Confirmed"},
    "Safety Changes Requested": {"Safety Changes Requested"},
    "Cancelled": {"Cancelled"},
}

# Why an event at each status can't progress to 'Confirmed' yet (SCRUM-152 AC1).
# The UI shows these verbatim, so they are whole sentences; it only surfaces the
# ones a coordinator can act on (see showsSafetyHint in eventStatus.ts).
SAFETY_BLOCK_MESSAGES = {
    "Submitted": (
        "This event must be approved and pass its Operational Safety Check "
        "before it can progress to Confirmed."
    ),
    "Under Review": (
        "This event must be approved and pass its Operational Safety Check "
        "before it can progress to Confirmed."
    ),
    "Approved": (
        "Submit this event for safety check for it to progress to Confirmed."
    ),
    "Rejected": "This event was rejected, so it can't progress to Confirmed.",
    "Pending Safety Check": "This event is waiting for the Safety Officer's decision.",
    "Safety Changes Requested": (
        "The Safety Officer has requested changes that must be made and resubmitted."
    ),
    "Cancelled": (
        "This event was cancelled after its safety check, so it can't progress to Confirmed."
    ),
}
DEFAULT_SAFETY_BLOCK_MESSAGE = (
    "This event must pass its Operational Safety Check before it can progress to Confirmed."
)


def safety_block_message(current_status):
    """Why an event at `current_status` can't progress to 'Confirmed' (SCRUM-152 AC1)."""
    return SAFETY_BLOCK_MESSAGES.get(current_status, DEFAULT_SAFETY_BLOCK_MESSAGE)


def unpack_description(value):
    description, purpose, decision, _ = unpack_decision(value)
    return description, purpose, decision


def unpack_decision(value):
    description, purpose, decision, history, _, _ = unpack_metadata(value)
    return description, purpose, decision, history


def unpack_metadata(value):
    try:
        details = json.loads(value or "")
    except (ValueError, TypeError):
        return value or "", "", None, [], "", []
    if (
        isinstance(details, dict)
        and details.get("_connectsphere") == "event-submission-v1"
        and isinstance(details.get("description"), str)
        and isinstance(details.get("purpose"), str)
    ):
        decision = details.get("decision")
        if not isinstance(decision, dict):
            approval = details.get("approval")
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
        action_details = details.get("actionDetails")
        if not isinstance(action_details, str):
            action_details = ""
        action_history = details.get("actionHistory")
        if not isinstance(action_history, list):
            action_history = []
        return (
            details["description"],
            details["purpose"],
            decision,
            history,
            action_details,
            action_history,
        )
    return value or "", "", None, [], "", []


def serialize(row):
    result = {key: row[column] or "" for key, column in FIELDS.items()}
    (
        result["description"],
        result["purpose"],
        decision,
        history,
        action_details,
        action_history,
    ) = unpack_metadata(row["description"])
    for key in ("preferredStartDate", "preferredEndDate"):
        result[key] = result[key].isoformat() if result[key] else ""
    result["expectedAttendance"] = str(row["expected_attendance"] or "")
    result["venueId"] = str(row["venue_id"]) if row.get("venue_id") else ""
    result.update(
        id=str(row["event_id"]),
        status=row["status"],
        submittedAt=row["submission_date"].replace(tzinfo=UTC).isoformat()
        if row["submission_date"]
        else None,
        coordinatorId=str(row["coordinator_id"]) if row.get("coordinator_id") else None,
        organiserId=str(row["organiser_id"]) if row.get("organiser_id") else None,
        decision=decision,
        decisionHistory=history,
        actionDetails=action_details,
        actionHistory=action_history,
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
        # Empty string means "no venue chosen yet" — must be NULL, not "", for the uuid column.
        "venueId": data.get("venueId") or None,
    }
    values = [stored[key] for key in FIELDS]
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""INSERT INTO public."Event"
                    (event_id, {COLUMNS}, status, submission_date, organiser_id)
                    VALUES (%s, {", ".join(["%s"] * len(FIELDS))},
                            'Submitted', timezone('UTC', CURRENT_TIMESTAMP), %s)
                    RETURNING {ROW_COLUMNS}""",
                [event_id, *values, data.get("organiserId") or None],
            )
            saved = cursor.fetchone()
    return serialize(saved)


def list_submitted(database_url, coordinator_id=None, is_manager=False):
    if is_manager or coordinator_id is None:
        query = f"""SELECT {ROW_COLUMNS}
                    FROM public."Event" WHERE status IN ('Submitted', 'Under Review')
                    ORDER BY submission_date ASC NULLS LAST, event_id ASC"""
        params = []
    else:
        query = f"""SELECT {ROW_COLUMNS}
                    FROM public."Event"
                    WHERE status IN ('Submitted', 'Under Review') AND coordinator_id = %s
                    ORDER BY submission_date ASC NULLS LAST, event_id ASC"""
        params = [coordinator_id]

    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, params)
            return [serialize(row) for row in cursor.fetchall()]


class EventNotFoundError(Exception):
    pass


class EventNotAssignedError(Exception):
    pass


class EventNotOwnedError(Exception):
    pass


class EventNotSubmittedError(Exception):
    pass


class RejectionReasonError(Exception):
    pass


class InvalidStatusTransitionError(Exception):
    pass


class SafetyApprovalRequiredError(Exception):
    """SCRUM-152 AC1: the event has not passed its Operational Safety Check."""

    def __init__(self, current_status):
        super().__init__(current_status)
        self.current_status = current_status

    @property
    def message(self):
        return safety_block_message(self.current_status)


def update_event_coordinator(database_url, event_id, coordinator_id):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            # Only ever reaches 'Under Review'. Keep it that way: anything that
            # can set 'Confirmed' or a later stage must go through the safety
            # gate in update_event_progress (SCRUM-152).
            cursor.execute(
                f"""UPDATE public."Event"
                    SET coordinator_id = %s,
                        status = CASE WHEN status = 'Submitted' THEN 'Under Review' ELSE status END
                    WHERE event_id = %s
                    RETURNING {ROW_COLUMNS}""",
                [coordinator_id, event_id],
            )
            assigned = cursor.fetchone()
            if not assigned:
                raise EventNotFoundError
    return serialize(assigned)


def list_events(
    database_url,
    coordinator_id,
    status=None,
    venue=None,
    date_from=None,
    date_to=None,
    is_manager=False,
    venue_id=None,
):
    if is_manager:
        conditions = []
        params = []
    else:
        conditions = ["coordinator_id = %s"]
        params = [coordinator_id]
    if status:
        conditions.append("status = %s")
        params.append(status)
    if venue:
        escaped = venue.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append("venue_requirements ILIKE %s ESCAPE '\\'")
        params.append(f"%{escaped}%")
    if venue_id:
        conditions.append("venue_id = %s")
        params.append(venue_id)
    if date_to:
        conditions.append("preferred_start_date <= %s")
        params.append(date_to)
    if date_from:
        conditions.append("preferred_end_date >= %s")
        params.append(date_from)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {ROW_COLUMNS}
                    FROM public."Event"
                    {where_clause}
                    ORDER BY preferred_start_date ASC NULLS LAST, event_id ASC""",
                params,
            )
            return [serialize(row) for row in cursor.fetchall()]


def list_confirmed_events(database_url):
    """Return confirmed events for the attendee registration catalogue."""
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {ROW_COLUMNS}
                    FROM public."Event"
                    WHERE status = 'Confirmed'
                    ORDER BY preferred_start_date ASC NULLS LAST, event_id ASC"""
            )
            return [serialize(row) for row in cursor.fetchall()]


def list_organiser_events(database_url, organiser_id):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {ROW_COLUMNS}
                    FROM public."Event"
                    WHERE organiser_id = %s
                    ORDER BY preferred_start_date ASC NULLS LAST, event_id ASC""",
                [organiser_id],
            )
            return [serialize(row) for row in cursor.fetchall()]


def get_organiser_event(database_url, event_id, organiser_id):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {ROW_COLUMNS}
                    FROM public."Event"
                    WHERE event_id = %s""",
                [event_id],
            )
            event = cursor.fetchone()
    if not event:
        raise EventNotFoundError
    if not event["organiser_id"] or str(event["organiser_id"]) != organiser_id:
        raise EventNotOwnedError
    return serialize(event)


def get_event(database_url, event_id, coordinator_id, is_manager=False):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {ROW_COLUMNS}
                    FROM public."Event"
                    WHERE event_id = %s""",
                [event_id],
            )
            event = cursor.fetchone()
    if not event:
        raise EventNotFoundError
    if not is_manager and (
        not event["coordinator_id"] or str(event["coordinator_id"]) != coordinator_id
    ):
        raise EventNotAssignedError
    return serialize(event)


def update_event_progress(database_url, event_id, coordinator_id, status, action_details):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {ROW_COLUMNS}
                    FROM public."Event"
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
            # SCRUM-152 AC1: nothing here may move an event into 'Confirmed'
            # (the preparation stage) — only the safety workflow can, by
            # approving the Operational Safety Check. Runs after the assignment
            # check, so a caller who isn't the assigned coordinator still gets
            # 403 and learns nothing about the event's stage; and inside the
            # FOR UPDATE lock, so a Safety Officer's decision landing at the
            # same moment can't leave this acting on a stale status.
            if status == PREPARATION_STATUS and event["status"] != PREPARATION_STATUS:
                raise SafetyApprovalRequiredError(event["status"])
            if status not in ALLOWED_TRANSITIONS.get(event["status"], {event["status"]}):
                raise InvalidStatusTransitionError

            (
                description,
                purpose,
                decision,
                decision_history,
                _,
                action_history,
            ) = unpack_metadata(event["description"])
            recorded_at = datetime.now(UTC).isoformat()
            action = {
                "status": status,
                "details": action_details,
                "coordinatorId": coordinator_id,
                "recordedAt": recorded_at,
            }
            action_history = [*action_history, action]

            if status != event["status"]:
                if status in ("Approved", "Rejected"):
                    decision = {
                        "status": status,
                        "coordinatorId": coordinator_id,
                        "decidedAt": recorded_at,
                        "reason": action_details if status == "Rejected" else None,
                    }
                    decision_history = [*decision_history, decision]
                elif status in ("Submitted", "Under Review"):
                    decision = None

            metadata = {
                "_connectsphere": "event-submission-v1",
                "description": description,
                "purpose": purpose,
                "decision": decision,
                "decisionHistory": decision_history,
                "actionDetails": action_details,
                "actionHistory": action_history,
            }
            cursor.execute(
                f"""UPDATE public."Event"
                    SET status = %s, description = %s
                    WHERE event_id = %s
                    RETURNING {ROW_COLUMNS}""",
                [status, json.dumps(metadata, ensure_ascii=False), event_id],
            )
            updated = cursor.fetchone()
    return serialize(updated)


def decide_event(database_url, event_id, coordinator_id, status, reason=None):
    # Only 'Approved'/'Rejected', only from 'Submitted'/'Under Review', so this
    # can't reach 'Confirmed' or preparation. Don't widen it without adding the
    # safety gate from update_event_progress (SCRUM-152).
    if status == "Rejected" and not isinstance(reason, str):
        raise RejectionReasonError
    reason_text = reason.strip() if isinstance(reason, str) else None

    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {ROW_COLUMNS}
                    FROM public."Event"
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
            if event["status"] not in ("Submitted", "Under Review"):
                raise EventNotSubmittedError
            if status == "Rejected" and not reason_text:
                raise RejectionReasonError

            (
                description,
                purpose,
                _,
                history,
                action_details,
                action_history,
            ) = unpack_metadata(event["description"])
            decided_at = datetime.now(UTC).isoformat()
            decision = {
                "status": status,
                "coordinatorId": coordinator_id,
                "decidedAt": decided_at,
                "reason": reason_text,
            }
            decision_history = [*history, decision]
            cursor.execute(
                f"""UPDATE public."Event"
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
                            'decisionHistory', %s::jsonb,
                            'actionDetails', %s,
                            'actionHistory', %s::jsonb
                        )::text
                    WHERE event_id = %s
                    RETURNING {ROW_COLUMNS}""",
                [
                    status,
                    description,
                    purpose,
                    status,
                    coordinator_id,
                    decided_at,
                    reason_text,
                    json.dumps(decision_history),
                    action_details,
                    json.dumps(action_history),
                    event_id,
                ],
            )
            decided = cursor.fetchone()
    return serialize(decided)


def approve_event(database_url, event_id, coordinator_id):
    return decide_event(database_url, event_id, coordinator_id, "Approved")


def reject_event(database_url, event_id, coordinator_id, reason):
    return decide_event(database_url, event_id, coordinator_id, "Rejected", reason)
