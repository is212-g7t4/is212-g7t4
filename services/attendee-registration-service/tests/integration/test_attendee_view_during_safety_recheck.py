"""SCRUM-153 Re-check Safety After High-Impact Changes and SCRUM-150 Approve Operational Safety Check: Attendee Registration Service integration tests.

Story (SCRUM-153): As an Event Coordinator, I want a safety approval to be withdrawn when a high-impact detail changes afterwards, so that the event is never prepared on the basis of an outdated safety review.
Story (SCRUM-150): As a Safety Officer, I want to approve an event's operational safety arrangements, so that the event can proceed to preparation.
Real:       the Flask app, the /registrations orchestration and the app/clients.py httpx calls.
Doubled:    Event, Registration and User Services at their HTTP boundaries with respx.
Not proven: the overlay rule inside Event Service and persistence.

SCRUM-153
AC1  Given an event is 'Confirmed', when its date/time, expected attendance, venue requirements, equipment requirements or accessibility needs change, then its status returns to 'Pending Safety Check' and the coordinator is told why.
     Not covered here: owned by Event Service's test_scrum153_recheck_safety_after_high_impact_changes.py.
AC2  Given only a low-impact field changes (name, description, purpose, registration needs), then the event stays 'Confirmed'.
     Not covered here: owned by Event Service's test_scrum153_recheck_safety_after_high_impact_changes.py.
AC3  Given a safety approval is withdrawn, then it stays visible in the event's safety history.
     Not covered here: owned by Event Service's test_scrum153_recheck_safety_after_high_impact_changes.py.
AC4  Given a high-impact change to a 'Confirmed' event is waiting for its new safety check, when a registered Attendee views the event, then they still see the previously approved details, and the changed details are shown to them only after the Safety Officer approves the new safety check.
AC5  Given the new safety check ends without approval (changes requested or the event is cancelled), then registered Attendees are never shown the unapproved change, and they continue to see the last approved details or the cancellation.
     Not covered here: which details apply is decided by Event Service; this composite passes them through exactly as in AC4.
SCRUM-150
AC1  Given an event is 'Pending Safety Check', when I approve it, then its status changes to 'Confirmed'.
     Not covered here: owned by Event Service's test_scrum150_safety_approve_status.py.
AC2  Given I approve an event, then the safety check is recorded with the status 'Safety Approved', together with my identity, the approval timestamp and any optional remarks, in the event's history.
     Not covered here: owned by Event Service's test_scrum150_safety_approve_status.py.
AC3  Given an event is not 'Pending Safety Check', then the approve action is not available and an API call is rejected without changing the event.
     Not covered here: owned by Event Service's test_scrum150_safety_approve_status.py.
AC4  Given the safety check I approve follows a high-impact change, when I approve it, then the changed details become visible to registered Attendees.
AC = acceptance criterion; DR = supporting design rule.
"""

import pytest
import respx
from httpx import Response

import app.clients as service_clients
from tests.integration.factories import ATTENDEE_ID, EVENT_ID, attendee_summary, event, registration

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


def stub_registration_lookup(router):
    # Shape: services/registration-service/app/routes.py GET /registrations.
    return router.get(
        f"{service_clients.REGISTRATION_SERVICE_URL}/registrations",
    ).mock(return_value=Response(200, json={"registrations": [registration()]}))


def stub_user(router):
    # Shape: services/user-service GET /users/<id>.
    return router.get(f"{service_clients.USER_SERVICE_URL}/users/{ATTENDEE_ID}").mock(
        return_value=Response(200, json={"username": "Synthetic", "email": "attendee@example.com"}))


def stub_event_catalogue(router, events):
    # Shape: services/event-service/app/__init__.py GET /events/registration (Confirmed only).
    return router.get(f"{service_clients.EVENT_SERVICE_URL}/events/registration").mock(
        return_value=Response(200, json={"events": events}))


def stub_attendee_summaries(router, response):
    # Shape: services/event-service/app/models.py::list_attendee_event_summaries.
    return router.get(f"{service_clients.EVENT_SERVICE_URL}/events/attendee-summaries").mock(
        return_value=response)


# AC4 -------------------------------------------------------------------------


def test_ac4_registered_pending_event_reaches_the_attendee_with_approved_details(client):
    """Normal: the event is pending its re-check, so it is missing from the Confirmed
    catalogue and fetched from attendee-summaries with the approved window and venue.
    """
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_registration_lookup(router)
        stub_user(router)
        stub_event_catalogue(router, [])
        summaries = stub_attendee_summaries(router, Response(200, json={"events": [attendee_summary()]}))

        response = client.get("/registrations")

    assert response.status_code == 200
    [item] = response.json["registrations"]
    assert item["event"]["preferredStartDate"] == "2030-03-01T09:00:00"
    assert item["event"]["preferredEndDate"] == "2030-03-01T17:00:00"
    assert item["event"]["attendeeVenueName"] == "Hall A"
    assert dict(summaries.calls[0].request.url.params) == {"ids": EVENT_ID}


# SCRUM-150 AC4 ---------------------------------------------------------------


def test_scrum150_ac4_confirmed_event_uses_catalogue_and_skips_attendee_summaries(client):
    """Normal: after approval the event is Confirmed with its new times; there is no
    attendee-summaries stub, so assert_all_mocked proves no history lookup was made.
    """
    approved = event(start="2030-03-02T09:00:00+08:00")
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_registration_lookup(router)
        stub_user(router)
        stub_event_catalogue(router, [approved])

        response = client.get("/registrations")

    assert response.status_code == 200
    assert response.json["registrations"][0]["event"]["preferredStartDate"] == "2030-03-02T09:00:00+08:00"


# DR --------------------------------------------------------------------------


def test_dr_attendee_summaries_outage_is_reported_as_502(client):
    """Failure: Event Service's attendee-summaries answers 503; the attendee gets a 502."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_registration_lookup(router)
        stub_user(router)
        stub_event_catalogue(router, [])
        stub_attendee_summaries(router, Response(503, json={"message": "DATABASE_URL is not configured."}))

        response = client.get("/registrations")

    assert response.status_code == 502
    assert response.json["message"] == "Unable to load your registrations right now."
