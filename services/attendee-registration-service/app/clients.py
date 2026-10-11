import os

import httpx

EVENT_SERVICE_URL = os.getenv("EVENT_SERVICE_URL") or "http://localhost:5003"
REGISTRATION_SERVICE_URL = os.getenv("REGISTRATION_SERVICE_URL") or "http://localhost:5005"
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL") or "http://localhost:5001"


class RegistrationConflictError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def get_confirmed_events() -> list:
    response = httpx.get(f"{EVENT_SERVICE_URL}/events/registration", timeout=5)
    response.raise_for_status()
    return response.json().get("events", [])


def get_confirmed_event(event_id: str):
    """Find the requested event in Event Service's confirmed-event catalogue."""
    return next(
        (event for event in get_confirmed_events() if event.get("id") == event_id),
        None,
    )


def get_attendee_registrations(attendee_id: str) -> list:
    response = httpx.get(
        f"{REGISTRATION_SERVICE_URL}/registrations",
        params={"attendeeId": attendee_id},
        timeout=5,
    )
    response.raise_for_status()
    return response.json().get("registrations", [])


def get_event_registrations(event_id: str) -> list:
    response = httpx.get(
        f"{REGISTRATION_SERVICE_URL}/registrations",
        params={"eventId": event_id},
        timeout=5,
    )
    response.raise_for_status()
    return response.json().get("registrations", [])


def get_user(user_id: str) -> dict | None:
    """Look up a single user from User Service, or None if they don't exist."""
    response = httpx.get(f"{USER_SERVICE_URL}/users/{user_id}", timeout=5)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def save_registration(data: dict) -> dict:
    response = httpx.post(
        f"{REGISTRATION_SERVICE_URL}/registrations",
        json=data,
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
