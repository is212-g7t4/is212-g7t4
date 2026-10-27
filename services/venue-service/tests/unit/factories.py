"""Shared payloads and row builders for the Venue Service unit tests.

These used to live in test_add_venue.py and were imported from there by
test_edit_venue.py. A test module should never import another test module, so
they live here instead.
"""

VENUE_ID = "8381b11e-aaae-4d58-bdba-2607e9e2bde2"

VALID_PAYLOAD = {
    "name": "Sky Lounge",
    "location": "Level 20, Main Tower",
    "capacity": "80",
    "facilities": ["wifi", "projector"],
    "accessibility": "Wheelchair accessible",
    "supportedLayouts": ["theatre", "classroom"],
    "status": "Available",
    "setupTimeMinutes": "30",
    "turnaroundTimeMinutes": "45",
}


def saved_row(**overrides):
    row = {
        "venue_id": VENUE_ID,
        "venue_name": "Sky Lounge",
        "location": "Level 20, Main Tower",
        "max_capacity": 80,
        "facilities": {"wifi": True, "projector": True},
        "accessibility": "Wheelchair accessible",
        "supported_layouts": ["theatre", "classroom"],
        "operational_status": "Available",
        "setup_time_minutes": 30,
        "turnaround_time_minutes": 45,
    }
    row.update(overrides)
    return row


# SCRUM-167 Record Venue Safety Information.
STAFF_ID = "5b1f0c2e-7d3a-4c1e-9f6b-2a8d4e0c1b37"

SAFETY_PAYLOAD = {
    "emergencyAccessDetails": "Exits on north and south walls; assembly point at the front lawn",
    "knownRestrictions": "Noise curfew 10pm; no open flames",
}


def staff_headers(role="Venue Staff", user_id=STAFF_ID):
    return {"X-Dev-User-Id": user_id, "X-Dev-Role": role}
