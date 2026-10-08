import os

import httpx

EVENT_SERVICE_URL = os.getenv("EVENT_SERVICE_URL") or "http://localhost:5003"
REGISTRATION_SERVICE_URL = os.getenv("REGISTRATION_SERVICE_URL") or "http://localhost:5005"


class RegistrationConflictError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def get_confirmed_event(event_id: str):
    """Find the requested event in Event Service's confirmed-event catalogue."""
    response = httpx.get(f"{EVENT_SERVICE_URL}/events/registration", timeout=5)
    response.raise_for_status()
    return next(
        (event for event in response.json().get("events", []) if event.get("id") == event_id),
        None,
    )


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
