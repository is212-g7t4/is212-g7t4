"""Row builders for Venue Service's integration tests. Each one inserts and returns the new ID.

Venue.safety_info_updated_by has a foreign key to User, which User Service owns; the test
(not the app) writes those parent rows, so the foreign key stays real.
"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

STAFF_ID = "55555555-5555-4555-8555-555555555555"
OTHER_STAFF_ID = "66666666-6666-4666-8666-666666666666"
UNKNOWN_ID = "99999999-9999-4999-8999-999999999999"

SINGAPORE = ZoneInfo("Asia/Singapore")
OLD_STAMP = datetime(2030, 1, 1, 9, 0, tzinfo=SINGAPORE)

EMERGENCY = "Exits on north and south walls\nAssembly point: front lawn\nFire engine access via Gate 2"
RESTRICTIONS = "Noise curfew 10pm\nNo open flames\nFloor load limit 500 kg/m²"

# What PUT /venues/<id> (the profile route) accepts; see app/validation.py.
PROFILE = {
    "name": "Harbour Hall",
    "location": "Level 2, Harbour Wing",
    "capacity": "120",
    "facilities": ["wifi"],
    "accessibility": "Wheelchair accessible",
    "supportedLayouts": ["theatre"],
    "status": "Available",
}


def make_user(db, user_id, role="Venue Staff"):
    db.execute(
        'INSERT INTO public."User" (user_id, username, email, role) VALUES (%s, %s, %s, %s)',
        [user_id, f"user-{user_id[:4]}", f"user-{user_id[:4]}@example.com", role],
    )
    return user_id


def make_venue(
    db,
    name="Harbour Hall",
    emergency_access_details=None,
    known_restrictions=None,
    safety_info_updated_by=None,
    safety_info_updated_at=None,
    **overrides,
):
    row = {
        "venue_name": name,
        "location": "Level 2, Harbour Wing",
        "max_capacity": 120,
        "facilities": json.dumps({"wifi": True}),
        "accessibility": "Wheelchair accessible",
        "supported_layouts": json.dumps(["theatre"]),
        "operational_status": "Available",
        "emergency_access_details": emergency_access_details,
        "known_restrictions": known_restrictions,
        "safety_info_updated_by": safety_info_updated_by,
        "safety_info_updated_at": safety_info_updated_at,
        **overrides,
    }
    columns = ", ".join(row)
    placeholders = ", ".join(["%s"] * len(row))
    return str(db.execute(
        f'INSERT INTO public."Venue" ({columns}) VALUES ({placeholders}) RETURNING venue_id',
        list(row.values()),
    )[0]["venue_id"])


def staff_headers(user_id=STAFF_ID, role="Venue Staff"):
    return {"X-Dev-User-Id": user_id, "X-Dev-Role": role}
