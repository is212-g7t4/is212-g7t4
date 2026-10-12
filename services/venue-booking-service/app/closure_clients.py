"""Closure HTTP orchestration only; never access the atomic database."""

import httpx
from app.clients import VENUE_SERVICE_URL, VENUE_AVAILABILITY_SERVICE_URL


class ClosureUpstreamError(Exception):
    def __init__(self, status):
        self.status = status


def call(method, url, **kwargs):
    try:
        response = httpx.request(method, url, timeout=5.0, **kwargs)
    except httpx.RequestError as error:
        raise ClosureUpstreamError(503) from error
    if response.status_code not in {200, 201}:
        code = (
            response.status_code
            if response.status_code in {400, 401, 403, 404, 503}
            else 503
        )
        raise ClosureUpstreamError(code)
    try:
        return response.json()
    except ValueError as error:
        raise ClosureUpstreamError(502) from error


def create(data, headers):
    result = call("GET", f"{VENUE_SERVICE_URL}/venues/{data['venueId']}")
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("venue"), dict)
        or result["venue"].get("id") != data["venueId"]
    ):
        raise ClosureUpstreamError(502)
    return checked(
        call(
            "POST",
            f"{VENUE_AVAILABILITY_SERVICE_URL}/venue-closures",
            json=data,
            headers=headers,
        )
    )


def read(closure_id, params, headers):
    path = (
        f"/venue-closures/{closure_id}" if closure_id is not None else "/venue-closures"
    )
    return checked(
        call(
            "GET", VENUE_AVAILABILITY_SERVICE_URL + path, params=params, headers=headers
        ),
        collection=closure_id is None,
    )


def checked(payload, collection=False):
    if not isinstance(payload, dict):
        raise ClosureUpstreamError(502)
    if collection:
        if not isinstance(payload.get("closures"), list) or "nextCursor" not in payload:
            raise ClosureUpstreamError(502)
    elif not isinstance(payload.get("closure"), dict):
        raise ClosureUpstreamError(502)
    return payload
