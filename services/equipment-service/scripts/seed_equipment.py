"""Seed mock equipment so a fresh database has a catalogue to list.

Safe to run repeatedly: it upserts by (`equipment_type`, `description`)
instead of inserting duplicates on every run.

- `equipment_type` is one of the class names in `app/equipment.py`.
- `operational_status` is one of `Available` or `Unavailable`.

The first 7 rows are the live catalogue after migration
20261002120000_normalize_equipment_catalogue.sql; the last 2 are extra mock rows
(an Unavailable item and a plain Furniture item). Run the migration before this
script, otherwise the old display-name rows will sit alongside these.

Requires DATABASE_URL in the environment, loaded from
services/equipment-service/.env — see .env.example.

Usage:
    cd services/equipment-service
    uv run python scripts/seed_equipment.py
"""

import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()

STATUSES = ("Available", "Unavailable")

EQUIPMENT = [
    {"equipment_type": "Table", "description": "6-foot folding table", "total_quantity": 50, "location": "Furniture Storage", "operational_status": "Available"},
    {"equipment_type": "Laptop", "description": "Windows laptop for presentations", "total_quantity": 8, "location": "IT Storage", "operational_status": "Unavailable"},
    {"equipment_type": "Speaker", "description": "Portable PA speaker with stand", "total_quantity": 6, "location": "AV Storage Room", "operational_status": "Available"},
    {"equipment_type": "Projector", "description": "HD projector with HDMI/USB-C input", "total_quantity": 10, "location": "AV Storage Room", "operational_status": "Available"},
    {"equipment_type": "Chair", "description": "Standard stackable event chair", "total_quantity": 300, "location": "Furniture Storage", "operational_status": "Available"},
    {"equipment_type": "LightingKit", "description": "LED par can lighting kit", "total_quantity": 4, "location": "AV Storage Room", "operational_status": "Available"},
    {"equipment_type": "Microphone", "description": "Handheld wireless mic set with receiver", "total_quantity": 20, "location": "AV Storage Room", "operational_status": "Available"},
    {"equipment_type": "Microphone", "description": "Lapel microphone set", "total_quantity": 6, "location": "AV Storage Room", "operational_status": "Unavailable"},
    {"equipment_type": "Furniture", "description": "Standing lectern", "total_quantity": 5, "location": "Furniture Storage", "operational_status": "Available"},
]


def seed(database_url):
    # Upsert manually since there's no unique constraint on these columns.
    with psycopg2.connect(database_url, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            for item in EQUIPMENT:
                cursor.execute(
                    """SELECT equipment_id FROM public."Equipment"
                       WHERE equipment_type = %(equipment_type)s
                         AND description = %(description)s""",
                    item,
                )
                if cursor.fetchone():
                    cursor.execute(
                        """UPDATE public."Equipment" SET
                               total_quantity = %(total_quantity)s,
                               location = %(location)s,
                               operational_status = %(operational_status)s
                           WHERE equipment_type = %(equipment_type)s
                             AND description = %(description)s""",
                        item,
                    )
                else:
                    cursor.execute(
                        """INSERT INTO public."Equipment"
                            (equipment_type, description, total_quantity,
                             location, operational_status)
                           VALUES (%(equipment_type)s, %(description)s,
                                   %(total_quantity)s, %(location)s,
                                   %(operational_status)s)""",
                        item,
                    )


if __name__ == "__main__":
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set — copy .env.example to .env first.")
    seed(url)
    print(f"Seeded {len(EQUIPMENT)} equipment records.")
