"""# Test scope and acceptance mapping — SCRUM-171 integration

- **Separately approved immutability rule; no direct SCRUM-171 AC:** update/cancel/approve/reject preserve the atomic service BOOKING_IMMUTABLE state error through the composite API. Mocked calls do not prove database immutability.

## Case/group traceability

- `test_immutable_atomic_response_remains_state_error`: Separate approved immutability rule — composite preserves BOOKING_IMMUTABLE response; no direct closure AC.

## Existing test contract and detailed cases

SCRUM-171 composite preserves immutable-state errors."""

import pytest
import httpx
from app import create_app


@pytest.mark.parametrize("action", ["update", "cancel", "approve", "reject"])
def test_immutable_atomic_response_remains_state_error(monkeypatch, action):
    def reply(*args, **kwargs):
        return httpx.Response(
            409,
            json={
                "code": "BOOKING_IMMUTABLE",
                "message": "Rejected request is immutable.",
            },
            request=httpx.Request("PATCH", "http://test"),
        )

    # Main reads booking/venue buffer settings before approval; keep those
    # independent reads local so this case reaches the immutable-write response.
    monkeypatch.setattr("app.routes.get_booking", lambda *a: {"venueId": "venue"})
    monkeypatch.setattr("app.routes.get_venue", lambda *a: {"id": "venue", "setupTimeMinutes": 0, "turnaroundTimeMinutes": 0})
    monkeypatch.setattr(httpx, "patch", reply)
    monkeypatch.setattr("app.routes.get_event", lambda *a: {})
    monkeypatch.setattr(
        "app.routes.get_venues",
        lambda: [
            {"id": "venue", "status": "Available", "capacity": 100, "name": "Hall"}
        ],
    )
    client = create_app().test_client()
    suffix = "" if action == "update" else "/" + action
    result = client.patch(
        "/booking-requests/booking" + suffix,
        json=dict(
            eventId="event",
            venueId="venue",
            coordinatorId="user",
            reviewedBy="staff",
            requestedStartTime="2099-01-01T10:00",
            requestedEndTime="2099-01-01T11:00",
            requiredCapacity=20,
            venueRequirements="",
        ),
    )
    assert result.status_code == 409
    assert result.json["code"] == "BOOKING_IMMUTABLE"
