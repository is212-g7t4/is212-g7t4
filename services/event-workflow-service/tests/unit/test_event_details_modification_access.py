"""SCRUM-10 Role-Based Modification Control: Event Workflow Service unit tests.

Story:      As a registered user, I want to modify only information appropriate to my
            role and relationship to an event, so that I can perform my responsibilities
            without changing information outside my permissions.
Real:       Flask app, routes, token verification and the role check on PATCH /events/<id>/details.
Doubled:    every downstream service (Event, User, Venue Availability, Venue, Equipment Request,
            Equipment); the unit tier's socket block fails any call that is not stubbed, so a
            refused edit is also proven to send nothing downstream.
Not proven: that the coordinator is assigned to the event or that the Lead may edit an unassigned
            one (Event Service decides that; see test_update_details.py and Event Service's
            SCRUM-10 tests); that a refused edit leaves the stored event unchanged (Event Service);
            Supabase issuing the token. PATCH /change-requests/<id> already refuses non-coordinators
            through its User Service lookup (test_change_request_review.py).

AC1  Given an authenticated user is permitted to modify information based on their role and
     relationship to the event, when they make a valid change to that information, then the
     change is allowed.
AC2  Given an authenticated user's role does not permit them to modify particular information,
     when they attempt to change that information, then the modification is prevented and the
     existing information remains unchanged.
AC3  Not covered here: the assignment check is Event Service's (see above).
AC4  Not covered here: this route has no read-only counterpart; viewing an event is Event Service's
     (SCRUM-9).
AC5  Not covered here: see AC3.
"""
import pytest

from app import create_app
from tests.unit.factories import bearer, signed_in

EVENT_ID = "00000000-0000-0000-0000-000000000001"
USER = "00000000-0000-4000-8000-000000000001"


# AC1 ----

@pytest.mark.parametrize("role", ["Event Coordinator", "Event Coordinator Lead"])
def test_ac1_coordinator_roles_get_past_the_gate_to_the_change_checks(role):
    """Normal: both coordinator roles reach the handler, which then asks for a non-empty change."""
    client = signed_in(create_app().test_client(), role=role)

    response = client.patch(f"/events/{EVENT_ID}/details", json={})

    assert response.status_code == 400
    assert "changes" in response.json["message"]


# AC2 ----

@pytest.mark.parametrize(
    "role", ["Event Organiser", "Venue Staff", "Technical Support", "Safety Officer", "Attendee"]
)
def test_ac2_only_coordinator_roles_may_edit_event_details(role):
    """Failure: other roles are refused on the token's role, and nothing is sent downstream."""
    client = create_app().test_client()

    response = client.patch(
        f"/events/{EVENT_ID}/details", json={"changes": {"eventName": "X"}}, headers=bearer(USER, role)
    )

    assert response.status_code == 403
    assert response.json["code"] == "NOT_ASSIGNED_COORDINATOR"
    assert response.json["message"] == "Your role cannot change this information."
