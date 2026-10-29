import os

import httpx
from flask import has_request_context, request

# Composites are the only services allowed to call other services (see
# AGENTS.md). Each downstream service gets its own base-URL env var and a
# thin wrapper function here — copy this pattern per atomic this composite
# calls, don't build a generic client.

EVENT_SERVICE_URL = os.environ.get("EVENT_SERVICE_URL") or "http://localhost:5003"
USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL") or "http://localhost:5001"


# Roles an event can be assigned to. The Lead assigns coordinators and can
# also take an event on themselves (c4_diagram/c3.dsl: "eligible coordinators
# (including the Lead)").
ASSIGNABLE_ROLES = ("Event Coordinator Lead", "Event Coordinator")


def _forwarded_auth():
    """The caller's Supabase token, so downstream services see the same signed-in user (SCRUM-8)."""
    if has_request_context() and request.headers.get("Authorization"):
        return {"Authorization": request.headers["Authorization"]}
    return {}


def get_available_coordinators() -> list:
    """Return everyone an event can be assigned to, Lead first, from User Service."""
    coordinators = []
    for role in ASSIGNABLE_ROLES:
        response = httpx.get(f"{USER_SERVICE_URL}/users", params={"role": role}, headers=_forwarded_auth())
        response.raise_for_status()
        coordinators.extend(response.json()["users"])
    return coordinators


def get_user(user_id: str) -> dict | None:
    """Look up a single user from User Service, or None if they don't exist."""
    response = httpx.get(f"{USER_SERVICE_URL}/users/{user_id}", headers=_forwarded_auth())
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def assign_event_coordinator(event_id: str, coordinator_id: str) -> dict:
    """Update the coordinator for an event in Event Service, which records the signed-in assigner."""
    response = httpx.patch(
        f"{EVENT_SERVICE_URL}/events/{event_id}",
        json={"assignedCoordinatorId": coordinator_id},
        headers=_forwarded_auth(),
    )
    response.raise_for_status()
    return response.json()


def get_assignment_events() -> list:
    """Return the Lead's submitted-request assignment worklist.

    Event Service uses ``Under Review`` after the first assignment, so the
    submitted-request endpoint deliberately returns both ``Submitted`` and
    ``Under Review`` events.  Asking for the Lead's view (with the Lead's own
    token) lets Event Service return assigned and unassigned requests together.
    """
    response = httpx.get(
        f"{EVENT_SERVICE_URL}/events/submitted",
        params={"viewerRole": "Event Coordinator Lead"},
        headers=_forwarded_auth(),
    )
    response.raise_for_status()
    return response.json()["events"]


def get_active_events() -> list:
    """Active events (not Confirmed/Rejected/Cancelled), assigned or not, from Event Service."""
    response = httpx.get(f"{EVENT_SERVICE_URL}/events/active", headers=_forwarded_auth())
    response.raise_for_status()
    return response.json()["events"]
