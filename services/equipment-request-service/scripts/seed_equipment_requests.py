"""Seed Pending equipment requests, some above the stock owned, to demo the Insufficient flag.

Dev-only. Reads `Event` and `Equipment` ids directly (this is a script, not the
service) and attaches the requests to the first two events it finds. Safe to
re-run: a request is skipped when the same event, equipment and requirement
text already exist.

Usage:
    cd services/equipment-request-service
    uv run python scripts/seed_equipment_requests.py
"""

import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()

# (equipment description, quantity requested, technical requirements); stock comes from seed_equipment.py.
REQUESTS = [
    [("6-foot folding table", 80, "Vendor booths (demo: exceeds stock of 50)"),
     ("Standard stackable event chair", 120, "General seating (demo: within stock)"),
     ("LED par can lighting kit", 6, "Stage wash (demo: exceeds stock of 4)")],
    [("Portable PA speaker with stand", 2, "Outdoor closing ceremony (demo: within stock)"),
     ("HD projector with HDMI/USB-C input", 12, "One per breakout room (demo: exceeds stock of 10)")],
]


def seed(database_url):
    with psycopg2.connect(database_url, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT event_id FROM public."Event" ORDER BY submission_date ASC NULLS LAST, event_id ASC LIMIT %s', [len(REQUESTS)])
            event_ids = [row[0] for row in cursor.fetchall()]
            if not event_ids:
                raise SystemExit("No events found — submit an event first.")
            for event_id, items in zip(event_ids, REQUESTS):
                for description, quantity, requirements in items:
                    cursor.execute('SELECT equipment_id FROM public."Equipment" WHERE description = %s', [description])
                    equipment = cursor.fetchone()
                    if not equipment:
                        print(f"skip: no equipment named {description!r} (run equipment-service seed first)")
                        continue
                    cursor.execute(
                        'SELECT 1 FROM public."EquipmentRequest" WHERE event_id = %s AND equipment_id = %s AND technical_requirements = %s',
                        [event_id, equipment[0], requirements],
                    )
                    if cursor.fetchone():
                        continue
                    cursor.execute(
                        """INSERT INTO public."EquipmentRequest"
                               (event_id, equipment_id, quantity_requested, technical_requirements, status)
                           VALUES (%s, %s, %s, %s, 'Pending')""",
                        [event_id, equipment[0], quantity, requirements],
                    )
                    print(f"added: {description} x{quantity} for event {event_id}")


if __name__ == "__main__":
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set — copy .env.example to .env first.")
    seed(url)
