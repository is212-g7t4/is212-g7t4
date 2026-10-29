"""SCRUM-46 Attendee Registration and Update Notifications: attendee composite unit tests.

Story: As an Attendee, I want to receive notifications about my registration status, so that I can confirm my place and stay updated on event changes.
Real: history route and identity scoping. Doubled: downstream HTTP adapters.
Not proven: authentication, downstream SQL or delivery.
AC1 Given an Attendee successfully registers for an event, the system sends an in-app notification confirming their registration with the event name, date, time, venue, and registration reference number.
AC2 Given an Attendee successfully withdraws their registration, the system sends an in-app notification confirming the withdrawal with the event name.
AC3 Given an event cancellation takes effect, or a change to its date, time or venue is approved and applied, all currently registered Attendees receive an in-app notification with the event name and cancellation status or updated details, as applicable.
AC1/2 delivery belongs to Registration/Workflow; AC3 historical destination is covered here.
AC = acceptance criterion; DR = supporting design rule.
"""

from app import create_app
from app import routes
from tests.unit.factories import signed_in


# AC3 ---- a cancellation notification retains a usable history destination
def test_ac3_cancelled_events_remain_visible_without_changing_registration_status(
    monkeypatch,
):
    """Normal: an attendee owns a Confirmed registration whose event is now Cancelled.
    Request their history with downstream adapters doubled; the real route must
    retain that event and the original registration status. Otherwise a delivered
    cancellation link would lose its destination just when the attendee needs it.
    """
    user = "22222222-2222-4222-8222-222222222222"
    event = "11111111-1111-4111-8111-111111111111"
    ref = "33333333-3333-4333-8333-333333333333"
    monkeypatch.setattr(
        routes,
        "get_attendee_registrations",
        lambda: [
            dict(
                registration_id=ref,
                event_id=event,
                attendee_id=user,
                status="Confirmed",
            )
        ],
    )
    monkeypatch.setattr(
        routes,
        "get_user",
        lambda attendee: dict(username="Synthetic", email="user@example.com"),
    )
    monkeypatch.setattr(routes, "get_confirmed_events", lambda: [])
    monkeypatch.setattr(
        routes,
        "get_historical_events",
        lambda ids: [dict(id=event, eventName="Workshop", status="Cancelled")],
        raising=False,
    )
    response = signed_in(create_app().test_client()).get(f"/registrations")
    assert response.status_code == 200
    assert response.json["registrations"] == [
        dict(
            registration=dict(
                registration_id=ref,
                event_id=event,
                attendee_id=user,
                status="Confirmed",
                attendee_name="Synthetic",
                attendee_email="user@example.com",
                attendee_organization="",
            ),
            event=dict(id=event, eventName="Workshop", status="Cancelled"),
        )
    ]


# Supporting DR ---- historical summary adapter contract
def test_dr_history_adapter_maps_public_summaries_and_batches_only_owned_registration_events(
    monkeypatch,
):
    """Boundary: ask the real history adapter for no IDs, then one owned event ID.
    A mocked HTTP summary supplies a cancelled event and its schedule; expect the
    public fields plus the page's legacy date aliases and exact batched query.
    This keeps historical links usable without requiring the event to be Confirmed.
    """
    from unittest.mock import Mock
    from app import clients

    response = Mock()
    response.json.return_value = {
        "events": [
            dict(
                id="event",
                eventName="Workshop",
                status="Cancelled",
                startTime="2030-03-01T09:00:00",
                endTime="2030-03-01T17:00:00",
                attendeeVenueName=None,
            )
        ]
    }
    get = Mock(return_value=response)
    monkeypatch.setattr(clients.httpx, "get", get)
    assert clients.get_historical_events([]) == []
    events = clients.get_historical_events(["event"])
    assert events == [
        dict(
            id="event",
            eventName="Workshop",
            status="Cancelled",
            startTime="2030-03-01T09:00:00",
            endTime="2030-03-01T17:00:00",
            attendeeVenueName=None,
            preferredStartDate="2030-03-01T09:00:00",
            preferredEndDate="2030-03-01T17:00:00",
            description="",
            purpose="",
        )
    ]
    assert get.call_args.args == (f"{clients.EVENT_SERVICE_URL}/events/attendee-summaries",)
    assert get.call_args.kwargs == dict(params={"ids": "event"}, headers={}, timeout=5)
    response.raise_for_status.assert_called_once()


import pytest
import respx
from app import clients


# AC1 ---- capture actual arrangements before saving confirmation
@pytest.mark.parametrize("state", ["confirmed", "no-approved"])
def test_ac1_composite_captures_actual_venue_before_saving_the_action(
    monkeypatch, state
):
    """Boundary: save a registration through the real HTTP adapter with an event snapshot.
    The confirmed case doubles an Approved booking and Hall A: expect that venue in
    the exact owner request. The no-approved case must raise before saving anything.
    Capturing actual arrangements now prevents delayed confirmation from using guesses;
    respx controls all remote responses, not the adapter's request-building code.
    """
    event = "11111111-1111-4111-8111-111111111111"
    monkeypatch.setattr(
        clients, "VENUE_AVAILABILITY_SERVICE_URL", "http://availability.test"
    )
    monkeypatch.setattr(clients, "VENUE_SERVICE_URL", "http://venue.test")
    monkeypatch.setattr(clients, "REGISTRATION_SERVICE_URL", "http://registration.test")
    snapshot = dict(
        eventName="Workshop",
        startDateTime="2030-03-01T09:00:00",
        endDateTime="2030-03-01T17:00:00",
    )
    data = dict(
        eventId=event, capacity=10, notificationContext=snapshot
    )
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as http:
        # Venue Availability app/models.py::serialize and Venue app/__init__.py::venue.
        http.get(f"http://availability.test/events/{event}/venue-bookings").respond(
            200,
            json={
                "bookings": []
                if state == "no-approved"
                else [
                    dict(
                        id="booking",
                        status="Approved",
                        venueId="venue",
                        requestedStartTime="2030-03-01T09:00:00",
                    )
                ]
            },
        )
        if state == "confirmed":
            http.get("http://venue.test/venues/venue").respond(
                200, json={"venue": {"name": "Hall A"}}
            )
            # Registration app/__init__.py::add_registration returns the owner registration wrapper.
            saved = http.post(
                "http://registration.test/registrations",
                json={
                    **data,
                    "notificationContext": {**snapshot, "venueName": "Hall A"},
                },
            ).respond(201, json={"registration": {"registration_id": "ref"}})
            assert clients.save_registration(data) == {"registration_id": "ref"}
            assert saved.call_count == 1
        else:
            with pytest.raises(ValueError):
                clients.save_registration(data)
