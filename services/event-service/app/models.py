import json
import logging
from contextlib import closing
from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.extras import RealDictCursor, Json

# Safe both ways: validation.py imports nothing from here.
from app import validation

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
ROW_COLUMNS = (
    f"event_id, {COLUMNS}, status, submission_date, coordinator_id, organiser_id,"
    " assigned_by, assigned_at, previous_coordinator_id"
)

SINGAPORE = ZoneInfo("Asia/Singapore")


# The database stores TIMESTAMPTZ; the API works in naive Singapore local
# time. Convert at the boundary so neither side depends on the connection's
# session time zone.
def _aware(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        return value.replace(tzinfo=SINGAPORE)
    return value


def _local(value):
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(SINGAPORE).replace(tzinfo=None)
    return value


# Event lifecycle, in order. Defined once here so the safety-check stories
# (SCRUM-149/150/151/153) reuse these names instead of re-typing the strings.
PRE_SAFETY_STATUSES = (
    "Submitted",
    "Under Review",
    "Clarification Requested",
    "Approved",
    "Rejected",
)
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
# transition is a save that keeps the status and updates the action details.
# Clarification Requested is deliberately locked and lists no transition. The
# frontend's src/features/event/eventStatus.ts mirrors this table.
#
# Safety-workflow moves do NOT belong here — they live in SAFETY_TRANSITIONS
# below and are reachable only through PATCH /events/<id>/safety-status.
ALLOWED_TRANSITIONS = {
    "Submitted": {"Submitted", "Under Review"},
    "Under Review": {"Under Review", "Approved", "Rejected"},
    # Only the dedicated clarification response endpoint may leave this state.
    # An empty set also prevents PATCH /progress from changing action metadata
    # while the organiser is answering the coordinator's question.
    "Clarification Requested": set(),
    # SCRUM-152: `Approved -> Confirmed` was removed. The next step is
    # SCRUM-149's submit-for-safety-check, not this endpoint.
    "Approved": {"Approved"},
    "Rejected": {"Rejected"},
    "Pending Safety Check": {"Pending Safety Check"},
    "Confirmed": {"Confirmed"},
    "Safety Changes Requested": {"Safety Changes Requested"},
    "Cancelled": {"Cancelled"},
}

# Moves only the safety-check workflow may make, via PATCH /events/<id>/safety-status
# (Safety Check Service). SCRUM-149 adds the first; SCRUM-150 adds the second
# (-> Confirmed); SCRUM-151 adds the other two (-> Safety Changes Requested /
# Cancelled). 'Cancelled' has no entry: a rejected event can never move again
# (SCRUM-151 AC4). SCRUM-164 adds "Safety Changes Requested": {"Pending Safety Check"}.
SAFETY_TRANSITIONS = {
    "Approved": {"Pending Safety Check"},
    "Safety Changes Requested": {"Pending Safety Check"},
    "Pending Safety Check": {"Confirmed", "Safety Changes Requested", "Cancelled"},
    # SCRUM-153 AC1: a high-impact change withdraws the approval, so
    # 'Confirmed' gains exactly one way out. It is legal only together with
    # the edit that justifies it, which is why it is listed in
    # RECHECK_ONLY_MOVES below and `/safety-status` refuses it on its own.
    "Confirmed": {"Pending Safety Check"},
}

# Moves that are in SAFETY_TRANSITIONS but reachable only through
# `update_event_details` — the edit and the status move are one transaction, so
# the event can never go back to 'Pending Safety Check' without the
# high-impact change that caused it. `/safety-status` refuses these.
RECHECK_ONLY_MOVES = {("Confirmed", "Pending Safety Check")}

# SCRUM-153's field classification, shared with SCRUM-20 (which defines the
# same split and owns "edit event details"): its names are used here so its
# later contradiction checks reuse them rather than re-typing the strings.
# High-impact fields are the five details in SCRUM-153 AC1 whose change
# invalidates a safety review; low-impact ones are AC2's.
LOW_IMPACT_FIELDS = ("eventName", "description", "purpose", "registrationNeeds")
HIGH_IMPACT_FIELDS = (
    "preferredStartDate",
    "preferredEndDate",
    "expectedAttendance",
    "venueRequirements",
    "equipmentRequirements",
    "accessibilityNeeds",
)
EDITABLE_FIELDS = (*LOW_IMPACT_FIELDS, *HIGH_IMPACT_FIELDS)
COORDINATOR_LEAD_ROLE = "Event Coordinator Lead"

# Human labels for the history line and the UI (AC1's "told why"). Both date
# fields map to one label deliberately, so changing start and end together
# says "Date/time" once rather than twice.
FIELD_LABELS = {
    "preferredStartDate": "Date/time",
    "preferredEndDate": "Date/time",
    "expectedAttendance": "Expected attendance",
    "venueRequirements": "Venue requirements",
    "equipmentRequirements": "Equipment requirements",
    "accessibilityNeeds": "Accessibility needs",
    "eventName": "Event name",
    "description": "Description",
    "purpose": "Purpose",
    "registrationNeeds": "Registration needs",
}

# Statuses whose details a coordinator may still edit. 'Rejected' and
# 'Cancelled' are terminal — there is nothing left to prepare. 'Pending Safety
# Check' allows low-impact edits only: a high-impact change while the Safety
# Officer is mid-review would move the goalposts under them (SCRUM-153 Q3).
EDITABLE_STATUSES = (
    "Submitted",
    "Under Review",
    "Approved",
    "Safety Changes Requested",
    "Confirmed",
    "Pending Safety Check",
)

UNDER_SAFETY_REVIEW_MESSAGE = (
    "This event is waiting for its Operational Safety Check. Change date/time, "
    "attendance, venue, equipment or accessibility details after the Safety "
    "Officer's decision."
)


def field_labels(fields):
    """The distinct human labels for `fields`, in HIGH/LOW declaration order.

    Deduplicated, so a change to both date fields reads "Date/time" once
    (AC1's "told why"), and ordered by `EDITABLE_FIELDS` rather than by what
    the caller happened to send, so the same edit always reads the same way.
    """
    labels = []
    for field in EDITABLE_FIELDS:
        if field in fields and FIELD_LABELS[field] not in labels:
            labels.append(FIELD_LABELS[field])
    return labels


def _sentence_list(labels):
    """"A", "A and B", "A, B and C" — for the message AC1 shows the coordinator."""
    if len(labels) <= 1:
        return "".join(labels)
    return f"{', '.join(labels[:-1])} and {labels[-1]}"

# Stored verbatim in action-history entries' "areas"; mirrors the Safety
# Check Record Service's FLAG_AREAS (SCRUM-151).
SAFETY_FLAG_AREAS = ("venue arrangement", "technical arrangement", "event details")

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
    "Clarification Requested": (
        "This event is waiting for the Event Organiser's clarification response."
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
    description, purpose, decision, history, _, _, _ = unpack_metadata(value)
    return description, purpose, decision, history


def unpack_metadata(value):
    try:
        details = json.loads(value or "")
    except (ValueError, TypeError):
        return value or "", "", None, [], "", [], []
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
        clarification_history = details.get("clarificationHistory")
        if not isinstance(clarification_history, list):
            clarification_history = []
        return (
            details["description"],
            details["purpose"],
            decision,
            history,
            action_details,
            action_history,
            clarification_history,
        )
    return value or "", "", None, [], "", [], []


def serialize(row):
    result = {key: row[column] or "" for key, column in FIELDS.items()}
    (
        result["description"],
        result["purpose"],
        decision,
        history,
        action_details,
        action_history,
        clarification_history,
    ) = unpack_metadata(row["description"])
    for key in ("preferredStartDate", "preferredEndDate"):
        result[key] = _local(result[key]).isoformat() if result[key] else ""
    result["expectedAttendance"] = str(row["expected_attendance"] or "")
    result.update(
        id=str(row["event_id"]),
        status=row["status"],
        submittedAt=row["submission_date"].astimezone(UTC).isoformat()
        if row["submission_date"]
        else None,
        coordinatorId=str(row["coordinator_id"]) if row.get("coordinator_id") else None,
        organiserId=str(row["organiser_id"]) if row.get("organiser_id") else None,
        assignedBy=str(row["assigned_by"]) if row.get("assigned_by") else None,
        assignedAt=row["assigned_at"].astimezone(UTC).isoformat()
        if row.get("assigned_at")
        else None,
        previousCoordinatorId=str(row["previous_coordinator_id"])
        if row.get("previous_coordinator_id")
        else None,
        decision=decision,
        decisionHistory=history,
        actionDetails=action_details,
        actionHistory=action_history,
        clarificationHistory=clarification_history,
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
        "preferredStartDate": _aware(data["preferredStartDate"]),
        "preferredEndDate": _aware(data["preferredEndDate"]),
    }
    values = [stored[key] for key in FIELDS]
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""INSERT INTO public."Event"
                    (event_id, {COLUMNS}, status, submission_date, organiser_id)
                    VALUES (%s, {", ".join(["%s"] * len(FIELDS))},
                            'Submitted', now(), %s)
                    RETURNING {ROW_COLUMNS}""",
                [event_id, *values, data.get("organiserId") or None],
            )
            saved = cursor.fetchone()
    return serialize(saved)


def list_submitted(database_url, coordinator_id, view_all=False):
    if view_all:
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


def list_unassigned(database_url):
    """The Lead's queue: submitted requests no coordinator has been assigned.

    Assignment moves an event to 'Under Review', so it drops out of here."""
    query = f"""SELECT {ROW_COLUMNS}
                FROM public."Event"
                WHERE status = 'Submitted' AND coordinator_id IS NULL
                ORDER BY submission_date ASC NULLS LAST, event_id ASC"""
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query)
            return [serialize(row) for row in cursor.fetchall()]


# The Lead's workload view leaves out events whose coordinator work is over:
# 'Confirmed' (passed safety, in preparation), 'Rejected', and 'Cancelled'
# (safety rejection).
INACTIVE_STATUSES = ("Confirmed", "Rejected", "Cancelled")


def list_active_events(database_url):
    """Every active event, assigned or not, for the Lead's workload view."""
    query = f"""SELECT {ROW_COLUMNS}
                FROM public."Event"
                WHERE status NOT IN %s
                ORDER BY preferred_start_date ASC NULLS LAST, event_id ASC"""
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, [INACTIVE_STATUSES])
            return [serialize(row) for row in cursor.fetchall()]


class EventNotFoundError(Exception):
    pass


SUMMARY_COLUMNS = "event_id, event_name, status, coordinator_id, preferred_start_date, preferred_end_date"


def _summary(row):
    return {
        "id": str(row["event_id"]),
        "eventName": row["event_name"],
        "status": row["status"],
        "coordinatorId": str(row["coordinator_id"]) if row["coordinator_id"] else None,
        "startTime": _local(row["preferred_start_date"]).isoformat() if row["preferred_start_date"] else None,
        "endTime": _local(row["preferred_end_date"]).isoformat() if row["preferred_end_date"] else None,
    }


def list_event_summaries(database_url, event_ids):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f'SELECT {SUMMARY_COLUMNS} FROM public."Event" WHERE event_id = ANY(%s::uuid[])',
                [event_ids],
            )
            return [_summary(row) for row in cursor.fetchall()]


def list_overlapping_events(database_url, start, end, statuses, exclude_event_id=None):
    """Events in `statuses` whose window overlaps [start, end): other.start < end AND other.end > start."""
    query = (
        f'SELECT {SUMMARY_COLUMNS} FROM public."Event" '
        "WHERE status = ANY(%s) AND preferred_start_date < %s AND preferred_end_date > %s"
    )
    params = [list(statuses), _aware(end), _aware(start)]
    if exclude_event_id:
        query += " AND event_id <> %s"
        params.append(exclude_event_id)
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query + " ORDER BY preferred_start_date ASC, event_id ASC", params)
            return [_summary(row) for row in cursor.fetchall()]


class EventNotAssignedError(Exception):
    pass


class EventNotOwnedError(Exception):
    pass


class EventNotSubmittedError(Exception):
    pass


class RejectionReasonError(Exception):
    pass


class ClarificationNotAllowedError(Exception):
    def __init__(self, current_status):
        super().__init__(current_status)
        self.current_status = current_status


class ClarificationNotOpenError(Exception):
    pass


class InvalidStatusTransitionError(Exception):
    """PATCH /progress raises this bare; the safety endpoint names the status
    it refused to move from, so the composite can report it (SCRUM-149)."""

    def __init__(self, current_status=None):
        super().__init__(current_status)
        self.current_status = current_status


class SafetyCheckAlreadyPendingError(Exception):
    """SCRUM-149 AC4: the event is already waiting for its safety check."""


class StaleSafetyCheckError(Exception):
    """SCRUM-150 AC3: the round being approved isn't the one the event has open.

    Stops a stale or made-up round from confirming the event, with no call to
    another service: the latest 'Pending Safety Check' action's safetyCheckId
    must match the round being decided.
    """


class SafetyApprovalRequiredError(Exception):
    """SCRUM-152 AC1: the event has not passed its Operational Safety Check."""

    def __init__(self, current_status):
        super().__init__(current_status)
        self.current_status = current_status

    @property
    def message(self):
        return safety_block_message(self.current_status)


class EventClosedError(Exception):
    """Reassignment is blocked for terminal events and an open clarification."""

    def __init__(self, current_status):
        super().__init__(current_status)
        self.current_status = current_status


class SafetyRecheckRequiredError(Exception):
    """SCRUM-153 AC1: this high-impact edit would withdraw the event's safety approval.

    The gate. A high-impact change to a `Confirmed` event is refused unless it
    arrives through the safety workflow, which withdraws the approval and
    opens the next round in the same request. So a client that skips the UI
    still can't leave an event `Confirmed` on the basis of an outdated review.
    """

    def __init__(self, changed_fields, high_impact_fields):
        super().__init__(high_impact_fields)
        self.changed_fields = changed_fields
        self.high_impact_fields = high_impact_fields

    @property
    def labels(self):
        return field_labels(self.high_impact_fields)

    @property
    def message(self):
        return (
            f"Changing {_sentence_list(self.labels)} will withdraw this event's "
            "safety approval. It will return to Pending Safety Check."
        )


class EventUnderSafetyReviewError(Exception):
    """SCRUM-153 Q3: no high-impact edits while the Safety Officer is mid-review."""


class EventNotEditableError(Exception):
    """The event is 'Rejected' or 'Cancelled', so its details are history."""

    def __init__(self, current_status):
        super().__init__(current_status)
        self.current_status = current_status


class NoCoordinatorChangeError(Exception):
    """Reassignment: the selected coordinator is already the assigned one."""


# Events whose coordinator can no longer be changed.
# Clarification is temporarily non-reassignable so the organiser's response
# returns to the same coordinator who asked the question (clarification AC4).
CLOSED_STATUSES = ("Rejected", "Cancelled", "Clarification Requested")


def update_event_coordinator(database_url, event_id, coordinator_id, assigned_by):
    """Assign or reassign the event's coordinator.

    Venue bookings, equipment requests and safety checks all authorise against
    the event's current coordinator_id, so changing it here hands every linked
    record to the new coordinator and takes it away from the previous one.
    """
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            # Locked so two Leads reassigning at once can't both pass the
            # no-change check against the same old coordinator.
            cursor.execute(
                """SELECT coordinator_id, status FROM public."Event"
                   WHERE event_id = %s FOR UPDATE""",
                [event_id],
            )
            current = cursor.fetchone()
            if not current:
                raise EventNotFoundError
            if current["status"] in CLOSED_STATUSES:
                raise EventClosedError(current["status"])
            if current["coordinator_id"] and str(current["coordinator_id"]) == coordinator_id:
                raise NoCoordinatorChangeError
            # Only ever reaches 'Under Review'. Keep it that way: anything that
            # can set 'Confirmed' or a later stage must go through the safety
            # gate in update_event_progress (SCRUM-152).
            # previous_coordinator_id = coordinator_id reads the old value, so
            # only the latest handover is kept; NULL on a first assignment.
            cursor.execute(
                f"""UPDATE public."Event"
                    SET previous_coordinator_id = coordinator_id,
                        coordinator_id = %s,
                        assigned_by = %s,
                        assigned_at = now(),
                        status = CASE WHEN status = 'Submitted' THEN 'Under Review' ELSE status END
                    WHERE event_id = %s
                    RETURNING {ROW_COLUMNS}""",
                [coordinator_id, assigned_by, event_id],
            )
            assigned = cursor.fetchone()
    return serialize(assigned)


def list_events(
    database_url,
    coordinator_id,
    status=None,
    venue=None,
    date_from=None,
    date_to=None,
    view_all=False,
):
    if view_all:
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
    if date_to:
        conditions.append("preferred_start_date <= %s")
        params.append(_aware(date_to))
    if date_from:
        conditions.append("preferred_end_date >= %s")
        params.append(_aware(date_from))
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


def get_event(database_url, event_id, coordinator_id, view_all=False):
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
    if not view_all and (
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
                clarification_history,
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
                "clarificationHistory": clarification_history,
            }
            cursor.execute(
                f"""UPDATE public."Event"
                    SET status = %s, description = %s
                    WHERE event_id = %s
                    RETURNING {ROW_COLUMNS}""",
                [status, json.dumps(metadata, ensure_ascii=False), event_id],
            )
            updated = cursor.fetchone()
            if status == "Rejected" and event["status"] != status:
                record_rejection(cursor, event, action_details)
            if status == "Approved" and event["status"] != status:
                record_approval(cursor, event)
    return serialize(updated)


def _stale_safety_check_check(action_history, safety_check_id):
    """AC3/AC6: the round being decided must be the one this event has open —
    the latest 'Pending Safety Check' submission entry's safetyCheckId.
    Stops a stale or made-up round from moving the event, with no call to
    another service.

    The entry must carry a safetyCheckId to count as a submission: a
    coordinator saving progress while the event waits for its decision
    writes a 'Pending Safety Check' entry too (the self-transition in
    ALLOWED_TRANSITIONS), but without a round id. Matching on status alone
    let that save shadow the real submission and made the open round look
    stale, so the Safety Officer could no longer decide it.
    """
    latest_pending = next(
        (
            entry
            for entry in reversed(action_history)
            if entry.get("status") == "Pending Safety Check" and entry.get("safetyCheckId")
        ),
        None,
    )
    if not latest_pending or latest_pending.get("safetyCheckId") != safety_check_id:
        raise StaleSafetyCheckError


def update_event_safety_status(
    database_url,
    event_id,
    status,
    safety_check_id,
    round_number,
    coordinator_id=None,
    decided_by=None,
    remarks=None,
    areas=None,
):
    """Move an event along the safety-check workflow (SCRUM-149 AC1, SCRUM-150 AC1).

    For Safety Check Service only — it is the service that has already
    checked the caller's role (coordinator or Safety Officer) and the event's
    arrangements. Everything that can be is re-checked here under `FOR
    UPDATE` because the composite's earlier read can be stale: the event may
    have been reassigned, or another decision may have landed, in between.
    """
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
            # Assignment first, as in update_event_progress: a caller who isn't
            # the assigned coordinator gets 403 and learns nothing else (AC5).
            # Only the submit move has a coordinator at all — the Safety
            # Officer approving is not the coordinator, and the composite
            # already checked that role via User Service.
            if status == "Pending Safety Check" and (
                not event["coordinator_id"]
                or str(event["coordinator_id"]) != coordinator_id
            ):
                raise EventNotAssignedError
            if (
                status == "Pending Safety Check"
                and event["status"] == "Pending Safety Check"
            ):
                raise SafetyCheckAlreadyPendingError
            # SCRUM-153: 'Confirmed -> Pending Safety Check' is in
            # SAFETY_TRANSITIONS, but only `update_event_details` may make it —
            # the move is legal solely as part of the high-impact edit that
            # justifies it. Belt and braces: the route refuses this before
            # connecting at all, and this refuses it again under the lock, in
            # case the event moved to 'Confirmed' in between.
            if (event["status"], status) in RECHECK_ONLY_MOVES or status not in (
                SAFETY_TRANSITIONS.get(event["status"], set())
            ):
                raise InvalidStatusTransitionError(event["status"])

            (
                description,
                purpose,
                decision,
                decision_history,
                action_details,
                action_history,
                clarification_history,
            ) = unpack_metadata(event["description"])
            recorded_at = datetime.now(UTC).isoformat()

            if status == "Confirmed":
                _stale_safety_check_check(action_history, safety_check_id)
                action = {
                    "status": status,
                    "details": (
                        f"Operational Safety Check approved (round {round_number})."
                    ),
                    "decidedBy": decided_by,
                    "safetyCheckId": safety_check_id,
                    "remarks": remarks,
                    "recordedAt": recorded_at,
                }
            elif status == "Safety Changes Requested":
                _stale_safety_check_check(action_history, safety_check_id)
                action = {
                    "status": status,
                    "details": (
                        f"Operational Safety Check: changes requested (round "
                        f"{round_number}) for {', '.join(areas)}."
                    ),
                    "decidedBy": decided_by,
                    "safetyCheckId": safety_check_id,
                    "remarks": remarks,
                    "areas": areas,
                    "recordedAt": recorded_at,
                }
            elif status == "Cancelled":
                _stale_safety_check_check(action_history, safety_check_id)
                action = {
                    "status": status,
                    "details": (
                        f"Operational Safety Check rejected (round {round_number}). "
                        "The event is cancelled."
                    ),
                    "decidedBy": decided_by,
                    "safetyCheckId": safety_check_id,
                    "remarks": remarks,
                    "recordedAt": recorded_at,
                }
            else:
                # SAFETY_TRANSITIONS only allows the submit move here otherwise.
                action = {
                    "status": status,
                    "details": (
                        f"Submitted for Operational Safety Check (round {round_number})."
                    ),
                    "coordinatorId": coordinator_id,
                    "safetyCheckId": safety_check_id,
                    "recordedAt": recorded_at,
                }
            # The event-side record of AC1/AC2's "in the event's history".
            # SafetyCheck.submitted_at/decided_at is the authoritative one.
            # The coordinator decision (Approved/Rejected) is untouched: a
            # safety decision is its own thing, kept on the SafetyCheck round.
            metadata = {
                "_connectsphere": "event-submission-v1",
                "description": description,
                "purpose": purpose,
                "decision": decision,
                "decisionHistory": decision_history,
                "actionDetails": action_details,
                "actionHistory": [*action_history, action],
                "clarificationHistory": clarification_history,
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


# The editable fields that are columns of their own. `description` and
# `purpose` live inside the `description` JSON instead, so they are rebuilt
# with the rest of the metadata rather than written as columns.
DETAIL_COLUMNS = {
    field: FIELDS[field]
    for field in EDITABLE_FIELDS
    if field not in ("description", "purpose")
}


def _normalised(field, value):
    """`value` reduced to what "changed" means for its field (SCRUM-153 AC2).

    Compared after the same normalisation `serialize` applies, so resending
    the current value is never a change: `"120"` and `120` are the same
    attendance, `" Hall A "` and `"Hall A"` the same requirement, and the same
    moment in two ISO spellings the same date. That is what stops a coordinator
    re-saving the form without edits from withdrawing a safety approval.
    """
    text = str(value).strip()
    if field == "expectedAttendance":
        return int(text) if text.isascii() and text.isdigit() else text
    if field in ("preferredStartDate", "preferredEndDate"):
        # Safe without a guard for an unparseable date: `validation.validate`
        # has already run on the merged event, so every date here is either a
        # valid local ISO date-time or empty (an event submitted before the
        # dates were required).
        return _local(_aware(text)) if text else ""
    return text


def _changed_fields(changes, current):
    """Which of `changes` really differ from `current`, and which of those are high-impact."""
    changed = [
        field
        for field, value in changes.items()
        if _normalised(field, value) != _normalised(field, current.get(field))
    ]
    return changed, [field for field in changed if field in HIGH_IMPACT_FIELDS]


def _latest_approval_entry(action_history):
    """The entry that confirmed this event: the latest 'Confirmed' action with a round id.

    SCRUM-150 writes it when the Safety Officer approves. Matching the round
    being withdrawn against it is how this service checks, with no call to
    another service, that the composite withdrew the approval the event
    actually holds (and not a stale or made-up round).
    """
    return next(
        (
            entry
            for entry in reversed(action_history)
            if entry.get("status") == "Confirmed" and entry.get("safetyCheckId")
        ),
        None,
    )


def update_event_details(
    database_url,
    event_id,
    coordinator_id,
    changes,
    safety_recheck=None,
    internal=False,
    actor_role=None,
    dry_run=False,
):
    """Save an edit to an event's details (SCRUM-153 AC1, AC2; SCRUM-20's edit write).

    `actor_role` lets the Event Coordinator Lead edit an event that has no
    assigned coordinator, but only on an `internal` call (the composite has
    looked the role up). `dry_run` runs every check and returns the classification of the
    change without writing, so the composite can validate before saving.

    This service is the single authority on what counts as high-impact, so the
    classification and the gate live here rather than in the composite. A
    low-impact edit saves in place and the status is untouched (AC2). A
    high-impact edit of a `Confirmed` event is refused with
    `SafetyRecheckRequiredError` unless `safety_recheck` arrives with the
    internal token — and with them, the fields are saved **and** the event
    moves back to 'Pending Safety Check' in this same `FOR UPDATE`
    transaction (AC1), so the two can never come apart.

    Everything the composite already checked is re-checked here under the
    lock: its read can be stale by the time it calls, and an atomic never
    trusts its caller's homework.
    """
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
            # Assignment first, as everywhere else: a caller who isn't the
            # assigned coordinator gets 403 and learns nothing about the event.
            is_lead = (
                internal
                and actor_role == COORDINATOR_LEAD_ROLE
                and not event["coordinator_id"]
            )
            if not is_lead and (
                not event["coordinator_id"]
                or str(event["coordinator_id"]) != coordinator_id
            ):
                raise EventNotAssignedError
            status = event["status"]
            if status not in EDITABLE_STATUSES:
                raise EventNotEditableError(status)

            current = serialize(event)
            merged = {**current, **changes}
            missing, errors = validation.validate(merged)
            if missing or errors:
                raise ValueError({"missingFields": missing, "errors": errors})

            changed, high = _changed_fields(changes, current)
            if dry_run:
                if high and status == "Pending Safety Check":
                    raise EventUnderSafetyReviewError
                return {
                    "event": current,
                    "changedFields": changed,
                    "highImpactFields": high,
                    "labels": field_labels(changed),
                }
            if not changed:
                # Nothing actually differs, so there is nothing to record and
                # no approval to withdraw (AC2).
                return current

            recheck = False
            if high and status == PREPARATION_STATUS:
                # The gate (AC1). `internal` proves the call came through the
                # safety workflow, which has already withdrawn the approval
                # and opened round N+1.
                if not safety_recheck or not internal:
                    raise SafetyRecheckRequiredError(changed, high)
                approval = _latest_approval_entry(current["actionHistory"])
                if (
                    not approval
                    or approval["safetyCheckId"]
                    != safety_recheck["withdrawnSafetyCheckId"]
                ):
                    raise StaleSafetyCheckError
                recheck = True
            elif high and status == "Pending Safety Check":
                # Q3: the Safety Officer is mid-review; don't move the
                # goalposts under them. Low-impact edits still save.
                raise EventUnderSafetyReviewError

            (
                description,
                purpose,
                decision,
                decision_history,
                action_details,
                action_history,
                clarification_history,
            ) = unpack_metadata(event["description"])
            description = merged["description"]
            purpose = merged["purpose"]
            recorded_at = datetime.now(UTC).isoformat()
            labels = field_labels(changed)

            if recheck:
                new_status = "Pending Safety Check"
                action = {
                    "status": new_status,
                    "details": (
                        f"Safety approval withdrawn because "
                        f"{_sentence_list(field_labels(high))} changed after "
                        "approval. The event needs a new Operational Safety "
                        f"Check (round {safety_recheck['roundNumber']}) before "
                        "it can proceed to preparation."
                    ),
                    "changedFields": changed,
                    "highImpactFields": high,
                    "coordinatorId": coordinator_id,
                    "withdrawnSafetyCheckId": safety_recheck["withdrawnSafetyCheckId"],
                    # Round N+1, deliberately: SCRUM-150/151's stale-round
                    # check identifies the open round as the latest 'Pending
                    # Safety Check' entry carrying a safetyCheckId, so the
                    # Safety Officer can decide round N+1 with no change to
                    # those code paths.
                    "safetyCheckId": safety_recheck["safetyCheckId"],
                    "recordedAt": recorded_at,
                }
            else:
                new_status = status
                action = {
                    "status": new_status,
                    "details": f"Event details updated: {', '.join(labels)}.",
                    "changedFields": changed,
                    "coordinatorId": coordinator_id,
                    "recordedAt": recorded_at,
                }

            # `decision`, `decisionHistory` and `actionDetails` are carried
            # through untouched: an edit is not a coordinator decision, and
            # losing them would erase the approve/reject history.
            metadata = {
                "_connectsphere": "event-submission-v1",
                "description": description,
                "purpose": purpose,
                "decision": decision,
                "decisionHistory": decision_history,
                "actionDetails": action_details,
                "actionHistory": [*action_history, action],
                "clarificationHistory": clarification_history,
            }
            assignments = ", ".join(f"{column} = %s" for column in DETAIL_COLUMNS.values())
            values = []
            for field, _column in DETAIL_COLUMNS.items():
                value = merged[field]
                if field == "expectedAttendance":
                    values.append(int(str(value).strip()))
                elif field in ("preferredStartDate", "preferredEndDate"):
                    values.append(_aware(value))
                else:
                    values.append(value)
            # The fields and the status move in one UPDATE, so AC1's "its
            # status returns to 'Pending Safety Check'" can't land without the
            # change that caused it, or the other way round.
            cursor.execute(
                f"""UPDATE public."Event"
                    SET {assignments}, description = %s, status = %s
                    WHERE event_id = %s
                    RETURNING {ROW_COLUMNS}""",
                [
                    *values,
                    json.dumps(metadata, ensure_ascii=False),
                    new_status,
                    event_id,
                ],
            )
            updated = cursor.fetchone()
    return serialize(updated)


def request_event_clarification(database_url, event_id, coordinator_id, message):
    """Open one clarification round without changing any submitted fields."""
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
                raise ClarificationNotAllowedError(event["status"])

            (
                description,
                purpose,
                decision,
                decision_history,
                action_details,
                action_history,
                clarification_history,
            ) = unpack_metadata(event["description"])
            requested_at = datetime.now(UTC).isoformat()
            clarification = {
                "id": str(uuid4()),
                "question": message,
                "requestedBy": coordinator_id,
                "requestedAt": requested_at,
                "response": None,
                "respondedBy": None,
                "respondedAt": None,
            }
            action = {
                "status": "Clarification Requested",
                "details": "Clarification requested from the Event Organiser.",
                "coordinatorId": coordinator_id,
                "recordedAt": requested_at,
            }
            metadata = {
                "_connectsphere": "event-submission-v1",
                "description": description,
                "purpose": purpose,
                "decision": decision,
                "decisionHistory": decision_history,
                "actionDetails": action_details,
                "actionHistory": [*action_history, action],
                "clarificationHistory": [*clarification_history, clarification],
            }
            cursor.execute(
                f"""UPDATE public."Event"
                    SET status = 'Clarification Requested', description = %s
                    WHERE event_id = %s
                    RETURNING {ROW_COLUMNS}""",
                [json.dumps(metadata, ensure_ascii=False), event_id],
            )
            updated = cursor.fetchone()
    return serialize(updated)


def respond_to_event_clarification(database_url, event_id, organiser_id, response):
    """Answer the open clarification and return the assigned event to Submitted."""
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
            if not event["organiser_id"] or str(event["organiser_id"]) != organiser_id:
                raise EventNotOwnedError
            if event["status"] != "Clarification Requested":
                raise ClarificationNotOpenError

            (
                description,
                purpose,
                decision,
                decision_history,
                action_details,
                action_history,
                clarification_history,
            ) = unpack_metadata(event["description"])
            open_index = next(
                (
                    index
                    for index in range(len(clarification_history) - 1, -1, -1)
                    if clarification_history[index].get("response") is None
                ),
                None,
            )
            if open_index is None:
                raise ClarificationNotOpenError

            responded_at = datetime.now(UTC).isoformat()
            answered = {
                **clarification_history[open_index],
                "response": response,
                "respondedBy": organiser_id,
                "respondedAt": responded_at,
            }
            clarification_history = [*clarification_history]
            clarification_history[open_index] = answered
            action = {
                "status": "Submitted",
                "details": "Event Organiser responded to the clarification request.",
                "organiserId": organiser_id,
                "recordedAt": responded_at,
            }
            metadata = {
                "_connectsphere": "event-submission-v1",
                "description": description,
                "purpose": purpose,
                "decision": decision,
                "decisionHistory": decision_history,
                "actionDetails": action_details,
                "actionHistory": [*action_history, action],
                "clarificationHistory": clarification_history,
            }
            cursor.execute(
                f"""UPDATE public."Event"
                    SET status = 'Submitted', description = %s
                    WHERE event_id = %s
                    RETURNING {ROW_COLUMNS}""",
                [json.dumps(metadata, ensure_ascii=False), event_id],
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
                clarification_history,
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
                            'actionHistory', %s::jsonb,
                            'clarificationHistory', %s::jsonb
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
                    json.dumps(clarification_history),
                    event_id,
                ],
            )
            decided = cursor.fetchone()
            if status == "Rejected":
                record_rejection(cursor, event, reason_text)
            if status == "Approved":
                record_approval(cursor, event)
    return serialize(decided)


def approve_event(database_url, event_id, coordinator_id):
    return decide_event(database_url, event_id, coordinator_id, "Approved")


def record_approval(cursor, event):
    """Save approval facts in the decision transaction without outward calls."""
    if not event.get("organiser_id"):
        logging.getLogger(__name__).warning("Approval notification missing organiser event=%s", event["event_id"])
        return
    source = dict(eventId=str(event["event_id"]), eventName=event["event_name"],
                  recipientId=str(event["organiser_id"]), decision="Approved")
    cursor.execute(
        'INSERT INTO public."EventNotificationOutbox" (source_id, type, source) VALUES (%s, %s, %s)',
        (str(uuid4()), "event.approval", Json(source)),
    )


def record_rejection(cursor, event, reason):
    """Save notification intent on the mutation's transaction, never call outward."""
    if not event.get("organiser_id"):
        logging.getLogger(__name__).warning("Rejection notification missing organiser event=%s", event["event_id"])
        return
    source = dict(eventId=str(event["event_id"]), eventName=event["event_name"],
                  recipientId=str(event.get("organiser_id")), decision="Rejected", reason=reason)
    cursor.execute(
        'INSERT INTO public."EventNotificationOutbox" (source_id, type, source) VALUES (%s, %s, %s)',
        (str(uuid4()), "event.rejection", Json(source)),
    )


def reject_event(database_url, event_id, coordinator_id, reason):
    return decide_event(database_url, event_id, coordinator_id, "Rejected", reason)
