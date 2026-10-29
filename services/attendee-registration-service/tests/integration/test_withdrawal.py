"""SCRUM-39 Withdraw Registration: Attendee Registration Service integration tests.

Story:      As an Attendee, I want to withdraw my registration for an event,
            so that I can free up my place for someone else if I can no longer attend.
Real:       Flask app, withdrawal orchestration, validation, and app/clients.py httpx calls.
Doubled:    Event Service and Registration Service at their HTTP boundaries with respx.
Not proven: persistence inside Registration Service, or Supabase sign-in itself (the
            attendee is a token signed with a test key, SCRUM-8).

AC1  The Attendee can access a "Withdraw" option from their registered event details page.
     Not covered here: button visibility belongs to the frontend component suite.
AC2  Given the Attendee confirms withdrawal, the system changes the registration status
     to 'Withdrawn' and displays a confirmation message.
AC3  The withdrawal is recorded with timestamp for auditability.
     Not covered here: timestamp persistence belongs to Registration Service.
AC4  Given the Attendee attempts to withdraw after the registration withdrawal deadline
     (if applicable), the system displays a message to contact the organisers and the
     withdrawal does not go through.
"""

import json

import pytest
import respx
from httpx import Response

import app.clients as service_clients
from tests.integration.factories import EVENT_ID, REGISTRATION_ID, event, registration

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


def stub_registration_lookup(router):
    return router.get(
        f"{service_clients.REGISTRATION_SERVICE_URL}/registrations",
    ).mock(return_value=Response(200, json={"registrations": [registration()]}))


def stub_event_catalogue(router, event_payload):
    return router.get(
        f"{service_clients.EVENT_SERVICE_URL}/events/registration"
    ).mock(return_value=Response(200, json={"events": [event_payload]}))


# AC2 -------------------------------------------------------------------------


def test_ac2_confirmed_withdrawal_returns_confirmation_and_forwards_identity(client):
    """Normal: the composite joins its real route, validation and HTTP client calls."""
    withdrawn = {
        **registration(status="Withdrawn"),
        "withdrawn_at": "2029-12-02T02:30:00+00:00",
    }
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        lookup = stub_registration_lookup(router)
        stub_event_catalogue(router, event())
        withdrawal = router.patch(
            f"{service_clients.REGISTRATION_SERVICE_URL}/registrations/{REGISTRATION_ID}/withdraw"
        ).mock(return_value=Response(200, json={"registration": withdrawn}))

        response = client.patch(
            f"/registrations/{REGISTRATION_ID}/withdraw",
            json={},
        )

    assert response.status_code == 200
    assert response.json["message"] == "Registration withdrawn for Community Workshop."
    assert response.json["registration"]["status"] == "Withdrawn"
    assert response.json["registration"]["withdrawn_at"] == "2029-12-02T02:30:00+00:00"
    # SCRUM-46: the real HTTP adapter must forward the action-time event name,
    # not just identity, so a delayed withdrawal alert needs no later name lookup.
    assert json.loads(withdrawal.calls[0].request.content) == {"notificationContext": {"eventName": "Community Workshop"}}
    # SCRUM-8: the attendee is identified downstream by their forwarded token, not an ID.
    for call in (lookup.calls[0], withdrawal.calls[0]):
        assert call.request.headers["Authorization"] == client.environ_base["HTTP_AUTHORIZATION"]
    assert not lookup.calls[0].request.url.params


# AC4 -------------------------------------------------------------------------


def test_ac4_expired_organiser_deadline_refuses_withdrawal_and_contacts_organisers(client):
    """Conflict: an explicit elapsed cutoff takes precedence over a future event start."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_registration_lookup(router)
        stub_event_catalogue(
            router,
            event(withdrawal_deadline="2020-03-01T08:00:00+08:00"),
        )

        response = client.patch(
            f"/registrations/{REGISTRATION_ID}/withdraw",
            json={},
        )

    assert response.status_code == 409
    assert response.json["code"] == "WITHDRAWAL_DEADLINE_PASSED"
    assert response.json["message"] == (
        "The withdrawal deadline has passed. Please contact the event organisers."
    )


def test_ac4_event_start_is_the_deadline_when_organiser_did_not_set_one(client):
    """Boundary: a missing optional cutoff falls back to the event start timestamp."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_registration_lookup(router)
        stub_event_catalogue(
            router,
            event(withdrawal_deadline=None, start="2020-03-01T09:00:00+08:00"),
        )

        response = client.patch(
            f"/registrations/{REGISTRATION_ID}/withdraw",
            json={},
        )

    assert response.status_code == 409
    assert response.json["code"] == "WITHDRAWAL_DEADLINE_PASSED"
    assert "contact the event organisers" in response.json["message"]


def test_ac2_registration_service_failure_does_not_report_success(client):
    """Failure: a downstream write outage must not produce a withdrawal confirmation."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_registration_lookup(router)
        stub_event_catalogue(router, event())
        router.patch(
            f"{service_clients.REGISTRATION_SERVICE_URL}/registrations/{REGISTRATION_ID}/withdraw"
        ).mock(return_value=Response(503, json={"message": "database unavailable"}))

        response = client.patch(
            f"/registrations/{REGISTRATION_ID}/withdraw",
            json={},
        )

    assert response.status_code == 502
    assert response.json["message"] == "Unable to withdraw this registration right now."
