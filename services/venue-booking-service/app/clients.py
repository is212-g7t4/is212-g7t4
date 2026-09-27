import os

import httpx

# Composites are the only services allowed to call other services (see
# AGENTS.md). Each downstream service gets its own base-URL env var and a
# thin wrapper function here — copy this pattern per atomic this composite
# calls, don't build a generic client.

EVENT_SERVICE_URL = os.environ.get("EVENT_SERVICE_URL") or "http://localhost:5003"
VENUE_SERVICE_URL = os.environ.get("VENUE_SERVICE_URL") or "http://localhost:5006"


class EventNotFoundError(Exception):
    pass


class EventNotAssignedError(Exception):
    pass


def get_event(event_id: str, coordinator_id: str) -> dict:
    """Fetch an event from Event Service, scoped to the requesting coordinator."""
    response = httpx.get(
        f"{EVENT_SERVICE_URL}/events/{event_id}",
        params={"coordinatorId": coordinator_id},
    )
    if response.status_code == 404:
        raise EventNotFoundError
    if response.status_code == 403:
        raise EventNotAssignedError
    response.raise_for_status()
    return response.json()


def get_venues() -> list:
    """Return the venue catalogue from Venue Service."""
    response = httpx.get(f"{VENUE_SERVICE_URL}/venues")
    response.raise_for_status()
    return response.json()["venues"]
