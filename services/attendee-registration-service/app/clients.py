import os

import httpx
from flask import has_request_context, request

EVENT_SERVICE_URL = os.getenv("EVENT_SERVICE_URL") or "http://localhost:5003"
REGISTRATION_SERVICE_URL = os.getenv("REGISTRATION_SERVICE_URL") or "http://localhost:5005"
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL") or "http://localhost:5001"
VENUE_AVAILABILITY_SERVICE_URL = os.getenv("VENUE_AVAILABILITY_SERVICE_URL") or "http://localhost:5008"
VENUE_SERVICE_URL = os.getenv("VENUE_SERVICE_URL") or "http://localhost:5006"


def _forwarded_auth():
    """The caller's Supabase token, so downstream services see the same signed-in user (SCRUM-8)."""
    if has_request_context() and request.headers.get("Authorization"):
        return {"Authorization": request.headers["Authorization"]}
    return {}


class RegistrationConflictError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def get_confirmed_events() -> list:
    response = httpx.get(f"{EVENT_SERVICE_URL}/events/registration", headers=_forwarded_auth(), timeout=5)
    response.raise_for_status()
    return response.json().get("events", [])


def get_confirmed_event(event_id: str):
    """Find the requested event in Event Service's confirmed-event catalogue."""
    return next(
        (event for event in get_confirmed_events() if event.get("id") == event_id),
        None,
    )


def get_historical_events(event_ids):
    """Public summaries preserve event history without exposing internal event detail routes.

    The attendee-facing summaries show the last approved times and venue
    (`attendeeVenueName`) while a safety re-check is open (SCRUM-153 AC4/AC5).
    """
    events = []
    ids = sorted(set(event_ids))
    for offset in range(0, len(ids), 100):
        response = httpx.get(f"{EVENT_SERVICE_URL}/events/attendee-summaries", params={"ids": ",".join(ids[offset:offset+100])}, headers=_forwarded_auth(), timeout=5)
        response.raise_for_status()
        for item in response.json()["events"]:
            events.append({**item, "preferredStartDate": item["startTime"], "preferredEndDate": item["endTime"],
                           "description": "", "purpose": ""})
    return events


def get_attendee_registrations() -> list:
    """The signed-in attendee's registrations (Registration Service reads them from the token)."""
    response = httpx.get(
        f"{REGISTRATION_SERVICE_URL}/registrations",
        headers=_forwarded_auth(),
        timeout=5,
    )
    response.raise_for_status()
    return response.json().get("registrations", [])


def get_event_registrations(event_id: str) -> list:
    response = httpx.get(
        f"{REGISTRATION_SERVICE_URL}/registrations",
        params={"eventId": event_id},
        headers=_forwarded_auth(),
        timeout=5,
    )
    response.raise_for_status()
    return response.json().get("registrations", [])


def get_user(user_id: str) -> dict | None:
    """Look up a single user from User Service, or None if they don't exist."""
    response = httpx.get(f"{USER_SERVICE_URL}/users/{user_id}", headers=_forwarded_auth(), timeout=5)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def save_registration(data: dict) -> dict:
    if "notificationContext" in data:
        from datetime import datetime
        response = httpx.get(f"{VENUE_AVAILABILITY_SERVICE_URL}/events/{data['eventId']}/venue-bookings", headers=_forwarded_auth(), timeout=5)
        response.raise_for_status()
        approved = [b for b in response.json()["bookings"] if b["status"] == "Approved"]
        if not approved:
            raise ValueError("Approved venue unavailable")
        booking = min(approved, key=lambda b: (datetime.fromisoformat(b["requestedStartTime"]), b["id"]))
        response = httpx.get(f"{VENUE_SERVICE_URL}/venues/{booking['venueId']}", headers=_forwarded_auth(), timeout=5)
        response.raise_for_status()
        name = response.json()["venue"]["name"]
        data = {**data, "notificationContext": {**data["notificationContext"], "venueName": name}}
    response = httpx.post(
        f"{REGISTRATION_SERVICE_URL}/registrations",
        json=data,
        headers=_forwarded_auth(),
        timeout=5,
    )
    if response.status_code == 409:
        body = response.json()
        raise RegistrationConflictError(
            body.get("code", "REGISTRATION_CONFLICT"),
            body.get("message", "Unable to register for this event."),
        )
    response.raise_for_status()
    return response.json()["registration"]


def withdraw_saved_registration(registration_id: str, event_name=None) -> dict:
    response = httpx.patch(
        f"{REGISTRATION_SERVICE_URL}/registrations/{registration_id}/withdraw",
        json={"notificationContext": {"eventName": event_name}} if event_name is not None else {},
        headers=_forwarded_auth(),
        timeout=5,
    )
    if response.status_code in (403, 404, 409):
        body = response.json()
        raise RegistrationConflictError(
            body.get("code", "WITHDRAWAL_CONFLICT"),
            body.get("message", "Unable to withdraw this registration."),
        )
    response.raise_for_status()
    return response.json()["registration"]
