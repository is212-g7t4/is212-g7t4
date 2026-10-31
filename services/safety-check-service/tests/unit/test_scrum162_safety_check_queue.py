"""
SCRUM-162: View Safety Check Queue

User Story
----------
As a Safety Officer, I want to view a list of events awaiting an Operational
Safety Check, so that I know which events I need to review.

Acceptance Criteria
-------------------
AC1: The queue shows only events with status 'Pending Safety Check'.
AC2: Each entry shows event name, event date/time, venue(s), expected
     attendance and submission date, with the nearest event date first.
AC3: Given an event was resubmitted after an earlier decision, then it is
     labelled as a resubmission.
AC4: Given a decision is recorded for an event, then it no longer appears in
     the queue.

Real
----
- The Safety Officer's queue: only events pending their safety check, each with
  its name, date and time, venues, expected attendance and submission date,
  nearest event first, resubmissions labelled, and decided events gone.
- We check the queue returned.

Doubled
-------
- Event, Safety Check Record, Venue Availability, Venue, Equipment Request and
  User Services: answer as each test needs, fail, or do not answer in time
  [Stub]; we check which were asked, in what order, and what they were sent
  [Mock].
- Sign-in: a test key signs the caller's token (tests/conftest.py) [Stub].

Not proven
----------
- The queue page in the browser (-> frontend SafetyChecksPage.test.tsx).
"""
import logging

import pytest
from flask import g

from app import clients, create_app
from tests.unit.factories import OFFICER_ID, booking, record, user, signed_in
from tests.unit.factories import Response, event

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


def test_queue_entry_shows_name_date_venues_attendance_and_submission(client, downstream):
    """
    Summary: Each entry shows what the officer needs to choose what to review.
    AC2: Each entry shows event name, event date/time, venue(s), expected
        attendance and submission date, with the nearest event date first.
    Double: Event Service lists the pending events, and the other services hold
        their rounds, bookings and venues [Stub].
    """
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


def test_queue_asks_only_for_pending_safety_check_events(client, downstream):
    """
    Summary: Only events awaiting a safety check are asked for.
    AC1: The queue shows only events with status 'Pending Safety Check'.
    Double: We check which events Event Service is asked for [Mock].
    """
    queue(client)

    assert ("list_events", "Pending Safety Check", OFFICER_ID, "Safety Officer") in (
        downstream.calls
    )


def test_queue_reads_open_round_for_each_event(client, downstream):
    """
    Summary: The submission date comes from each event's open round.
    AC2: Each entry shows event name, event date/time, venue(s), expected
        attendance and submission date, with the nearest event date first.
    Double: Event Service lists the pending events, and the other services hold
        their rounds, bookings and venues [Stub].
    """
    queue(client)

    assert ("list_records", EVENT_A, "Pending") in downstream.calls


def test_queue_with_nothing_pending_returns_empty_list(client, downstream):
    """
    Summary: Nothing pending gives an empty queue, not an error.
    AC1: The queue shows only events with status 'Pending Safety Check'.
    Double: Event Service lists the pending events, and the other services hold
        their rounds, bookings and venues [Stub].
    """
    downstream.events = []

    response = queue(client)

    assert response.status_code == 200
    assert response.get_json() == {"events": []}
    assert "list_records" not in downstream.names()


def test_queue_lists_nearest_event_first(client, downstream):
    """
    Summary: Events are listed nearest date first.
    AC2: Each entry shows event name, event date/time, venue(s), expected
        attendance and submission date, with the nearest event date first.
    Double: Event Service lists the pending events, and the other services hold
        their rounds, bookings and venues [Stub].
    """
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


def test_queue_ties_ordered_by_event_id(client, downstream):
    """
    Summary: Events at the same time keep a stable order.
    AC2: Each entry shows event name, event date/time, venue(s), expected
        attendance and submission date, with the nearest event date first.
    Double: Event Service lists the pending events, and the other services hold
        their rounds, bookings and venues [Stub].
    """
    downstream.events = [
        pending_event(EVENT_B, "2026-11-12T09:00:00"),
        pending_event(EVENT_A, "2026-11-12T09:00:00"),
    ]
    downstream.rounds = {
        event_id: [record(eventId=event_id)] for event_id in (EVENT_A, EVENT_B)
    }

    ids = [entry["eventId"] for entry in queue(client).get_json()["events"]]

    assert ids == [EVENT_A, EVENT_B]


def test_queue_lists_undated_event_last(client, downstream):
    """
    Summary: An event without a date goes last.
    AC2: Each entry shows event name, event date/time, venue(s), expected
        attendance and submission date, with the nearest event date first.
    Double: Event Service lists the pending events, and the other services hold
        their rounds, bookings and venues [Stub].
    """
    downstream.events = [
        pending_event(EVENT_B, ""),
        pending_event(EVENT_A, "2026-11-12T09:00:00"),
    ]
    downstream.rounds = {
        event_id: [record(eventId=event_id)] for event_id in (EVENT_A, EVENT_B)
    }

    ids = [entry["eventId"] for entry in queue(client).get_json()["events"]]

    assert ids == [EVENT_A, EVENT_B]


def test_queue_entry_with_missing_fields_shows_blanks(client, downstream):
    """
    Summary: An event with missing fields still appears, with blanks.
    AC2: Each entry shows event name, event date/time, venue(s), expected
        attendance and submission date, with the nearest event date first.
    Double: Event Service lists the pending events, and the other services hold
        their rounds, bookings and venues [Stub].
    """
    downstream.events = [{"id": EVENT_A, "status": "Pending Safety Check"}]

    entry = queue(client).get_json()["events"][0]

    assert entry["eventName"] == ""
    assert entry["preferredStartDate"] == ""
    assert entry["preferredEndDate"] == ""
    assert entry["expectedAttendance"] == ""


# --- AC2: venues ----------------------------------------------------------------


def test_queue_entry_lists_every_venue(client, downstream):
    """
    Summary: Every venue the event is booked into is listed.
    AC2: Each entry shows event name, event date/time, venue(s), expected
        attendance and submission date, with the nearest event date first.
    Double: Event Service lists the pending events, and the other services hold
        their rounds, bookings and venues [Stub].
    """
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


def test_queue_entry_lists_repeated_venue_once(client, downstream):
    """
    Summary: A venue booked twice is listed once.
    AC2: Each entry shows event name, event date/time, venue(s), expected
        attendance and submission date, with the nearest event date first.
    Double: Event Service lists the pending events, and the other services hold
        their rounds, bookings and venues [Stub].
    """
    downstream.bookings = {
        EVENT_A: [
            booking(eventId=EVENT_A, venueId=HALL, booking_id="b1"),
            booking(eventId=EVENT_A, venueId=HALL, booking_id="b2"),
        ]
    }

    venues = queue(client).get_json()["events"][0]["venues"]

    assert venues == [{"id": HALL, "name": "Main Hall"}]


@pytest.mark.parametrize("status", ["Cancelled", "Expired", "Rejected"])
def test_queue_entry_ignores_released_bookings(status, client, downstream):
    """
    Summary: Cancelled, expired or rejected bookings are not listed as venues.
    AC2: Each entry shows event name, event date/time, venue(s), expected
        attendance and submission date, with the nearest event date first.
    Double: Event Service lists the pending events, and the other services hold
        their rounds, bookings and venues [Stub].
    """
    downstream.bookings = {
        EVENT_A: [
            booking(eventId=EVENT_A, venueId=HALL, booking_id="b1"),
            booking(status=status, eventId=EVENT_A, venueId=ROOM, booking_id="b2"),
        ]
    }

    venues = queue(client).get_json()["events"][0]["venues"]

    assert venues == [{"id": HALL, "name": "Main Hall"}]


def test_queue_entry_shows_venue_missing_from_catalogue(client, downstream):
    """
    Summary: A booked venue missing from the catalogue is still shown.
    AC2: Each entry shows event name, event date/time, venue(s), expected
        attendance and submission date, with the nearest event date first.
    Double: Event Service lists the pending events, and the other services hold
        their rounds, bookings and venues [Stub].
    """
    downstream.venues = []

    venues = queue(client).get_json()["events"][0]["venues"]

    assert venues == [{"id": HALL, "name": "Unknown venue"}]


def test_queue_entry_without_live_booking_has_no_venues(client, downstream):
    """
    Summary: With no live booking, the venue list is empty.
    AC2: Each entry shows event name, event date/time, venue(s), expected
        attendance and submission date, with the nearest event date first.
    Double: Event Service lists the pending events, and the other services hold
        their rounds, bookings and venues [Stub].
    """
    downstream.bookings = {}

    assert queue(client).get_json()["events"][0]["venues"] == []


# --- AC3: resubmissions ---------------------------------------------------------


def test_queue_entry_for_first_round_is_not_resubmission(client, downstream):
    """
    Summary: A first submission is not labelled a resubmission.
    AC3: Given an event was resubmitted after an earlier decision, then it is
        labelled as a resubmission.
    Double: Event Service lists the pending events, and the other services hold
        their rounds, bookings and venues [Stub].
    """
    entry = queue(client).get_json()["events"][0]

    assert entry["roundNumber"] == 1
    assert entry["resubmission"] is False


@pytest.mark.parametrize("round_number", [2, 3])
def test_queue_entry_for_later_round_is_resubmission(round_number, client, downstream):
    """
    Summary: Any later round is labelled a resubmission.
    AC3: Given an event was resubmitted after an earlier decision, then it is
        labelled as a resubmission.
    Double: Event Service lists the pending events, and the other services hold
        their rounds, bookings and venues [Stub].
    """
    downstream.rounds = {EVENT_A: [record(round_number=round_number, eventId=EVENT_A)]}

    entry = queue(client).get_json()["events"][0]

    assert entry["roundNumber"] == round_number
    assert entry["resubmission"] is True


def test_queue_entry_for_resubmission_shows_latest_date(client, downstream):
    """
    Summary: A resubmission shows when it was resubmitted.
    AC3: Given an event was resubmitted after an earlier decision, then it is
        labelled as a resubmission.
    Double: Event Service lists the pending events, and the other services hold
        their rounds, bookings and venues [Stub].
    """
    downstream.rounds = {
        EVENT_A: [
            record(round_number=2, eventId=EVENT_A, submittedAt="2026-11-05T01:00:00+00:00")
        ]
    }

    entry = queue(client).get_json()["events"][0]

    assert entry["submittedAt"] == "2026-11-05T01:00:00+00:00"


# --- AC4: decided events drop out ------------------------------------------------


def test_queue_excludes_decided_event(client, downstream):
    """
    Summary: Once decided, an event leaves the queue.
    AC4: Given a decision is recorded for an event, then it no longer appears
        in the queue.
    Double: Event Service lists the pending events, and the other services hold
        their rounds, bookings and venues [Stub].
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


def test_queue_leaves_out_event_without_open_round_and_logs(client, downstream, caplog):
    """
    Summary: An event with no open round is left out and logged.
    AC4: Given a decision is recorded for an event, then it no longer appears
        in the queue.
    Double: Event Service lists the pending events, and the other services hold
        their rounds, bookings and venues [Stub].
    """
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


# --- Failures: fail closed, never leak ----------------------------------------------


@pytest.mark.parametrize("name", ["list_events", "list_venues", "list_records", "bookings"])
@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamTimeout(), 504), (clients.DownstreamError(), 502)],
    ids=["clients_downstreamtimeout_504", "clients_downstreamerror_502"],
)
def test_queue_with_any_unreadable_part_fails_whole(name, error, status, client, downstream):
    """
    Summary: If any part cannot be read, the whole queue fails rather than hiding an event.
    AC1: The queue shows only events with status 'Pending Safety Check'.
    Double: Event Service lists the pending events, and the other services hold
        their rounds, bookings and venues [Stub].
    """
    downstream.fail[name] = error

    response = queue(client)

    assert response.status_code == status
    assert response.get_json() == {
        "message": "Unable to load the safety check queue right now."
    }


def test_queue_with_malformed_downstream_answer_returns_502(client, downstream):
    """
    Summary: If another service sends back something unreadable, the queue reports a failure rather than guessing.
    AC1: The queue shows only events with status 'Pending Safety Check'.
    Double: Event Service lists the pending events, and the other services hold
        their rounds, bookings and venues [Stub].
    """
    downstream.events = [{"eventName": "No id"}]

    response = queue(client)

    assert response.status_code == 502


def test_list_events_client_reads_as_viewer_role(sent):
    """
    Summary: The queue's events are read in the Safety Officer's view.
    AC1: The queue shows only events with status 'Pending Safety Check'.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    calls, queue = sent
    queue.append(Response(200, {"events": [event("Pending Safety Check")]}))

    found = clients.list_events_by_status("Pending Safety Check", "Safety Officer")

    assert found[0]["status"] == "Pending Safety Check"
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith("/events")
    assert calls[0]["params"] == {
        "viewerRole": "Safety Officer",
        "status": "Pending Safety Check",
    }


@pytest.mark.parametrize("status", [400, 403, 503])
def test_list_events_client_failure_is_downstream_error(status, sent):
    """
    Summary: If the list of events cannot be read, it is reported as a failure of that service.
    AC1: The queue shows only events with status 'Pending Safety Check'.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    _, queue = sent
    queue.append(Response(status, {"message": "no"}))

    with pytest.raises(clients.DownstreamError):
        clients.list_events_by_status("Pending Safety Check", "Safety Officer")


def test_list_venues_client_reads_whole_catalogue(sent):
    """
    Summary: The whole venue catalogue is read.
    AC2: Each entry shows event name, event date/time, venue(s), expected
        attendance and submission date, with the nearest event date first.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    calls, queue = sent
    queue.append(Response(200, {"venues": [{"id": "v1", "name": "Main Hall"}]}))

    assert clients.list_venues() == [{"id": "v1", "name": "Main Hall"}]
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith("/venues")
    assert "params" not in calls[0]


def test_list_venues_client_failure_is_downstream_error(sent):
    """
    Summary: If the venues cannot be read, it is reported as a failure of that service.
    AC2: Each entry shows event name, event date/time, venue(s), expected
        attendance and submission date, with the nearest event date first.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    _, queue = sent
    queue.append(Response(503, {"message": "down"}))

    with pytest.raises(clients.DownstreamError):
        clients.list_venues()
