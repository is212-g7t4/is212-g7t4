import os

import httpx
from flask import has_request_context, request

# Composites are the only services allowed to call other services (see
# AGENTS.md). One thin wrapper per downstream call, and one base-URL env var
# per atomic. Defaults are the host ports (INDEX.md), so `uv run flask run`
# works outside Docker; compose overrides them with service-name hostnames.
EVENT_SERVICE_URL = os.environ.get("EVENT_SERVICE_URL") or "http://localhost:5003"
VENUE_AVAILABILITY_SERVICE_URL = (
    os.environ.get("VENUE_AVAILABILITY_SERVICE_URL") or "http://localhost:5008"
)
EQUIPMENT_REQUEST_SERVICE_URL = (
    os.environ.get("EQUIPMENT_REQUEST_SERVICE_URL") or "http://localhost:5011"
)
EQUIPMENT_SERVICE_URL = os.environ.get("EQUIPMENT_SERVICE_URL") or "http://localhost:5002"
USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL") or "http://localhost:5001"
VENUE_SERVICE_URL = os.environ.get("VENUE_SERVICE_URL") or "http://localhost:5006"

# Proves to Event Service that the Lead's role was looked up here rather than
# claimed by a browser (its lock on `actorRole`).
INTERNAL_SERVICE_TOKEN = os.environ.get("INTERNAL_SERVICE_TOKEN")

TIMEOUT = 5.0


class DownstreamError(Exception):
    """A service this request depends on failed in a way we can't interpret."""


class DownstreamTimeout(Exception):
    """A service this request depends on didn't answer in time."""


class UserNotFoundError(Exception):
    pass


class EventRejectedError(Exception):
    """Event Service refused the request; `body` and `status` go back to the caller as they are."""

    def __init__(self, status, body):
        super().__init__(status)
        self.status = status
        self.body = body


def _forwarded_auth():
    """The caller's Supabase token, so downstream services see the same signed-in user (SCRUM-8)."""
    if has_request_context() and request.headers.get("Authorization"):
        return {"Authorization": request.headers["Authorization"]}
    return {}


def _send(method, url, **kwargs):
    """One HTTP call with every transport failure mapped to our own exceptions.

    Downstream URLs and error text never leave this module, so the browser
    learns nothing about the internal topology.
    """
    kwargs["headers"] = {**_forwarded_auth(), **kwargs.get("headers", {})}
    try:
        return httpx.request(method, url, timeout=TIMEOUT, **kwargs)
    except httpx.TimeoutException:
        raise DownstreamTimeout from None
    except httpx.HTTPError:
        raise DownstreamError from None


def _ok(response):
    if not response.is_success:
        raise DownstreamError
    return response


def _body(response):
    try:
        return response.json()
    except ValueError:
        return {}


# --- User Service (atomic, 5001) --------------------------------------------


def get_user(user_id: str) -> dict:
    """The caller's account: their role is looked up, never trusted from the request."""
    response = _send("GET", f"{USER_SERVICE_URL}/users/{user_id}")
    if response.status_code == 404:
        raise UserNotFoundError
    return _ok(response).json()


# --- Event Service (atomic, 5003) -------------------------------------------


def _details_call(event_id, changes, actor_role, dry_run):
    body = {"changes": changes, "dryRun": dry_run}
    if actor_role:
        body["actorRole"] = actor_role
    response = _send(
        "PATCH",
        f"{EVENT_SERVICE_URL}/events/{event_id}/details",
        json=body,
        headers={"X-Internal-Service-Token": INTERNAL_SERVICE_TOKEN or ""},
    )
    if response.status_code in (400, 403, 404, 409):
        raise EventRejectedError(response.status_code, _body(response))
    return _ok(response).json()


def _event_workflow_call(method, path, **kwargs):
    response = _send(
        method,
        f"{EVENT_SERVICE_URL}{path}",
        headers={"X-Internal-Service-Token": INTERNAL_SERVICE_TOKEN or ""},
        **kwargs,
    )
    if response.status_code in (400, 403, 404, 409):
        raise EventRejectedError(response.status_code, _body(response))
    return _ok(response).json()


def preview_event_details(event_id, changes, actor_role=None) -> dict:
    """Event Service's verdict on an edit with nothing written.

    It is the one authority on what counts as high-impact, so this is asked
    rather than re-derived. Returns `event`, `changedFields`,
    `highImpactFields` and `labels`.
    """
    return _details_call(event_id, changes, actor_role, dry_run=True)


def save_event_details(event_id, changes, actor_role=None) -> dict:
    """Save the edit; Event Service re-checks everything under its own row lock."""
    return _details_call(event_id, changes, actor_role, dry_run=False)


def list_pending_change_requests() -> list:
    return _event_workflow_call("GET", "/change-requests")["changeRequests"]


def get_change_request(change_request_id: str) -> dict:
    return _event_workflow_call("GET", f"/change-requests/{change_request_id}")


def decide_change_request(
    change_request_id: str,
    decision: str,
    reason: str | None = None,
) -> dict:
    body = {"decision": decision}
    if reason is not None:
        body["reason"] = reason
    return _event_workflow_call(
        "PATCH", f"/change-requests/{change_request_id}/decision", json=body
    )


def list_overlapping_events(start, end, statuses, exclude_event_id) -> list:
    response = _ok(
        _send(
            "GET",
            f"{EVENT_SERVICE_URL}/events/overlapping",
            params={
                "start": start,
                "end": end,
                "statuses": ",".join(statuses),
                "excludeEventId": exclude_event_id,
            },
        )
    )
    return response.json()["events"]


# --- Venue Availability Service (atomic, 5008) ------------------------------


def get_event_venue_bookings(event_id: str) -> list:
    """Every venue booking for the event, all statuses — an event can have several."""
    response = _ok(
        _send("GET", f"{VENUE_AVAILABILITY_SERVICE_URL}/events/{event_id}/venue-bookings")
    )
    return response.json()["bookings"]


# --- Venue Service (atomic, 5006) -------------------------------------------


def list_venues() -> list:
    """The venue catalogue, for each booked venue's capacity."""
    return _ok(_send("GET", f"{VENUE_SERVICE_URL}/venues")).json()["venues"]


# --- Equipment Request Service (atomic, 5011) -------------------------------


def list_event_equipment_requests(event_id: str) -> list:
    response = _ok(
        _send(
            "GET",
            f"{EQUIPMENT_REQUEST_SERVICE_URL}/equipment-requests",
            params={"eventId": event_id},
        )
    )
    return response.json()["requests"]


def list_approved_equipment_requests(event_ids: list) -> list:
    response = _ok(
        _send(
            "GET",
            f"{EQUIPMENT_REQUEST_SERVICE_URL}/equipment-requests",
            params={"status": "Approved", "eventIds": ",".join(event_ids)},
        )
    )
    return response.json()["requests"]


# --- Equipment Service (atomic, 5002) ---------------------------------------


def list_equipment() -> list:
    return _ok(_send("GET", f"{EQUIPMENT_SERVICE_URL}/equipment")).json()["equipment"]
