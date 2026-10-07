import os

import httpx

# Composites are the only services allowed to call other services (see
# AGENTS.md). One thin wrapper per downstream endpoint; URLs are read per call
# so tests and compose can override them.
FORWARDED_HEADERS = ("X-Dev-User-Id", "X-Dev-Role")
PASSED_THROUGH = (401, 403, 404, 409)


class DownstreamError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _base(name, default):
    return os.environ.get(name) or default


def _call(method, url, **kwargs):
    try:
        response = httpx.request(method, url, timeout=10, **kwargs)
    except httpx.HTTPError:
        raise DownstreamError(503, "Unable to reach a service this request depends on.") from None
    if response.is_success:
        return response.json()
    try:
        message = response.json().get("message")
    except (ValueError, AttributeError):
        message = None
    status = response.status_code if response.status_code in PASSED_THROUGH else 502
    raise DownstreamError(status, message or "A service this request depends on failed.")


def _request_service(path):
    return f"{_base('EQUIPMENT_REQUEST_SERVICE_URL', 'http://localhost:5009')}{path}"


def _identity(headers):
    return {name: headers[name] for name in FORWARDED_HEADERS if name in headers}


# Equipment Request Service (atomic): request records and decisions.
def list_requests(headers, status=None, event_ids=None):
    if event_ids is not None and not event_ids:
        return []
    params = {}
    if status:
        params["status"] = status
    if event_ids is not None:
        params["eventIds"] = ",".join(event_ids)
    return _call("GET", _request_service("/equipment-requests"), params=params, headers=_identity(headers))["requests"]


def get_request(headers, request_id):
    return _call("GET", _request_service(f"/equipment-requests/{request_id}"), headers=_identity(headers))["request"]


def review_request(headers, request_id, status):
    body = _call("PATCH", _request_service(f"/equipment-requests/{request_id}"), json={"status": status}, headers=_identity(headers))
    return body["request"]


def review_event_requests(headers, event_id, status):
    body = _call("PATCH", _request_service(f"/events/{event_id}/equipment-requests"), json={"status": status}, headers=_identity(headers))
    return body["requests"]


# Event Service (atomic): names, status and time windows.
def _event_service(path):
    return f"{_base('EVENT_SERVICE_URL', 'http://localhost:5003')}{path}"


def get_event_summaries(event_ids):
    summaries = []
    for start in range(0, len(event_ids), 100):
        chunk = event_ids[start:start + 100]
        summaries += _call("GET", _event_service("/events/summaries"), params={"ids": ",".join(chunk)})["events"]
    return summaries


def get_overlapping_events(start, end, statuses, exclude_event_id):
    params = {"start": start, "end": end, "statuses": ",".join(statuses), "excludeEventId": exclude_event_id}
    return _call("GET", _event_service("/events/overlapping"), params=params)["events"]


# Equipment Service (atomic): the catalogue and total stock.
def list_equipment():
    return _call("GET", f"{_base('EQUIPMENT_SERVICE_URL', 'http://localhost:5002')}/equipment")["equipment"]
