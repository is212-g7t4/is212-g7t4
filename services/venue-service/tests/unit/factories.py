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
    }
    row.update(overrides)
    return row
