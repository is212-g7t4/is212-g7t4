"""Closure HTTP orchestration only; never access the atomic database."""

import httpx
from app.clients import (
    VENUE_SERVICE_URL,
    VENUE_AVAILABILITY_SERVICE_URL,
    EVENT_SERVICE_URL,
    _forwarded_auth,
)


class ClosureUpstreamError(Exception):

    def __init__(self, status, code=None):
        self.status = status
        self.code = code


def call(method, url, **kwargs):
    try:
        response = httpx.request(method, url, timeout=5.0, headers=_forwarded_auth(), **kwargs)
    except httpx.RequestError as error:
        raise ClosureUpstreamError(503) from error
    if response.status_code == 409:
        try:
            if response.json().get("code") == "CLOSURE_PREVIEW_CHANGED":
                raise ClosureUpstreamError(409, "CLOSURE_PREVIEW_CHANGED")
        except (ValueError, AttributeError):
            pass
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


def create(data):
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
        )
    )


def preview(data):
    from app.closure_contract import uuid_value, timestamp

    try:
        venue = call("GET", f"{VENUE_SERVICE_URL}/venues/{data['venueId']}")["venue"]
        if (
            venue["id"] != data["venueId"]
            or not isinstance(venue["name"], str)
            or not venue["name"].strip()
        ):
            raise ValueError()
        result = call(
            "POST",
            f"{VENUE_AVAILABILITY_SERVICE_URL}/venue-closures/preview",
            json=data,
        )
        rows = result["affectedRequests"]
        if (
            not isinstance(rows, list)
            or type(result["affectedCount"]) is not int
            or result["affectedCount"] != len(rows)
            or result["closure"] != data
            or not isinstance(result["confirmationToken"], str)
            or not result["confirmationToken"]
        ):
            raise ValueError()
        seen = set()
        for row in rows:
            booking_id = uuid_value(row["id"])
            uuid_value(row["eventId"])
            start, end = timestamp(row["requestedStartTime"]), timestamp(
                row["requestedEndTime"]
            )
            if (
                booking_id in seen
                or row["venueId"] != data["venueId"]
                or row["status"] not in {"Pending", "Pending Review", "Approved"}
                or end <= start
                or start >= timestamp(data["endDateTime"])
                or end <= timestamp(data["startDateTime"])
            ):
                raise ValueError()
            seen.add(booking_id)
        event_ids = sorted({row["eventId"] for row in rows})
        names = {}
        for offset in range(0, len(event_ids), 100):
            events = call(
                "GET",
                f"{EVENT_SERVICE_URL}/events/summaries",
                params={"ids": ",".join(event_ids[offset : offset + 100])},
            )["events"]
            for event in events:
                if (
                    not isinstance(event["eventName"], str)
                    or not event["eventName"].strip()
                ):
                    raise ValueError()
                names[event["id"]] = event["eventName"]
        return {
            **result,
            "venueName": venue["name"],
            "affectedRequests": [
                {**row, "venueName": venue["name"], "eventName": names[row["eventId"]]}
                for row in rows
            ],
        }
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise ClosureUpstreamError(502) from error


def read(closure_id, params):
    path = (
        f"/venue-closures/{closure_id}" if closure_id is not None else "/venue-closures"
    )
    return checked(
        call(
            "GET", VENUE_AVAILABILITY_SERVICE_URL + path, params=params
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
