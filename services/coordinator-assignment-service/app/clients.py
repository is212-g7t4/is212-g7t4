import os

import httpx

# Composites are the only services allowed to call other services (see
# AGENTS.md). Each downstream service gets its own base-URL env var and a
# thin wrapper function here — copy this pattern per atomic this composite
# calls, don't build a generic client.

EVENT_SERVICE_URL = os.environ.get("EVENT_SERVICE_URL") or "http://localhost:5003"
USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL") or "http://localhost:5001"


def get_available_coordinators() -> list:
    """Return Event Coordinators from User Service."""
    response = httpx.get(f"{USER_SERVICE_URL}/users", params={"role": "Event Coordinator"})
    response.raise_for_status()
    return response.json()["users"]


def get_user(user_id: str) -> dict | None:
    """Look up a single user from User Service, or None if they don't exist."""
    response = httpx.get(f"{USER_SERVICE_URL}/users/{user_id}")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def assign_event_coordinator(event_id: str, coordinator_id: str) -> dict:
    """Update the coordinator for an event in Event Service."""
    response = httpx.patch(
        f"{EVENT_SERVICE_URL}/events/{event_id}",
        json={"assignedCoordinatorId": coordinator_id}
    )
    response.raise_for_status()
    return response.json()
