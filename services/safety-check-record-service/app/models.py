from contextlib import closing
from datetime import UTC

import psycopg2
from psycopg2.extras import RealDictCursor

# Only columns owned by Safety Check Record Service; no queries to other
# services' tables (AGENTS.md: an atomic owns exactly one entity).
COLUMNS = (
    "safety_check_id, event_id, round_number, submitted_by, submitted_at, "
    "equipment_placement_notes, crowd_movement_notes, status, decided_by, "
    "decided_at, remarks"
)

# Values of SafetyCheck.status. SCRUM-149 writes only PENDING; SCRUM-150 writes
# SAFETY_APPROVED, SCRUM-151 writes CHANGES_REQUESTED / SAFETY_REJECTED (Jira
# wording). 'Approved' is deliberately absent: that is only ever an *event*
# status, the one an event holds before its safety check.
PENDING = "Pending"
SAFETY_APPROVED = "Safety Approved"
CHANGES_REQUESTED = "Changes Requested"
SAFETY_REJECTED = "Safety Rejected"
RECORD_STATUSES = (PENDING, SAFETY_APPROVED, CHANGES_REQUESTED, SAFETY_REJECTED)

DECISION_STATUSES = (SAFETY_APPROVED, CHANGES_REQUESTED, SAFETY_REJECTED)

# Stored verbatim in SafetyCheckFlag.area; mirrors docs/db-structure.md and
# the seed data (SCRUM-151 AC1).
FLAG_AREAS = ("venue arrangement", "technical arrangement", "event details")
FLAG_COLUMNS = "flag_id, safety_check_id, area, booking_id, equip_request_id, change_required"

NOTES_LIMIT = 2000


class RoundAlreadyOpenError(Exception):
    """A round for this event is still 'Pending', so there is nothing to submit (SCRUM-149 AC4)."""

    def __init__(self, existing):
        super().__init__(existing)
        self.existing = existing


class RecordNotFoundError(Exception):
    pass


class RecordNotDeletableError(Exception):
    """The round has already been decided, so the composite's rollback must not remove it."""


class RoundAlreadyDecidedError(Exception):
    """The round is no longer 'Pending', so it can't be decided again (race guard)."""

    def __init__(self, existing):
        super().__init__(existing)
        self.existing = existing


class RoundNotLatestError(Exception):
    """A later round exists for the event, so this one is history, not the open round."""


class RoundNotReopenableError(Exception):
    """Compensation only: the round isn't decided, or `decidedAt` doesn't match the decision being undone."""


def _utc(value):
    return value.astimezone(UTC).isoformat() if value else None


def serialize(row, flags=()):
    return {
        "id": str(row["safety_check_id"]),
        "eventId": str(row["event_id"]) if row["event_id"] else None,
        "roundNumber": row["round_number"],
        "submittedBy": str(row["submitted_by"]) if row["submitted_by"] else None,
        "submittedAt": _utc(row["submitted_at"]),
        "equipmentPlacementNotes": row["equipment_placement_notes"],
        "crowdMovementNotes": row["crowd_movement_notes"],
        "status": row["status"],
        "decidedBy": str(row["decided_by"]) if row["decided_by"] else None,
        "decidedAt": _utc(row["decided_at"]),
        "remarks": row["remarks"],
        "flags": [serialize_flag(flag) for flag in flags],
    }


def serialize_flag(row):
    return {
        "id": str(row["flag_id"]),
        "area": row["area"],
        "bookingId": str(row["booking_id"]) if row["booking_id"] else None,
        "equipmentRequestId": str(row["equip_request_id"]) if row["equip_request_id"] else None,
        "changeRequired": row["change_required"],
    }


def create_round(
    database_url,
    event_id,
    submitted_by,
    equipment_placement_notes=None,
    crowd_movement_notes=None,
):
    """Open round N for an event, where N is one past its latest round (SCRUM-149 AC1, AC3).

    The round number and the open-round check are decided inside one
    transaction, under `FOR UPDATE` on the event's latest round, so two
    simultaneous submits cannot both open a round. `UNIQUE (event_id,
    round_number)` is the backstop for the case where there is no previous
    row to lock (AC4).
    """
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            latest = _latest_round(cursor, event_id, lock=True)
            if latest and latest["status"] == PENDING:
                raise RoundAlreadyOpenError(serialize(latest))
            try:
                cursor.execute(
                    f"""INSERT INTO public."SafetyCheck"
                        (event_id, round_number, submitted_by, submitted_at,
                         equipment_placement_notes, crowd_movement_notes, status)
                        VALUES (%s, %s, %s, now(), %s, %s, %s)
                        RETURNING {COLUMNS}""",
                    [
                        event_id,
                        (latest["round_number"] if latest else 0) + 1,
                        submitted_by,
                        equipment_placement_notes,
                        crowd_movement_notes,
                        PENDING,
                    ],
                )
            except psycopg2.errors.UniqueViolation:
                # Another submit opened this very round between our lock and
                # our insert (nothing to lock on a first round). Report theirs.
                connection.rollback()
                raise RoundAlreadyOpenError(
                    serialize(_latest_round(cursor, event_id, lock=False))
                ) from None
            return serialize(cursor.fetchone())


def _latest_round(cursor, event_id, lock):
    cursor.execute(
        f"""SELECT {COLUMNS} FROM public."SafetyCheck"
            WHERE event_id = %s
            ORDER BY round_number DESC
            LIMIT 1{" FOR UPDATE" if lock else ""}""",
        [event_id],
    )
    return cursor.fetchone()


def list_rounds(database_url, event_id, status=None):
    """An event's review rounds, newest first, so a reviewer sees history (SCRUM-163)."""
    query = f'SELECT {COLUMNS} FROM public."SafetyCheck" WHERE event_id = %s'
    params = [event_id]
    if status:
        query += " AND status = %s"
        params.append(status)
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query + " ORDER BY round_number DESC", params)
            rounds = cursor.fetchall()
            flags_by_round = _flags_for(cursor, [row["safety_check_id"] for row in rounds])
            return [
                serialize(row, flags_by_round.get(row["safety_check_id"], []))
                for row in rounds
            ]


def _flags_for(cursor, safety_check_ids):
    """One round's flags keyed by safety_check_id; rounds without flags get []."""
    if not safety_check_ids:
        return {}
    cursor.execute(
        f"""SELECT {FLAG_COLUMNS} FROM public."SafetyCheckFlag"
            WHERE safety_check_id = ANY(%s)""",
        [list(safety_check_ids)],
    )
    flags_by_round = {}
    for flag in cursor.fetchall():
        flags_by_round.setdefault(flag["safety_check_id"], []).append(flag)
    return flags_by_round


def delete_open_round(database_url, safety_check_id):
    """Remove an undecided round.

    Compensation only: Safety Check Service calls this when it created a round
    but could not then move the event to 'Pending Safety Check'. A decided
    round is history (SCRUM-163 reads it), so this refuses to touch one.
    """
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {COLUMNS} FROM public."SafetyCheck"
                    WHERE safety_check_id = %s
                    FOR UPDATE""",
                [safety_check_id],
            )
            existing = cursor.fetchone()
            if not existing:
                raise RecordNotFoundError
            if existing["status"] != PENDING or existing["decided_at"] is not None:
                raise RecordNotDeletableError
            cursor.execute(
                'DELETE FROM public."SafetyCheck" WHERE safety_check_id = %s',
                [safety_check_id],
            )


def decide_round(database_url, safety_check_id, status, decided_by, remarks=None, flags=()):
    """Decide the open round: SCRUM-150 AC2 (approve), SCRUM-151 (reject/changes).

    `FOR UPDATE` on this round is the race guard for AC3: if two Safety
    Officers click at once, only one `UPDATE` can win; the other finds the
    round no longer 'Pending' and raises `RoundAlreadyDecidedError` before
    anything is written.

    `flags` (SCRUM-151 AC1, AC6) is one row per selected area, inserted in
    the same transaction as the decision so a change request never saves
    without its areas, or with them orphaned from a decision.
    """
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {COLUMNS} FROM public."SafetyCheck"
                    WHERE safety_check_id = %s
                    FOR UPDATE""",
                [safety_check_id],
            )
            existing = cursor.fetchone()
            if not existing:
                raise RecordNotFoundError
            if existing["status"] != PENDING or existing["decided_at"] is not None:
                raise RoundAlreadyDecidedError(serialize(existing))
            latest = _latest_round(cursor, existing["event_id"], lock=False)
            if latest and latest["round_number"] != existing["round_number"]:
                raise RoundNotLatestError
            cursor.execute(
                f"""UPDATE public."SafetyCheck"
                    SET status = %s, decided_by = %s, decided_at = now(), remarks = %s
                    WHERE safety_check_id = %s
                    RETURNING {COLUMNS}""",
                [status, decided_by, clean_notes(remarks), safety_check_id],
            )
            decided = cursor.fetchone()
            inserted = []
            for flag in flags:
                cursor.execute(
                    f"""INSERT INTO public."SafetyCheckFlag"
                        (safety_check_id, area, change_required)
                        VALUES (%s, %s, %s)
                        RETURNING {FLAG_COLUMNS}""",
                    [safety_check_id, flag["area"], flag["changeRequired"]],
                )
                inserted.append(cursor.fetchone())
            return serialize(decided, inserted)


def reopen_round(database_url, safety_check_id, decided_at):
    """Compensation only: undo the decision the caller's own request just made.

    Reverts to 'Pending' and clears the decision fields, but only if
    `decided_at` matches the value `decide_round` returned. That way this can
    only undo the write the same request just made, never an older decision.
    """
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {COLUMNS} FROM public."SafetyCheck"
                    WHERE safety_check_id = %s
                    FOR UPDATE""",
                [safety_check_id],
            )
            existing = cursor.fetchone()
            if not existing:
                raise RecordNotFoundError
            if existing["decided_at"] is None or _utc(existing["decided_at"]) != decided_at:
                raise RoundNotReopenableError
            cursor.execute(
                'DELETE FROM public."SafetyCheckFlag" WHERE safety_check_id = %s',
                [safety_check_id],
            )
            cursor.execute(
                f"""UPDATE public."SafetyCheck"
                    SET status = %s, decided_by = NULL, decided_at = NULL, remarks = NULL
                    WHERE safety_check_id = %s
                    RETURNING {COLUMNS}""",
                [PENDING, safety_check_id],
            )
            return serialize(cursor.fetchone())


def clean_notes(value):
    """Blank or whitespace-only notes are stored as NULL, not as an empty string."""
    return value.strip() or None if isinstance(value, str) else None
