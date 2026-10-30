"""SCRUM-167 Record Venue Safety Information: Safety Check Service integration tests.

Story:      As a Venue Staff member, I want to record a venue's emergency access details
            and known operational restrictions, so that the Safety Officer can take them
            into account when reviewing events at that venue.
Real:       Flask app, GET /safety-checks/<eventId>/review, the officer and event-status
            checks, the ThreadPoolExecutor fan-out, and the real httpx code in
            app/clients.py.
Doubled:    with respx: User Service (officer role lookup), Event Service
            (GET /events/<id>), Venue Availability (GET /events/<id>/venue-bookings),
            Equipment Request (GET /equipment-requests), Safety Check Record
            (GET /safety-check-records), Venue Service (GET /venues), Equipment Service
            (GET /equipment).
Not proven: that Venue Service stores or returns these fields (Venue Service's tests);
            Supabase sign-in itself (the officer is a token signed with a test key, SCRUM-8).

AC1  Given authorised Venue Staff edit a venue, when they enter emergency access details
     (e.g. exits, assembly point, emergency vehicle access) and known restrictions (e.g.
     noise curfew, no open flames, floor load limit), then the details are saved with the
     venue and shown on its details page.
     Covered here only as the story's "so that": the saved values reach the Safety
     Officer's review. Saving and the details page run in Venue Service and the frontend.
AC2  Given a venue has no safety information recorded, when it is viewed, then the fields
     show "Not provided" rather than appearing blank.
     Covered here as: no recorded values reach the review as null, which the review UI
     renders as "Not provided".
AC3  Given safety information is updated, when it is saved, then the editor and timestamp
     are recorded.
     Not covered here: the stamp is written by Venue Service.
AC4  Given a user who is not Venue Staff, when they attempt to edit venue safety
     information through the UI or API, then the change is rejected and the existing
     values are unchanged.
     Not covered here: the role check runs in Venue Service; this service only reads.
"""

import pytest
from httpx import Response

import app.clients as service_clients
from tests.integration.factories import (
    EVENT_ID,
    HALL_ID,
    OFFICER_ID,
    ROOM_ID,
    booking,
    event,
    safety_round,
    venue,
)
from tests.unit.factories import signed_in

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

HALL_EMERGENCY = "Exits on north and south walls\nAssembly point: front lawn"
HALL_RESTRICTIONS = "Noise curfew 10pm\nNo open flames"


def stub_review(router, bookings, venues_response):
    """Every downstream read the review makes, with the URLs and queries app/clients.py sends."""
    router.get(
        f"{service_clients.EVENT_SERVICE_URL}/events/{EVENT_ID}",
        params={"viewerRole": "Safety Officer"},
    ).mock(return_value=Response(200, json=event()))
    router.get(
        f"{service_clients.VENUE_AVAILABILITY_SERVICE_URL}/events/{EVENT_ID}/venue-bookings"
    ).mock(return_value=Response(200, json={"bookings": bookings}))
    router.get(
        f"{service_clients.EQUIPMENT_REQUEST_SERVICE_URL}/equipment-requests",
        params={"eventId": EVENT_ID},
    ).mock(return_value=Response(200, json={"requests": []}))
    router.get(
        f"{service_clients.SAFETY_CHECK_RECORD_SERVICE_URL}/safety-check-records",
        params={"eventId": EVENT_ID},
    ).mock(return_value=Response(200, json={"safetyChecks": [safety_round()]}))
    router.get(f"{service_clients.EQUIPMENT_SERVICE_URL}/equipment").mock(
        return_value=Response(200, json={"equipment": []})
    )
    return router.get(f"{service_clients.VENUE_SERVICE_URL}/venues").mock(
        return_value=venues_response
    )


def get_review(client):
    return signed_in(client, OFFICER_ID, "Safety Officer").get(f"/safety-checks/{EVENT_ID}/review")


# AC1 ----------------------------------------------------------------------


def test_ac1_safety_officer_review_shows_recorded_emergency_access_and_restrictions(client, stubs):
    """Normal: what Venue Staff recorded reaches the Safety Officer's review unchanged."""
    venues = stub_review(
        stubs,
        [booking(HALL_ID, "booking-hall")],
        Response(200, json={"venues": [venue(HALL_ID, "Harbour Hall", HALL_EMERGENCY, HALL_RESTRICTIONS)]}),
    )

    response = get_review(client)

    assert response.status_code == 200
    reviewed = response.get_json()["venues"][0]
    assert reviewed["venueId"] == HALL_ID
    assert reviewed["emergencyAccess"] == HALL_EMERGENCY
    assert reviewed["restrictions"] == HALL_RESTRICTIONS
    assert venues.call_count == 1
    assert all(route.call_count == 1 for route in stubs.routes)
    # SCRUM-8: the officer is identified downstream by their forwarded token.
    assert {call.request.headers["Authorization"] for call in stubs.calls} == {client.environ_base["HTTP_AUTHORIZATION"]}


def test_ac1_two_venues_each_show_their_own_safety_information(client, stubs):
    """Normal: with two booked venues, each review entry carries its own venue's values."""
    stub_review(
        stubs,
        [booking(HALL_ID, "booking-hall"), booking(ROOM_ID, "booking-room")],
        Response(200, json={"venues": [
            venue(ROOM_ID, "River Room", "Single exit to corridor B", "Floor load limit 300 kg/m²"),
            venue(HALL_ID, "Harbour Hall", HALL_EMERGENCY, HALL_RESTRICTIONS),
        ]}),
    )

    response = get_review(client)

    assert response.status_code == 200
    assert [
        (v["venueId"], v["emergencyAccess"], v["restrictions"])
        for v in response.get_json()["venues"]
    ] == [
        (HALL_ID, HALL_EMERGENCY, HALL_RESTRICTIONS),
        (ROOM_ID, "Single exit to corridor B", "Floor load limit 300 kg/m²"),
    ]


def test_ac1_venue_service_failure_is_502_without_partial_review(client, stubs):
    """Failure: proves the error path, not storage; no review is shown without venue data."""
    stub_review(stubs, [booking(HALL_ID, "booking-hall")], Response(500, json={"message": "boom"}))

    response = get_review(client)

    assert response.status_code == 502
    assert response.get_json() == {"message": "Unable to check the event's arrangements right now."}


# AC2 ----------------------------------------------------------------------


def test_ac2_venue_without_safety_information_reaches_the_review_as_null(client, stubs):
    """Boundary: nothing recorded stays null, so the review UI shows "Not provided"."""
    stub_review(
        stubs,
        [booking(HALL_ID, "booking-hall")],
        Response(200, json={"venues": [venue(HALL_ID, "Harbour Hall")]}),
    )

    response = get_review(client)

    assert response.status_code == 200
    reviewed = response.get_json()["venues"][0]
    assert reviewed["emergencyAccess"] is None
    assert reviewed["restrictions"] is None
