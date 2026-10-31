from contextlib import closing

import psycopg2
import psycopg2.errors
from psycopg2.extras import RealDictCursor
from app import outbox, allocation

COLUMNS = (
    "equipment_request_id, event_id, equipment_id, quantity_requested, "
    "technical_requirements, status, reviewed_by, rejection_reason"
)


class RequestNotFoundError(Exception):
    pass


class RequestAlreadyReviewedError(Exception):
    pass


class UnknownReferenceError(Exception):
    pass


def serialize(row):
    return {
        "id": str(row["equipment_request_id"]),
        "eventId": str(row["event_id"]),
        "equipmentId": str(row["equipment_id"]),
        "quantityRequested": row["quantity_requested"],
        "technicalRequirements": row["technical_requirements"] or "",
        "status": row["status"],
        "reviewedBy": str(row["reviewed_by"]) if row["reviewed_by"] else None,
        "rejectionReason": row.get("rejection_reason"),
    }


def get_request(database_url, request_id):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f'SELECT {COLUMNS} FROM public."EquipmentRequest" WHERE equipment_request_id = %s',
                [request_id],
            )
            row = cursor.fetchone()
    if not row:
        raise RequestNotFoundError
    return serialize(row)


def list_requests(database_url, status=None, event_id=None, event_ids=None):
    clauses, params = [], []
    if status:
        clauses.append("status = %s")
        params.append(status)
    if event_id:
        clauses.append("event_id = %s")
        params.append(event_id)
    if event_ids is not None:
        clauses.append("event_id = ANY(%s::uuid[])")
        params.append(event_ids)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    query = (
        f'SELECT {COLUMNS} FROM public."EquipmentRequest"{where} '
        "ORDER BY equipment_request_id ASC"
    )
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, params)
            return [serialize(row) for row in cursor.fetchall()]


def create_requests(database_url, event_id, items, requester_id, notification_context):
    """Insert every line as Pending in one transaction, so a bad line saves none of them."""
    created = []
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        try:
            with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
                for item in items:
                    cursor.execute(
                        f"""INSERT INTO public."EquipmentRequest"
                               (event_id, equipment_id, quantity_requested, technical_requirements, status,
                                requested_by, requested_at)
                           VALUES (%s, %s, %s, %s, 'Pending', %s, CURRENT_TIMESTAMP)
                           RETURNING {COLUMNS}""",
                        [event_id, item["equipmentId"], item["quantityRequested"], item["technicalRequirements"] or None, requester_id],
                    )
                    created.append(serialize(cursor.fetchone()))
                outbox.record_submission(cursor, event_id, created, notification_context)
        except psycopg2.errors.ForeignKeyViolation:
            raise UnknownReferenceError from None
    return created


def reset_safety_requests(database_url, event_id, request_ids):
    """Validate and lock all selected event requests; return only Approved rows reset to Pending.

    The UPDATE repeats the status guard so stale composite selections cannot
    reopen Pending or Rejected requests. Invalid membership aborts the transaction.
    This reset is not a review decision and does not create notification intents.
    """
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f'''SELECT {COLUMNS} FROM public."EquipmentRequest"
                    WHERE event_id = %s AND equipment_request_id = ANY(%s::uuid[])
                    FOR UPDATE''',
                [event_id, request_ids],
            )
            rows = cursor.fetchall()
            if len(rows) != len(request_ids):
                raise RequestNotFoundError
            cursor.execute(
                f'''UPDATE public."EquipmentRequest"
                    SET status = 'Pending', reviewed_by = NULL, rejection_reason = NULL
                    WHERE event_id = %s AND equipment_request_id = ANY(%s::uuid[])
                      AND status = 'Approved'
                    RETURNING {COLUMNS}''',
                [event_id, request_ids],
            )
            return [serialize(row) for row in cursor.fetchall()]


def approve_requests(database_url, reviewer_id, checked, notification_context, *, request_id=None):
    """Serialize approvals globally before any row locks; read committed rows AFTER waiting.

    Catalogue and Event snapshots are trusted inputs, not cross-service transactions.
    Concurrent catalogue/schedule edits are outside this guarantee.
    """
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        connection.set_session(isolation_level="READ COMMITTED")
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [allocation.APPROVAL_LOCK])
            cursor.execute(
                f'''SELECT {COLUMNS} FROM public."EquipmentRequest"
                    WHERE equipment_request_id = ANY(%s::uuid[])
                    ORDER BY equipment_request_id FOR UPDATE''', [checked["requestIds"]])
            selected = [serialize(row) for row in cursor.fetchall()]
            if not selected:
                column, identifier = ("equipment_request_id", request_id) if request_id else ("event_id", checked["eventId"])
                cursor.execute(f'SELECT 1 FROM public."EquipmentRequest" WHERE {column} = %s LIMIT 1', [identifier])
                if cursor.fetchone():
                    raise RequestAlreadyReviewedError
                raise RequestNotFoundError
            if len(selected) != len(checked["requestIds"]) or any(row["eventId"] != checked["eventId"] for row in selected):
                raise allocation.AllocationConflict("Every checked request must still belong to this event.")
            if any(row["status"] != "Pending" for row in selected):
                raise RequestAlreadyReviewedError
            equipment_ids = list({row["equipmentId"] for row in selected})
            cursor.execute(
                f'''SELECT {COLUMNS} FROM public."EquipmentRequest"
                    WHERE status = 'Approved' AND equipment_id = ANY(%s::uuid[])''', [equipment_ids])
            allocation.ensure_sufficient(checked, selected, [serialize(row) for row in cursor.fetchall()])
            cursor.execute(
                f'''UPDATE public."EquipmentRequest"
                    SET status = 'Approved', reviewed_by = %s, rejection_reason = NULL
                    WHERE equipment_request_id = ANY(%s::uuid[]) AND status = 'Pending'
                    RETURNING {COLUMNS}''', [reviewer_id, checked["requestIds"]])
            updated = [serialize(row) for row in cursor.fetchall()]
            outbox.record_decisions(cursor, updated, notification_context)
            return updated


def review_request(database_url, request_id, status, reviewer_id, rejection_reason=None, *, notification_context, approval_context=None):
    """Move a Pending request to Approved/Rejected; approval checks stock in this transaction."""
    if status == "Approved":
        return approve_requests(database_url, reviewer_id, approval_context, notification_context, request_id=request_id)[0]
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""UPDATE public."EquipmentRequest"
                    SET status = %s, reviewed_by = %s, rejection_reason = %s
                    WHERE equipment_request_id = %s AND status = 'Pending'
                    RETURNING {COLUMNS}""",
                [status, reviewer_id, rejection_reason, request_id],
            )
            row = cursor.fetchone()
            if row:
                updated = serialize(row)
                outbox.record_decisions(cursor, [updated], notification_context)
                return updated
            cursor.execute(
                'SELECT 1 FROM public."EquipmentRequest" WHERE equipment_request_id = %s',
                [request_id],
            )
            if cursor.fetchone():
                raise RequestAlreadyReviewedError
            raise RequestNotFoundError


def review_event_requests(database_url, event_id, status, reviewer_id, rejection_reason=None, *, notification_context, approval_context=None):
    """Approve the checked selection, or reject every Pending request for an event."""
    if status == "Approved":
        return approve_requests(database_url, reviewer_id, approval_context, notification_context)
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""UPDATE public."EquipmentRequest"
                    SET status = %s, reviewed_by = %s, rejection_reason = %s
                    WHERE event_id = %s AND status = 'Pending'
                    RETURNING {COLUMNS}""",
                [status, reviewer_id, rejection_reason, event_id],
            )
            rows = cursor.fetchall()
            if rows:
                updated = [serialize(row) for row in rows]
                outbox.record_decisions(cursor, updated, notification_context)
                return updated
            cursor.execute(
                'SELECT 1 FROM public."EquipmentRequest" WHERE event_id = %s LIMIT 1',
                [event_id],
            )
            if cursor.fetchone():
                raise RequestAlreadyReviewedError
            raise RequestNotFoundError
