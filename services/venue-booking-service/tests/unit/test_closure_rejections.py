"""
SCRUM-171: Reject Affected Bookings

User Story
----------
As a Venue Staff, I want the system to automatically reject existing venue
requests when I mark a venue as temporarily unavailable, so that I do not have
to manually reject each affected venue request.

Acceptance Criteria
-------------------
AC1: Given a closure is recorded, then requests for the same venue with
     overlapping booking intervals and status Pending, Pending Review, or
     Approved are changed to Rejected.
AC2: Given a request belongs to another venue, does not overlap the closure, or
     is already rejected or cancelled, then that request is not changed by the
     closure.
AC3: Given a request is rejected because of a closure, when its details are
     viewed, then the closure period and operational reason are displayed.
AC4: Given an affected venue request is rejected, the existing event itself or
     other venue requests under that event are not rejected and remain
     unchanged.

Real
----
- The composite booking routes' mapping of Venue Availability's immutable
  answer for closure-rejected requests.
- Assertions are on the status.

Doubled
-------
- Event, Venue, Venue Availability, User and Safety Check Services: Stub (patch
  / monkeypatch on app.clients, or respx) - canned answers or raised errors;
  calls recorded so tests assert what was (or was not) called.

Not proven
----------
- That the atomic services behave as stubbed (-> their own unit and integration
  tests, and tests/integration/ here with respx).
"""

import pytest
import httpx
from app import create_app
from tests.unit.factories import signed_in, bearer

STAFF_ID = "d9e4002b-db91-4939-b87e-50f9cceb5e0a"


@pytest.mark.parametrize("action", ["update", "cancel", "approve", "reject"], ids=["update", "cancel", "approve", "reject"])
def test_change_closure_rejected_request_returns_state_error(monkeypatch, action):
    """
    Summary: A request rejected by a closure cannot be updated, cancelled or decided.
    AC4: Given an affected venue request is rejected, the existing event itself
        or other venue requests under that event are not rejected and remain
        unchanged.
    Double: Stub (Venue Availability answers immutable)
    """
    # Arrange (Given)
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
    monkeypatch.setattr(
        "app.routes.get_booking",
        lambda *a: {"eventId": "event", "venueId": "venue", "status": "Pending Review"},
    )
    # SCRUM-29 D7: approve/reject run the staff review gates first.
    monkeypatch.setattr(
        "app.routes.get_event_for_internal_viewer", lambda *a: {"status": "Under Review"}
    )
    monkeypatch.setattr("app.routes.get_venue", lambda *a: {"id": "venue", "setupTimeMinutes": 0, "turnaroundTimeMinutes": 0})
    monkeypatch.setattr(httpx, "patch", reply)
    monkeypatch.setattr("app.routes.get_event", lambda *a: {"status": "Under Review"})
    monkeypatch.setattr(
        "app.routes.get_venues",
        lambda: [
            {"id": "venue", "status": "Available", "capacity": 100, "name": "Hall"}
        ],
    )
    client = signed_in(create_app().test_client())
    suffix = "" if action == "update" else "/" + action

    # Act (When)
    result = client.patch(
        "/booking-requests/booking" + suffix,
        # Decisions are Venue Staff's; editing and cancelling are the coordinator's (SCRUM-10).
        headers=bearer(STAFF_ID, "Venue Staff" if action in ("approve", "reject") else "Event Coordinator"),
        json=dict(
            eventId="event",
            venueId="venue",
            coordinatorId="user",
            reviewedBy=STAFF_ID,
            rejectionReason="Venue unsuitable",
            requestedStartTime="2099-01-01T10:00",
            requestedEndTime="2099-01-01T11:00",
            requiredCapacity=20,
            venueRequirements="",
        ),
    )

    # Assert (Then)
    assert result.status_code == 409
    assert result.json["code"] == "BOOKING_IMMUTABLE"
