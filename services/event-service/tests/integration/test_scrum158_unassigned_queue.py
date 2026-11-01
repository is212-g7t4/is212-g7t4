"""
SCRUM-158: View Unassigned Event Queue

User Story
----------
As an Event Coordinator Lead, I want to view a queue of submitted event
requests that have not yet been assigned, so that I can see which requests need
a coordinator.

Acceptance Criteria
-------------------
AC1: Queue shows only submitted events with no assigned coordinator
AC2: Each entry shows: event name, organiser name, proposed date/time, expected
     attendance, submission date
AC3: An event leaves the queue once a coordinator is assigned
AC4: Event Coordinators and other roles cannot access the queue

Real
----
- GET /events/unassigned and PATCH /events/<id> (the Lead's assignment): the
  routes, the role check from the signed token, app/models.py SQL and the
  assignment's status change, against postgres:17.6 with the full migration
  chain.
- Assertions are on the HTTP status, the response body and the stored rows.

Doubled
-------
- Supabase JWKS: Stub (tests/conftest.py) - tokens are signed with a throwaway
  ES256 key.
- Nothing else: Event Service makes no outbound calls.

Not proven
----------
- That the "organiser name" shown on the page is resolved from organiserId
  (-> frontend UnassignedQueuePage.test.tsx; this service returns organiserId).
- That Coordinator Assignment Service's GET /queue calls this endpoint and
  passes it through (-> coordinator-assignment-service unit and integration
  tests).
"""

from datetime import datetime

import pytest

from tests.unit.factories import signed_in
from tests.integration.factories import (
    COORDINATOR_ID,
    LEAD_ID,
    ORGANISER_ID,
    SINGAPORE,
    make_event,
    make_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

LEAD = "Event Coordinator Lead"


@pytest.fixture(autouse=True)
def users(db):
    make_user(db, ORGANISER_ID)
    make_user(db, COORDINATOR_ID, "Event Coordinator")
    make_user(db, LEAD_ID, LEAD)


def queue(client):
    signed_in(client, LEAD_ID, LEAD)
    response = client.get("/events/unassigned")
    assert response.status_code == 200
    return response.get_json()["events"]


# AC1 ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [
        "Draft",
        "Under Review",
        "Clarification Requested",
        "Amendment Requested",
        "Approved",
        "Rejected",
        "Pending Safety Check",
        "Confirmed",
        "Safety Changes Requested",
        "Cancelled",
    ],
)
def test_ac1_event_in_any_other_status_is_not_listed(client, db, status):
    """Normal: of one Submitted event with no coordinator and one event in another status, only the Submitted one is returned."""
    queued_id = make_event(db, status="Submitted", event_name="Queued Fair")
    make_event(db, status=status, event_name="Other Fair")

    assert [event["id"] for event in queue(client)] == [queued_id]


def test_ac1_submitted_event_with_a_coordinator_is_not_listed(client, db):
    """Boundary: Submitted alone is not enough; a coordinator on the row takes it out of the queue."""
    queued_id = make_event(db, status="Submitted", event_name="Queued Fair")
    make_event(db, status="Submitted", event_name="Assigned Fair", coordinator_id=COORDINATOR_ID)

    assert [event["id"] for event in queue(client)] == [queued_id]


def test_ac1_queue_is_empty_when_every_request_is_assigned(client, db):
    """Boundary: nothing to assign returns an empty list, not an error."""
    make_event(db, status="Under Review", coordinator_id=COORDINATOR_ID)

    assert queue(client) == []


# AC2 ---------------------------------------------------------------------


def test_ac2_entry_shows_name_organiser_date_time_attendance_and_submission_date(client, db):
    """Normal: the stored name, organiser, start and end times, expected attendance and submission date come back."""
    event_id = make_event(
        db,
        status="Submitted",
        event_name="Community Workshop",
        start=datetime(2030, 3, 1, 9, tzinfo=SINGAPORE),
        end=datetime(2030, 3, 1, 17, tzinfo=SINGAPORE),
        expected_attendance=40,
        submitted=datetime(2030, 2, 1, 10, tzinfo=SINGAPORE),
    )

    (event,) = queue(client)

    assert event["id"] == event_id
    assert event["eventName"] == "Community Workshop"
    assert event["organiserId"] == ORGANISER_ID
    assert event["preferredStartDate"].startswith("2030-03-01T09:00")
    assert event["preferredEndDate"].startswith("2030-03-01T17:00")
    assert event["expectedAttendance"] == "40"
    assert event["submittedAt"].startswith("2030-02-01T02:00")
    assert event["coordinatorId"] is None


def test_ac2_oldest_submission_is_listed_first(client, db):
    """Normal: the queue is ordered by submission date, oldest first, whatever order the rows were created in."""
    newest = make_event(db, status="Submitted", submitted=datetime(2030, 1, 9, 9, tzinfo=SINGAPORE))
    oldest = make_event(db, status="Submitted", submitted=datetime(2030, 1, 5, 9, tzinfo=SINGAPORE))
    middle = make_event(db, status="Submitted", submitted=datetime(2030, 1, 7, 9, tzinfo=SINGAPORE))

    assert [event["id"] for event in queue(client)] == [oldest, middle, newest]


def test_ac2_events_submitted_at_the_same_time_are_listed_in_a_stable_order(client, db):
    """Boundary: equal submission dates fall back to event id, so the order never changes between refreshes."""
    submitted = datetime(2030, 1, 5, 9, tzinfo=SINGAPORE)
    ids = [make_event(db, status="Submitted", submitted=submitted) for _ in range(3)]

    assert [event["id"] for event in queue(client)] == sorted(ids)
    assert [event["id"] for event in queue(client)] == sorted(ids)


# AC3 ---------------------------------------------------------------------


def test_ac3_event_leaves_the_queue_once_the_lead_assigns_a_coordinator(client, db):
    """Normal: the Lead's assignment moves the event to Under Review with that coordinator, and it drops out of the queue."""
    assigned_id = make_event(db, status="Submitted", event_name="Assigned Fair")
    waiting_id = make_event(
        db, status="Submitted", event_name="Waiting Fair", submitted=datetime(2030, 1, 6, 9, tzinfo=SINGAPORE)
    )
    assert [event["id"] for event in queue(client)] == [assigned_id, waiting_id]

    response = signed_in(client, LEAD_ID, LEAD).patch(
        f"/events/{assigned_id}", json={"assignedCoordinatorId": COORDINATOR_ID}
    )

    assert response.status_code == 200
    stored = db.event(assigned_id)
    assert stored["status"] == "Under Review"
    assert str(stored["coordinator_id"]) == COORDINATOR_ID
    assert [event["id"] for event in queue(client)] == [waiting_id]


def test_ac3_reassigning_an_assigned_event_does_not_bring_it_back_to_the_queue(client, db):
    """Boundary: moving an Under Review event to another coordinator leaves it out of the queue."""
    other_coordinator_id = "55555555-5555-4555-8555-555555555555"
    make_user(db, other_coordinator_id, "Event Coordinator")
    event_id = make_event(db, status="Under Review", coordinator_id=COORDINATOR_ID)

    response = signed_in(client, LEAD_ID, LEAD).patch(
        f"/events/{event_id}", json={"assignedCoordinatorId": other_coordinator_id}
    )

    assert response.status_code == 200
    assert queue(client) == []


# AC4 ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "role",
    ["Event Coordinator", "Event Organiser", "Attendee", "Venue Staff", "Technical Support", "Safety Officer"],
    ids=["event_coordinator", "event_organiser", "attendee", "venue_staff", "technical_support", "safety_officer"],
)
def test_ac4_role_other_than_the_lead_is_refused(client, db, role):
    """Failure: any other role gets 403 and no event data, even with a request waiting in the queue."""
    make_event(db, status="Submitted", event_name="Queued Fair")

    response = signed_in(client, COORDINATOR_ID, role).get("/events/unassigned")

    assert response.status_code == 403
    assert "events" not in response.get_json()


def test_ac4_request_without_a_token_is_refused(client, db):
    """Failure: no sign-in means 401 and no event data."""
    make_event(db, status="Submitted", event_name="Queued Fair")
    unsigned = client.application.test_client()

    response = unsigned.get("/events/unassigned")

    assert response.status_code == 401
    assert "events" not in response.get_json()
