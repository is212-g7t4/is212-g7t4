from contextlib import closing

import psycopg2
from psycopg2.extras import RealDictCursor

from app.equipment import from_row

COLUMNS = "equipment_id, equipment_type, description, total_quantity, location, operational_status"


def list_equipment(database_url, status=None):
    query = f'SELECT {COLUMNS} FROM public."Equipment"'
    params = []
    if status:
        query += " WHERE operational_status = %s"
        params.append(status)
    query += " ORDER BY equipment_type ASC, description ASC, equipment_id ASC"
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, params)
            return [from_row(row).to_dict() for row in cursor.fetchall()]


def create_equipment(database_url, equipment_type, description, total_quantity, location, operational_status):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""INSERT INTO public."Equipment"
                        (equipment_type, description, total_quantity, location, operational_status)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING {COLUMNS}""",
                [equipment_type, description, total_quantity, location, operational_status],
            )
            return from_row(cursor.fetchone()).to_dict()
