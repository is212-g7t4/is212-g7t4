import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    return psycopg2.connect(os.environ["DATABASE_URL"])

with get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute("select event_id, event_name, status from event_service limit 10;")
        rows = cur.fetchall()
        print(rows)
