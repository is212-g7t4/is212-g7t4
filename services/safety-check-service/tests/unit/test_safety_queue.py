"""SCRUM-162: GET /safety-checks/queue.

As a Safety Officer, I want to view a list of events awaiting an Operational
Safety Check, so that I know which events I need to review.

AC1 The queue shows only events with status 'Pending Safety Check'.
AC2 Each entry shows event name, event date/time, venue(s), expected
    attendance and submission date, with the nearest event date first.
AC3 Given an event was resubmitted after an earlier decision, then it is
    labelled as a resubmission.
AC4 Given a decision is recorded for an event, then it no longer appears in
    the queue.

Every downstream call is a monkeypatched `app.clients` wrapper, so these
tests exercise the orchestration and the error mapping, not HTTP
(`test_clients.py` covers that).
"""
import logging

import pytest
from flask import g

from app import clients, create_app
from tests.unit.factories import OFFICER_ID, booking, record, user, signed_in

EVENT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
EVENT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
EVENT_C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
HALL = "88888888-8888-4888-8888-888888888888"
ROOM = "89898989-8989-4989-8989-898989898989"


def pending_event(event_id, start, name="Community Workshop", attendance="120"):
    """A 'Pending Safety Check' event as Event Service lists it."""
    return {
        "id": event_id,
        "eventName": name,
        "status": "Pending Safety Check",
        "preferredStartDate": start,
        "preferredEndDate": start.replace("09:00", "17:00") if start else "",
        "expectedAttendance": attendance,
    }


class Downstream:
    """Recorded stand-ins for every atomic the queue reads."""

    def __init__(self):
        self.user = user(role="Safety Officer")
        self.events = [pending_event(EVENT_A, "2026-11-12T09:00:00")]
        self.venues = [
            {"id": HALL, "name": "Main Hall"},
            {"id": ROOM, "name": "Seminar Room 2"},
        ]
        self.rounds = {EVENT_A: [record(eventId=EVENT_A)]}
        self.bookings = {EVENT_A: [booking(eventId=EVENT_A, venueId=HALL)]}
        self.calls = []
        self.fail = {}

    def _maybe_fail(self, name):
        if name in self.fail:
            raise self.fail[name]

    def get_user(self, user_id):
        self.calls.append(("get_user", user_id))
        self._maybe_fail("get_user")
        return self.user

    def list_events_by_status(self, status, viewer_role):
        viewer_id = g.user_id  # The downstream service reads this from the forwarded token.
        self.calls.append(("list_events", status, viewer_id, viewer_role))
        self._maybe_fail("list_events")
        return self.events

    def list_venues(self):
        self.calls.append(("list_venues",))
        self._maybe_fail("list_venues")
        return self.venues

    def list_safety_check_records(self, event_id, status=None):
        self.calls.append(("list_records", event_id, status))
        self._maybe_fail("list_records")
        return self.rounds.get(event_id, [])

    def get_event_venue_bookings(self, event_id):
        self.calls.append(("bookings", event_id))
        self._maybe_fail("bookings")
        return self.bookings.get(event_id, [])

    def names(self):
        return [call[0] for call in self.calls]


@pytest.fixture
def downstream(monkeypatch):
    stub = Downstream()
    for name in (
        "get_user",
        "list_events_by_status",
        "list_venues",
        "list_safety_check_records",
        "get_event_venue_bookings",
    ):
        monkeypatch.setattr(f"app.clients.{name}", getattr(stub, name))
    return stub


@pytest.fixture
def client():
    return signed_in(create_app().test_client())


def queue(client, safety_officer_id=OFFICER_ID):
    return client.get(
        "/safety-checks/queue", query_string={"safetyOfficerId": safety_officer_id}
    )


# --- AC1, AC2: what an entry shows --------------------------------------------


def test_entry_shows_name_date_venue_attendance_and_submission_date(client, downstream):
    """AC2: every field the officer needs to pick what to review next."""
    response = queue(client)

    assert response.status_code == 200
    assert response.get_json()["events"] == [
        {
            "eventId": EVENT_A,
            "eventName": "Community Workshop",
            "preferredStartDate": "2026-11-12T09:00:00",
            "preferredEndDate": "2026-11-12T17:00:00",
            "expectedAttendance": "120",
            "venues": [{"id": HALL, "name": "Main Hall"}],
            "safetyCheckId": record()["id"],
            "submittedAt": "2026-11-01T02:30:00+00:00",
            "roundNumber": 1,
            "resubmission": False,
        }
    ]


def test_only_pending_safety_check_events_are_requested(client, downstream):
    """AC1: Event Service is asked for 'Pending Safety Check' only, as the officer."""
    queue(client)

    assert ("list_events", "Pending Safety Check", OFFICER_ID, "Safety Officer") in (
        downstream.calls
    )


def test_the_open_round_is_read_for_each_event(client, downstream):
    """AC2: the submission date comes from the event's open ('Pending') round."""
    queue(client)

    assert ("list_records", EVENT_A, "Pending") in downstream.calls


def test_empty_queue(client, downstream):
    """AC1: nothing pending is an empty list, not an error."""
    downstream.events = []

    response = queue(client)

    assert response.status_code == 200
    assert response.get_json() == {"events": []}
    assert "list_records" not in downstream.names()


def test_nearest_event_date_first(client, downstream):
    """AC2: sorted by event date, nearest first, whatever order arrives."""
    downstream.events = [
        pending_event(EVENT_B, "2026-12-01T09:00:00", name="December"),
        pending_event(EVENT_A, "2026-11-12T09:00:00", name="November"),
        pending_event(EVENT_C, "2026-11-20T09:00:00", name="Late November"),
    ]
    downstream.rounds = {
        event_id: [record(eventId=event_id)] for event_id in (EVENT_A, EVENT_B, EVENT_C)
    }

    names = [entry["eventName"] for entry in queue(client).get_json()["events"]]

    assert names == ["November", "Late November", "December"]


def test_same_start_time_is_ordered_by_event_id(client, downstream):
    """AC2 boundary: a tie still has a stable order, so the list doesn't jump about."""
    downstream.events = [
        pending_event(EVENT_B, "2026-11-12T09:00:00"),
        pending_event(EVENT_A, "2026-11-12T09:00:00"),
    ]
    downstream.rounds = {
        event_id: [record(eventId=event_id)] for event_id in (EVENT_A, EVENT_B)
    }

    ids = [entry["eventId"] for entry in queue(client).get_json()["events"]]

    assert ids == [EVENT_A, EVENT_B]


def test_an_undated_event_goes_last(client, downstream):
    """AC2 boundary: an event with no date can't be 'nearest'."""
    downstream.events = [
        pending_event(EVENT_B, ""),
        pending_event(EVENT_A, "2026-11-12T09:00:00"),
    ]
    downstream.rounds = {
        event_id: [record(eventId=event_id)] for event_id in (EVENT_A, EVENT_B)
    }

    ids = [entry["eventId"] for entry in queue(client).get_json()["events"]]

    assert ids == [EVENT_A, EVENT_B]


def test_missing_event_fields_come_back_blank(client, downstream):
    """A sparse event still renders rather than breaking the list."""
    downstream.events = [{"id": EVENT_A, "status": "Pending Safety Check"}]

    entry = queue(client).get_json()["events"][0]

    assert entry["eventName"] == ""
    assert entry["preferredStartDate"] == ""
    assert entry["preferredEndDate"] == ""
    assert entry["expectedAttendance"] == ""


# --- AC2: venues ----------------------------------------------------------------


def test_every_venue_is_listed(client, downstream):
    """AC2: 'venue(s)' — an event can be booked into more than one venue."""
    downstream.bookings = {
        EVENT_A: [
            booking(eventId=EVENT_A, venueId=HALL, booking_id="b1"),
            booking(eventId=EVENT_A, venueId=ROOM, booking_id="b2"),
        ]
    }

    venues = queue(client).get_json()["events"][0]["venues"]

    assert venues == [
        {"id": HALL, "name": "Main Hall"},
        {"id": ROOM, "name": "Seminar Room 2"},
    ]


def test_a_venue_booked_twice_is_listed_once(client, downstream):
    """Two bookings in the same hall (say, two days) are still one venue."""
    downstream.bookings = {
        EVENT_A: [
            booking(eventId=EVENT_A, venueId=HALL, booking_id="b1"),
            booking(eventId=EVENT_A, venueId=HALL, booking_id="b2"),
        ]
    }

    venues = queue(client).get_json()["events"][0]["venues"]

    assert venues == [{"id": HALL, "name": "Main Hall"}]


@pytest.mark.parametrize("status", ["Cancelled", "Expired", "Rejected"])
def test_released_bookings_are_not_venues(status, client, downstream):
    """A booking that no longer holds the venue isn't where the event happens."""
    downstream.bookings = {
        EVENT_A: [
            booking(eventId=EVENT_A, venueId=HALL, booking_id="b1"),
            booking(status=status, eventId=EVENT_A, venueId=ROOM, booking_id="b2"),
        ]
    }

    venues = queue(client).get_json()["events"][0]["venues"]

    assert venues == [{"id": HALL, "name": "Main Hall"}]


def test_a_venue_missing_from_the_catalogue_is_still_shown(client, downstream):
    """The booking still counts; only its name is unknown."""
    downstream.venues = []

    venues = queue(client).get_json()["events"][0]["venues"]

    assert venues == [{"id": HALL, "name": "Unknown venue"}]


def test_no_live_booking_is_an_empty_venue_list(client, downstream):
    downstream.bookings = {}

    assert queue(client).get_json()["events"][0]["venues"] == []


# --- AC3: resubmissions ---------------------------------------------------------


def test_first_round_is_not_a_resubmission(client, downstream):
    """AC3 boundary: round 1 is the first submission."""
    entry = queue(client).get_json()["events"][0]

    assert entry["roundNumber"] == 1
    assert entry["resubmission"] is False


@pytest.mark.parametrize("round_number", [2, 3])
def test_a_later_round_is_a_resubmission(round_number, client, downstream):
    """AC3: any round after the first follows an earlier decision."""
    downstream.rounds = {EVENT_A: [record(round_number=round_number, eventId=EVENT_A)]}

    entry = queue(client).get_json()["events"][0]

    assert entry["roundNumber"] == round_number
    assert entry["resubmission"] is True


def test_resubmission_shows_the_latest_submission_date(client, downstream):
    """AC2/AC3: the date shown is when it was resubmitted, not first submitted."""
    downstream.rounds = {
        EVENT_A: [
            record(round_number=2, eventId=EVENT_A, submittedAt="2026-11-05T01:00:00+00:00")
        ]
    }

    entry = queue(client).get_json()["events"][0]

    assert entry["submittedAt"] == "2026-11-05T01:00:00+00:00"


# --- AC4: decided events drop out ------------------------------------------------


def test_a_decided_event_no_longer_appears(client, downstream):
    """AC4: once decided the event leaves 'Pending Safety Check', so it isn't listed.

    The queue is built only from what Event Service returns for that status;
    a decision moves the event to 'Confirmed', 'Safety Changes Requested' or
    'Cancelled', and the next read leaves it out.
    """
    downstream.events = [
        pending_event(EVENT_A, "2026-11-12T09:00:00"),
        pending_event(EVENT_B, "2026-11-13T09:00:00"),
    ]
    downstream.rounds = {
        event_id: [record(eventId=event_id)] for event_id in (EVENT_A, EVENT_B)
    }
    assert len(queue(client).get_json()["events"]) == 2

    downstream.events = [pending_event(EVENT_B, "2026-11-13T09:00:00")]

    ids = [entry["eventId"] for entry in queue(client).get_json()["events"]]
    assert ids == [EVENT_B]


def test_event_with_no_open_round_is_left_out_and_logged(client, downstream, caplog):
    """Out of step: nothing to decide, so no row — but someone should know."""
    downstream.events = [
        pending_event(EVENT_A, "2026-11-12T09:00:00"),
        pending_event(EVENT_B, "2026-11-13T09:00:00"),
    ]
    downstream.rounds = {EVENT_B: [record(eventId=EVENT_B)]}

    with caplog.at_level(logging.WARNING):
        response = queue(client)

    assert [entry["eventId"] for entry in response.get_json()["events"]] == [EVENT_B]
    assert EVENT_A in caplog.text


# --- Who may see it ---------------------------------------------------------------


def test_a_signed_in_officer_is_required(client, downstream):
    """SCRUM-8: without a token there is no officer to check."""
    response = client.application.test_client().get("/safety-checks/queue")

    assert response.status_code == 401
    assert downstream.calls == []


@pytest.mark.parametrize("role", ["Event Coordinator", "Venue Staff", "Event Organiser"])
def test_only_a_safety_officer_sees_the_queue(role, client, downstream):
    """The role is looked up in User Service, not trusted from the request."""
    downstream.user = user(role=role)

    response = queue(client)

    assert response.status_code == 403
    assert response.get_json()["code"] == "NOT_SAFETY_OFFICER"
    assert downstream.names() == ["get_user"]


def test_unknown_user_is_not_a_safety_officer(client, downstream):
    downstream.fail["get_user"] = clients.UserNotFoundError()

    response = queue(client)

    assert response.status_code == 403
    assert response.get_json()["code"] == "NOT_SAFETY_OFFICER"


# --- Failures: fail closed, never leak ----------------------------------------------


@pytest.mark.parametrize("name", ["list_events", "list_venues", "list_records", "bookings"])
@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamTimeout(), 504), (clients.DownstreamError(), 502)],
)
def test_any_unreadable_part_fails_the_whole_queue(name, error, status, client, downstream):
    """A partial list would silently hide an event the officer must review."""
    downstream.fail[name] = error

    response = queue(client)

    assert response.status_code == status
    assert response.get_json() == {
        "message": "Unable to load the safety check queue right now."
    }


def test_an_unexpected_downstream_shape_is_a_502(client, downstream):
    """A malformed reply (here, an event with no id) is a 502, not a 500."""
    downstream.events = [{"eventName": "No id"}]

    response = queue(client)

    assert response.status_code == 502


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamTimeout(), 504), (clients.DownstreamError(), 502)],
)
def test_role_lookup_failure(error, status, client, downstream):
    downstream.fail["get_user"] = error

    assert queue(client).status_code == status
