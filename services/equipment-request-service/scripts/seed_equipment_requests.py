"""Refresh up to three eligible events with Pending equipment requests for the UI demo.

Dev-only. Reads `Event` and `Equipment` ids directly (this is a script, not the
service), and does not change event records or unrelated requests. Each run
refreshes only the demo requests listed below.

Usage:
    cd services/equipment-request-service
    uv run python scripts/seed_equipment_requests.py
"""

import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()

# (equipment description, quantity requested, technical requirements); stock comes from seed_equipment.py.
EVENT_REQUESTS = [
    [("6-foot folding table", 60, "DEMO insufficiency: requested 60, catalogue stock is 50"),
     ("Standard stackable event chair", 40, "DEMO sufficient: requested 40, catalogue stock is 300"),
     ("LED par can lighting kit", 2, "DEMO sufficient: requested 2, catalogue stock is 4")],
    [("Windows laptop for presentations", 1, "DEMO insufficiency: equipment is Unavailable, so available stock is 0"),
     ("Portable PA speaker with stand", 3, "DEMO sufficient: requested 3, catalogue stock is 6"),
     ("Handheld wireless mic set with receiver", 8, "DEMO sufficient: requested 8, catalogue stock is 20")],
    [("HD projector with HDMI/USB-C input", 12, "DEMO insufficiency: requested 12, catalogue stock is 10"),
     ("Standing lectern", 2, "DEMO sufficient: requested 2, catalogue stock is 5"),
     ("Standard stackable event chair", 80, "DEMO sufficient: requested 80, catalogue stock is 300")],
]

LEGACY_REQUIREMENTS = (
    "Vendor booths (demo: exceeds stock of 50)",
    "General seating (demo: within stock)",
    "Stage wash (demo: exceeds stock of 4)",
    "Outdoor closing ceremony (demo: within stock)",
    "One per breakout room (demo: exceeds stock of 10)",
)


def seed(database_url):
    with psycopg2.connect(database_url, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            demo_requirements = [
                requirements
                for items in EVENT_REQUESTS
                for _, _, requirements in items
            ]
            cursor.execute(
                'DELETE FROM public."EquipmentRequest" WHERE technical_requirements = ANY(%s)',
                [list(LEGACY_REQUIREMENTS) + demo_requirements],
            )
            cursor.execute(
                """SELECT event_id, status FROM public."Event"
                   WHERE status IN (%s, %s)
                   ORDER BY submission_date ASC NULLS LAST, event_id ASC
                   LIMIT %s""",
                ["Submitted", "Under Review", len(EVENT_REQUESTS)],
            )
            events = cursor.fetchall()
            if not events:
                raise SystemExit("No Submitted or Under Review events found — submit an event first.")
            for (event_id, event_status), items in zip(events, EVENT_REQUESTS):
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
                    print(f"added: {description} x{quantity} for {event_status} event {event_id} ({requirements})")


if __name__ == "__main__":
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set — copy .env.example to .env first.")
    seed(url)
