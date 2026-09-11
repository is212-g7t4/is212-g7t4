import os

import httpx

# Composites are the only services allowed to call other services (see
# AGENTS.md). Each downstream service gets its own base-URL env var and a
# thin wrapper function here — copy this pattern per atomic this composite
# calls, don't build a generic client.
EXAMPLE_ATOMIC_SERVICE_URL = os.environ.get("EXAMPLE_ATOMIC_SERVICE_URL", "")


def get_example_resource(resource_id: str) -> dict:
    response = httpx.get(f"{EXAMPLE_ATOMIC_SERVICE_URL}/resources/{resource_id}")
    response.raise_for_status()
    return response.json()
