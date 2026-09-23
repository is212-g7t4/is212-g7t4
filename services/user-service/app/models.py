from contextlib import closing

import psycopg2
from psycopg2.extras import RealDictCursor

COLUMNS = "user_id, username, email, role, organization, contact_details, manager_id"


def serialize(row):
    return {
        "user_id": str(row["user_id"]),
        "username": row["username"] or "",
        "email": row["email"] or "",
        "role": row["role"] or "",
        "organization": row["organization"] or "",
        "contact_details": row["contact_details"] or "",
        "manager_id": str(row["manager_id"]) if row.get("manager_id") else None,
    }


def list_users(database_url, role=None):
    if role is None:
        query = f"""SELECT {COLUMNS} FROM public."User" ORDER BY username ASC, user_id ASC"""
        params = []
    else:
        query = f"""SELECT {COLUMNS} FROM public."User" WHERE role = %s
                    ORDER BY username ASC, user_id ASC"""
        params = [role]

    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, params)
            return [serialize(row) for row in cursor.fetchall()]


class UserNotFoundError(Exception):
    pass


def get_user(database_url, user_id):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {COLUMNS} FROM public."User" WHERE user_id = %s""",
                [user_id],
            )
            user = cursor.fetchone()
    if not user:
        raise UserNotFoundError
    return serialize(user)
