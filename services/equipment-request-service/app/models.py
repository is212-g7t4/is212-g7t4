from contextlib import closing

import psycopg2
from psycopg2.extras import RealDictCursor

COLUMNS = (
    "equipment_request_id, event_id, equipment_id, quantity_requested, "
    "technical_requirements, status, reviewed_by"
)


class RequestNotFoundError(Exception):
    pass


class RequestAlreadyReviewedError(Exception):
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


def review_request(database_url, request_id, status, reviewer_id):
    """Move a Pending request to Approved/Rejected; the Pending guard is in the UPDATE itself."""
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""UPDATE public."EquipmentRequest"
                    SET status = %s, reviewed_by = %s
                    WHERE equipment_request_id = %s AND status = 'Pending'
                    RETURNING {COLUMNS}""",
                [status, reviewer_id, request_id],
            )
            row = cursor.fetchone()
            if row:
                return serialize(row)
            cursor.execute(
                'SELECT 1 FROM public."EquipmentRequest" WHERE equipment_request_id = %s',
                [request_id],
            )
            if cursor.fetchone():
                raise RequestAlreadyReviewedError
            raise RequestNotFoundError


def review_event_requests(database_url, event_id, status, reviewer_id):
    """Apply one decision to every Pending request for an event."""
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""UPDATE public."EquipmentRequest"
                    SET status = %s, reviewed_by = %s
                    WHERE event_id = %s AND status = 'Pending'
                    RETURNING {COLUMNS}""",
                [status, reviewer_id, event_id],
            )
            rows = cursor.fetchall()
            if rows:
                return [serialize(row) for row in rows]
            cursor.execute(
                'SELECT 1 FROM public."EquipmentRequest" WHERE event_id = %s LIMIT 1',
                [event_id],
            )
            if cursor.fetchone():
                raise RequestAlreadyReviewedError
            raise RequestNotFoundError
