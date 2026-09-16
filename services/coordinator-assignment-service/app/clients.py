import os

import httpx

# Composites are the only services allowed to call other services (see
# AGENTS.md). Each downstream service gets its own base-URL env var and a
# thin wrapper function here — copy this pattern per atomic this composite
# calls, don't build a generic client.

EVENT_SERVICE_URL = os.environ.get("EVENT_SERVICE_URL") or "http://localhost:5003"

MOCK_COORDINATORS = [
    {
        "user_id": "e7334aa9-eb3a-4c45-84b5-280501b6c109",
        "username": "Alicia Tan",
        "email": "alicia.tan.test@connectsphere.local",
        "role": "EventCoordinator",
        "organization": "ConnectSphere",
        "contact_details": "Test coordinator for approval workflow",
    },
    {
        "user_id": "7912075d-46f5-405b-9af3-05502f42f173",
        "username": "Marcus Lim",
        "email": "marcus.lim@connectsphere.example",
        "role": "EventCoordinator",
        "organization": "ConnectSphere",
        "contact_details": "+65 8234 5678",
    },
    {
        "user_id": "7110f1a8-e707-4b76-9fb0-57808310da98",
        "username": "Priya Nair",
        "email": "priya.nair@connectsphere.example",
        "role": "EventCoordinator",
        "organization": "ConnectSphere",
        "contact_details": "+65 8345 6789",
    },
]


def get_available_coordinators() -> list:
    """Return temporary coordinator records until User Service is available."""
    return MOCK_COORDINATORS.copy()


def assign_event_coordinator(event_id: str, coordinator_id: str) -> dict:
    """Update the coordinator for an event in Event Service."""
    response = httpx.patch(
        f"{EVENT_SERVICE_URL}/events/{event_id}",
        json={"assignedCoordinatorId": coordinator_id}
    )
    response.raise_for_status()
    return response.json()
