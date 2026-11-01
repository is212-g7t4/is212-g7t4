"""SCRUM-161 View Coordinator Assignments and Active Events: Event Service integration tests.

Story:      As an Event Coordinator Lead, I want to view all coordinator assignments and
            active events under my supervision, so that I can balance workload and decide
            when to reassign
Real:       Flask app, GET /events/active, app/models.py SQL, postgres:17.6 with the full
            migration chain.
Doubled:    nothing (Event Service makes no outbound calls).
Not proven: Supabase sign-in itself (the caller is a token signed with a test key, SCRUM-8);
            the grouping by coordinator, the read-only view and the Lead-only access, which
            belong to GET /workload (-> coordinator-assignment-service
            tests/unit/test_scrum161_coordinator_workload.py).

Only the acceptance criteria that /events/active itself decides are covered here.

AC2  Each event shows: name, organiser, date/time, current status
AC3  Unassigned events are visible and clearly marked as unassigned
AC4  Confirmed, cancelled and rejected events are excluded
"""

from datetime import datetime

import pytest

from tests.unit.factories import signed_in
from tests.integration.factories import COORDINATOR_ID, LEAD_ID, ORGANISER_ID, SINGAPORE, make_event, make_user

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

LEAD = "Event Coordinator Lead"
ACTIVE_STATUSES = ["Submitted", "Under Review", "Approved", "Pending Safety Check"]
CLOSED_STATUSES = ["Confirmed", "Rejected", "Cancelled"]


@pytest.fixture(autouse=True)
def users(db):
    make_user(db, ORGANISER_ID)
    make_user(db, COORDINATOR_ID, "Event Coordinator")


def active_events(client):
    signed_in(client, LEAD_ID, LEAD)
    response = client.get("/events/active")
    assert response.status_code == 200
    return response.get_json()["events"]


# AC2 ---------------------------------------------------------------------


def test_ac2_event_shows_name_organiser_date_time_and_status(client, db):
    """Normal: the stored name, organiser, start and end times and status come back."""
    event_id = make_event(
        db,
        status="Under Review",
        event_name="Community Workshop",
        coordinator_id=COORDINATOR_ID,
        start=datetime(2030, 3, 1, 9, tzinfo=SINGAPORE),
        end=datetime(2030, 3, 1, 17, tzinfo=SINGAPORE),
    )

    (event,) = active_events(client)

    assert event["id"] == event_id
    assert event["eventName"] == "Community Workshop"
    assert event["organiserId"] == ORGANISER_ID
    assert event["preferredStartDate"].startswith("2030-03-01T09:00")
    assert event["preferredEndDate"].startswith("2030-03-01T17:00")
    assert event["status"] == "Under Review"


# AC3 ---------------------------------------------------------------------


def test_ac3_unassigned_event_is_listed_with_no_coordinator_beside_assigned_ones(client, db):
    """Normal: an event nobody is assigned to is returned with coordinatorId null."""
    unassigned_id = make_event(db, status="Submitted", event_name="Unassigned Fair")
    assigned_id = make_event(db, status="Approved", event_name="Assigned Fair", coordinator_id=COORDINATOR_ID)

    events = {event["id"]: event for event in active_events(client)}

    assert set(events) == {unassigned_id, assigned_id}
    assert events[unassigned_id]["coordinatorId"] is None
    assert events[assigned_id]["coordinatorId"] == COORDINATOR_ID


# AC4 ---------------------------------------------------------------------


def test_ac4_confirmed_rejected_and_cancelled_events_are_excluded(client, db):
    """Normal: of one event per status, only the active ones come back."""
    active_ids = {make_event(db, status=status, event_name=f"{status} Fair") for status in ACTIVE_STATUSES}
    for status in CLOSED_STATUSES:
        make_event(db, status=status, event_name=f"{status} Fair", coordinator_id=COORDINATOR_ID)

    events = active_events(client)

    assert {event["id"] for event in events} == active_ids
    assert not {event["status"] for event in events} & set(CLOSED_STATUSES)


@pytest.mark.parametrize("status", CLOSED_STATUSES)
def test_ac4_an_unassigned_closed_event_is_also_excluded(client, db, status):
    """Boundary: being unassigned does not bring a closed event back into the list."""
    make_event(db, status=status, event_name="Closed Fair")

    assert active_events(client) == []
