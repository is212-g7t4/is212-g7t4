"""
SCRUM-46: Attendee Registration and Update Notifications

User Story
----------
As an Attendee, I want to receive notifications about my registration status,
so that I can confirm my place and stay updated on event changes.

Acceptance Criteria
-------------------
AC1: Given an Attendee successfully registers for an event, the system sends an
     in-app notification confirming their registration with the event name,
     date, time, venue, and registration reference number.
AC2: Given an Attendee successfully withdraws their registration, the system
     sends an in-app notification confirming the withdrawal with the event
     name.
AC3: Given an event cancellation takes effect, or a change to its date, time or
     venue is approved and applied, all currently registered Attendees receive
     an in-app notification with the event name and cancellation status or
     updated details, as applicable.

Real
----
- The details captured for an attendee's notices: the event's name and schedule
  when they register, the venue the event is actually booked at, and the
  event's name when they withdraw.
- We check exactly what is passed on for each notice.

Doubled
-------
- Event Service: returns the confirmed event in the route-focused tests [Stub].
- The real `save_registration` HTTP adapter runs against respx routes for Venue
  Availability, Venue and Registration Services [Stub / Mock]. We inspect the
  exact registration request, and any unexpected HTTP call fails the test.
- The route-focused tests replace the Registration Service adapter [Stub]; we
  inspect the exact registration or withdrawal notice details [Mock].
- Sign-in: a test key signs the caller's token (tests/unit/conftest.py) [Stub].

Not proven
----------
- AC1's persisted notification, registration reference and delivery are proved
  by registration-service `test_scrum46_attendee_notifications.py`,
  Notification Service tests and E2E journey J7; this composite only supplies
  the event and venue context.
- AC2's persisted withdrawal notification and delivery are proved by
  registration-service `test_scrum46_attendee_notifications.py`, Notification
  Service tests and E2E journey J7; this composite only supplies the event name.
- AC3 cancellation and approved-change notifications are owned by Event
  Service's SCRUM-46 tests. The attendee-list test elsewhere only proves that a
  cancelled event remains visible with its status; it does not prove that a
  notification was sent.
"""

import pytest
import respx

from app import clients, create_app
from tests.unit.factories import confirmed_event, registration, signed_in


EVENT_ID = "11111111-1111-4111-8111-111111111111"
SNAPSHOT = dict(
    eventName="Workshop",
    startDateTime="2030-03-01T09:00:00",
    endDateTime="2030-03-01T17:00:00",
)
SAVE_DATA = dict(eventId=EVENT_ID, capacity=10, notificationContext=SNAPSHOT)


@pytest.fixture
def attendee():
    return signed_in(create_app().test_client(), role="Attendee")


@pytest.fixture
def service_urls(monkeypatch):
    monkeypatch.setattr(
        clients, "VENUE_AVAILABILITY_SERVICE_URL", "http://availability.test"
    )
    monkeypatch.setattr(clients, "VENUE_SERVICE_URL", "http://venue.test")
    monkeypatch.setattr(clients, "REGISTRATION_SERVICE_URL", "http://registration.test")


def test_ac1_register_adds_approved_venue_name_to_confirmation(service_urls):
    """
    Summary: The registration confirmation notice names the venue the event is actually booked at.
    AC1: Given an Attendee successfully registers for an event, the system
        sends an in-app notification confirming their registration with the
        event name, date, time, venue, and registration reference number.
    Double: Venue Availability holds one approved booking, Venue Service names
        it "Hall A", and Registration Service accepts the registration [Stub];
        any other outside call fails the test, and we check the exact details
        sent for the notice [Mock].
    """
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as http:
        http.get(f"http://availability.test/events/{EVENT_ID}/venue-bookings").respond(
            200,
            json={
                "bookings": [
                    dict(
                        id="booking",
                        status="Approved",
                        venueId="venue",
                        requestedStartTime="2030-03-01T09:00:00",
                    )
                ]
            },
        )
        http.get("http://venue.test/venues/venue").respond(200, json={"venue": {"name": "Hall A"}})
        http.post(
            "http://registration.test/registrations",
            json={**SAVE_DATA, "notificationContext": {**SNAPSHOT, "venueName": "Hall A"}},
        ).respond(201, json={"registration": {"registration_id": "ref"}})

        saved = clients.save_registration(SAVE_DATA)

    assert saved == {"registration_id": "ref"}


def test_ac1_register_when_no_approved_venue_raises_error(service_urls):
    """
    Summary: If the event has no approved venue to name in the notice, the registration is not sent, rather than confirmed with a missing venue.
    AC1: Given an Attendee successfully registers for an event, the system
        sends an in-app notification confirming their registration with the
        event name, date, time, venue, and registration reference number.
    Double: Venue Availability holds no bookings for the event [Stub]; any
        other outside call fails the test.
    """
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as http:
        http.get(f"http://availability.test/events/{EVENT_ID}/venue-bookings").respond(200, json={"bookings": []})

        with pytest.raises(ValueError, match="Approved venue unavailable"):
            clients.save_registration(SAVE_DATA)


def test_ac1_register_sends_event_name_and_schedule_for_the_notice(attendee, mocker):
    """
    Summary: Registering passes on the event's name, start and end time for the confirmation notice, as they are when the attendee registers.
    AC1: Given an Attendee successfully registers for an event, the system
        sends an in-app notification confirming their registration with the
        event name, date, time, venue, and registration reference number.
    Double: The event is confirmed and open [Stub]; we check the notice details
        Registration Service is asked to save with the registration [Mock].
    """
    mocker.patch("app.routes.get_confirmed_event", return_value=confirmed_event())
    save = mocker.patch("app.routes.save_registration", return_value={"registration_id": "registration-1"})

    attendee.post("/registrations", json={"eventId": confirmed_event()["id"]})

    assert save.call_args.args[0]["notificationContext"] == {
        "eventName": "Community Workshop",
        "startDateTime": "2099-11-10T09:00:00+08:00",
        "endDateTime": "2099-11-10T12:00:00+08:00",
    }


def test_ac2_withdraw_sends_event_name_for_the_notice(attendee, mocker):
    """
    Summary: Withdrawing passes on the event's name for the withdrawal notice, as it is when the attendee withdraws.
    AC2: Given an Attendee successfully withdraws their registration, the
        system sends an in-app notification confirming the withdrawal with the
        event name.
    Double: The attendee has a confirmed registration and the event is open for
        withdrawal [Stub]; we check the event name Registration Service is given
        with the withdrawal [Mock].
    """
    mocker.patch("app.routes.get_attendee_registrations", return_value=[registration()])
    mocker.patch("app.routes.get_confirmed_event", return_value=confirmed_event())
    withdraw = mocker.patch("app.routes.withdraw_saved_registration", return_value=registration(status="Withdrawn"))

    attendee.patch(f"/registrations/{registration()['registration_id']}/withdraw")

    withdraw.assert_called_once_with(registration()["registration_id"], "Community Workshop")
