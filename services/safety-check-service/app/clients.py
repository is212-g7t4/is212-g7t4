import os

import httpx

# Composites are the only services allowed to call other services (see
# AGENTS.md). Each downstream service gets its own base-URL env var and a thin
# wrapper function here — copy this pattern per atomic this composite calls,
# don't build a generic client.
#
# Defaults are the host ports (see INDEX.md), so `uv run flask run` works
# outside Docker; compose overrides them with service-name hostnames.
EVENT_SERVICE_URL = os.environ.get("EVENT_SERVICE_URL") or "http://localhost:5003"
VENUE_AVAILABILITY_SERVICE_URL = (
    os.environ.get("VENUE_AVAILABILITY_SERVICE_URL") or "http://localhost:5008"
)
EQUIPMENT_REQUEST_SERVICE_URL = (
    os.environ.get("EQUIPMENT_REQUEST_SERVICE_URL") or "http://localhost:5011"
)
SAFETY_CHECK_RECORD_SERVICE_URL = (
    os.environ.get("SAFETY_CHECK_RECORD_SERVICE_URL") or "http://localhost:5013"
)
USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL") or "http://localhost:5001"

# Shared with Event Service: proves to it that a call to
# PATCH /events/<id>/safety-status came from this workflow, not a direct
# browser call (SCRUM-150's lock, moved forward from SCRUM-152 v2's B1).
INTERNAL_SERVICE_TOKEN = os.environ.get("INTERNAL_SERVICE_TOKEN")

# Submitting is a user-facing click, and the two arrangement reads run in
# parallel, so each downstream call gets the whole budget rather than a share.
TIMEOUT = 5.0


class DownstreamError(Exception):
    """A service this request depends on failed in a way we can't interpret."""


class DownstreamTimeout(Exception):
    """A service this request depends on didn't answer in time."""


class EventNotFoundError(Exception):
    pass


class EventNotAssignedError(Exception):
    """The caller isn't the event's assigned coordinator (SCRUM-149 AC5)."""


class EventTransitionError(Exception):
    """Event Service refused the lifecycle move; `code` says which way."""

    def __init__(self, code, body):
        super().__init__(code)
        self.code = code
        self.body = body


class SafetyCheckAlreadyPendingError(Exception):
    """A round for this event is still awaiting a decision (SCRUM-149 AC4)."""

    def __init__(self, existing=None):
        super().__init__(existing)
        self.existing = existing


class RecordNotFoundError(Exception):
    pass


class UserNotFoundError(Exception):
    pass


class ServiceCredentialsError(Exception):
    """Event Service refused our internal token — a misconfiguration, not the caller's fault."""


class SafetyCheckAlreadyDecidedError(Exception):
    """SCRUM-150 AC3 / race: the round is no longer 'Pending'."""

    def __init__(self, existing=None):
        super().__init__(existing)
        self.existing = existing


def _send(method, url, **kwargs):
    """One HTTP call, with every transport failure mapped to our own exceptions.

    Downstream URLs and error text never leave this module: a caller that
    leaked them would be telling the browser about our internal topology.
    """
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


# --- Event Service (atomic, 5003) -------------------------------------------


def get_event(event_id: str, viewer_id: str, viewer_role: str = None) -> dict:
    """The event, scoped to the requesting viewer so Event Service does AC5.

    `viewer_role` is passed through as `viewerRole` when given — a Safety
    Officer isn't the assigned coordinator, so without it Event Service would
    refuse the read with 403 (SCRUM-150).
    """
    params = {"coordinatorId": viewer_id}
    if viewer_role:
        params["viewerRole"] = viewer_role
    response = _send(
        "GET",
        f"{EVENT_SERVICE_URL}/events/{event_id}",
        params=params,
    )
    if response.status_code == 404:
        raise EventNotFoundError
    if response.status_code == 403:
        raise EventNotAssignedError
    return _ok(response).json()


def set_event_safety_status(
    event_id: str,
    status: str,
    safety_check_id: str,
    round_number: int,
    coordinator_id: str = None,
    decided_by: str = None,
    remarks: str = None,
) -> dict:
    """Move the event along the safety workflow. Event Service re-checks under a row lock.

    Sends the shared internal token on every call (submit and approve alike):
    Event Service's `/safety-status` route is locked to this service
    (SCRUM-150).
    """
    body = {
        "status": status,
        "safetyCheckId": safety_check_id,
        "roundNumber": round_number,
    }
    if coordinator_id is not None:
        body["coordinatorId"] = coordinator_id
    if decided_by is not None:
        body["decidedBy"] = decided_by
        body["remarks"] = remarks
    response = _send(
        "PATCH",
        f"{EVENT_SERVICE_URL}/events/{event_id}/safety-status",
        json=body,
        headers={"X-Internal-Service-Token": INTERNAL_SERVICE_TOKEN or ""},
    )
    if response.status_code == 404:
        raise EventNotFoundError
    if response.status_code == 403:
        body_data = _body(response)
        if body_data.get("code") == "INTERNAL_ONLY":
            raise ServiceCredentialsError
        raise EventNotAssignedError
    if response.status_code == 409:
        body_data = _body(response)
        raise EventTransitionError(body_data.get("code"), body_data)
    return _ok(response).json()


# --- Venue Availability Service (atomic, 5008) ------------------------------


def get_event_venue_bookings(event_id: str) -> list:
    """Every venue booking for the event, all statuses — an event can have several."""
    response = _ok(
        _send("GET", f"{VENUE_AVAILABILITY_SERVICE_URL}/events/{event_id}/venue-bookings")
    )
    return response.json()["bookings"]


# --- Equipment Request Service (atomic, 5011) -------------------------------


def get_event_equipment_requests(event_id: str, coordinator_id: str) -> list:
    """Every equipment request for the event.

    This endpoint is behind the DEV identity headers; `READ_ROLES` there
    already allows Event Coordinators, so we pass the submitting coordinator's
    own identity rather than inventing a service account.
    """
    response = _ok(
        _send(
            "GET",
            f"{EQUIPMENT_REQUEST_SERVICE_URL}/equipment-requests",
            params={"eventId": event_id},
            headers={
                "X-Dev-User-Id": coordinator_id,
                "X-Dev-Role": "Event Coordinator",
            },
        )
    )
    return response.json()["requests"]


# --- Safety Check Record Service (atomic, 5013) -----------------------------


def create_safety_check_record(
    event_id: str,
    submitted_by: str,
    equipment_placement_notes=None,
    crowd_movement_notes=None,
) -> dict:
    """Open the next round. The record service is the duplicate guard (AC4)."""
    response = _send(
        "POST",
        f"{SAFETY_CHECK_RECORD_SERVICE_URL}/safety-check-records",
        json={
            "eventId": event_id,
            "submittedBy": submitted_by,
            "equipmentPlacementNotes": equipment_placement_notes,
            "crowdMovementNotes": crowd_movement_notes,
        },
    )
    if response.status_code == 409:
        raise SafetyCheckAlreadyPendingError(_body(response).get("safetyCheck"))
    return _ok(response).json()


def list_safety_check_records(event_id: str, status=None) -> list:
    response = _ok(
        _send(
            "GET",
            f"{SAFETY_CHECK_RECORD_SERVICE_URL}/safety-check-records",
            params={"eventId": event_id, **({"status": status} if status else {})},
        )
    )
    return response.json()["safetyChecks"]


def delete_safety_check_record(safety_check_id: str) -> None:
    """Undo a round this service just created — compensation only, see routes.py."""
    response = _send(
        "DELETE",
        f"{SAFETY_CHECK_RECORD_SERVICE_URL}/safety-check-records/{safety_check_id}",
    )
    if response.status_code == 404:
        raise RecordNotFoundError
    _ok(response)


def decide_safety_check_record(
    safety_check_id: str, status: str, decided_by: str, remarks=None
) -> dict:
    """Decide the open round (SCRUM-150 AC2). The record service is the race guard."""
    response = _send(
        "PATCH",
        f"{SAFETY_CHECK_RECORD_SERVICE_URL}/safety-check-records/{safety_check_id}/decision",
        json={"status": status, "decidedBy": decided_by, "remarks": remarks},
    )
    if response.status_code == 404:
        raise RecordNotFoundError
    if response.status_code == 409:
        raise SafetyCheckAlreadyDecidedError(_body(response).get("safetyCheck"))
    return _ok(response).json()


def reopen_safety_check_record(safety_check_id: str, decided_at: str) -> dict:
    """Undo the decision this service's own request just made — compensation only."""
    response = _send(
        "POST",
        f"{SAFETY_CHECK_RECORD_SERVICE_URL}/safety-check-records/{safety_check_id}/reopen",
        json={"decidedAt": decided_at},
    )
    if response.status_code == 404:
        raise RecordNotFoundError
    _ok(response)


# --- User Service (atomic, 5001) --------------------------------------------


def get_user(user_id: str) -> dict:
    """Who is this caller, and what is their role (SCRUM-150: checked, not trusted)."""
    response = _send("GET", f"{USER_SERVICE_URL}/users/{user_id}")
    if response.status_code == 404:
        raise UserNotFoundError
    return _ok(response).json()
