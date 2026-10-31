"""
SCRUM-40: View Event Info as Event Coord

User Story
----------
As an Event Coordinator, I want to view registration information for events I
manage, so that I can track attendance numbers and plan logistics.

Acceptance Criteria
-------------------
AC1: The Event Coordinator can view a list of events they are assigned to
     manage.
AC2: For each managed event, the Event Coordinator can see the total number of
     registrations.
AC3: The Event Coordinator can click on an event to view detailed registration
     information including list of registered Attendees with name, email,
     organisation (if provided), registration date, registration status
     (Confirmed, Withdrawn), total registration count, event capacity (if set),
     remaining available spots (capacity - confirmed registrations)
AC4: Given the Event Coordinator is not assigned to an event, they cannot view
     registration information for that event.

SCRUM-41: View Event Info as Event Organizer

User Story
----------
As an Event Organiser, I want to view registration information for my events,
so that I can see who is attending.

Acceptance Criteria
-------------------
AC1: The Event Organiser can view a list of events that they have created.
AC2: For each approved event, the Event Organiser can see the total number of
     registrations.
AC3: The Event Organiser can click on an event to view detailed registration
     information including list of registered Attendees with name, email,
     organisation (if provided), registration date, registration status
     (Confirmed, Withdrawn), total registration count
AC4: Given the Event Organiser did not create the event, they cannot view
     registration information for that event.

Real
----
- GET /registrations?eventId= (the event's registration rows) and GET
  /registrations/counts?eventIds= (total and confirmed per event) run for real,
  including id validation and date serialisation.
- Assertions are on the rows and counts returned and the SQL parameters.

Doubled
-------
- psycopg2.connect: Stub / Mock (tests/unit/conftest.py `setup`) - the cursor
  returns canned Registration rows (or raises); executed SQL and parameters are
  inspected; the model functions are replaced by a Stub where a route test only
  needs their result or error.

Not proven
----------
- That only the assigned coordinator or creating organiser can see an event's
  list (SCRUM-40 AC4, SCRUM-41 AC4): an atomic cannot ask Event Service, so
  Attendee Registration Service checks the relationship (->
  attendee-registration-service test_scrum9_event_registrations_access.py).
- Attendee name, email and organisation (AC3): joined in by Attendee
  Registration Service (-> its unit tests).
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import psycopg2.errors
import pytest

from app import create_app
from app.models import (
    CapacityReachedError,
    DuplicateRegistrationError,
    RegistrationAlreadyWithdrawnError,
    RegistrationNotFoundError,
    RegistrationOwnershipError,
    create_registration,
    withdraw_registration,
)
from tests.unit.factories import ATTENDEE_ID, EVENT_ID, registration_payload, registration_row, signed_in

OTHER_EVENT_ID = "11111111-1111-4111-8111-111111111111"


def test_list_event_registrations_returns_every_row_with_status(setup):
    """
    Summary: The event team sees every registration of an event, confirmed and withdrawn.
    AC3: The Event Coordinator can click on an event to view detailed
        registration information including list of registered Attendees with
        name, email, organisation (if provided), registration date,
        registration status (Confirmed, Withdrawn), total registration count,
        event capacity (if set), remaining available spots (capacity -
        confirmed registrations)
    SCRUM-41 AC3: The Event Organiser can click on an event to view detailed
        registration information including list of registered Attendees with
        name, email, organisation (if provided), registration date,
        registration status (Confirmed, Withdrawn), total registration count
    Double: Stub (cursor returns a Confirmed and a Withdrawn row)
    """
    client, _, cursor = setup
    signed_in(client, role="Event Coordinator")
    cursor.fetchall.return_value = [
        registration_row(),
        registration_row(registration_id="1eec36d7-3c51-4981-8f80-ae62f7f99b7f", status="Withdrawn"),
    ]

    response = client.get(f"/registrations?eventId={EVENT_ID}")

    assert response.status_code == 200
    assert len(response.json["registrations"]) == 2
    assert response.json["registrations"][0]["status"] == "Confirmed"
    assert response.json["registrations"][1]["status"] == "Withdrawn"
    query, params = cursor.execute.call_args.args
    assert "WHERE event_id = %s" in query
    assert params == [EVENT_ID]


def test_list_event_registrations_when_none_returns_empty_list(setup):
    """
    Summary: An event with no registrations shows an empty list.
    AC3: The Event Coordinator can click on an event to view detailed
        registration information including list of registered Attendees with
        name, email, organisation (if provided), registration date,
        registration status (Confirmed, Withdrawn), total registration count,
        event capacity (if set), remaining available spots (capacity -
        confirmed registrations)
    Double: Stub (cursor returns no rows)
    """
    client, _, cursor = setup
    signed_in(client, role="Event Coordinator")
    cursor.fetchall.return_value = []

    response = client.get(f"/registrations?eventId={EVENT_ID}")

    assert response.status_code == 200
    assert response.json == {"registrations": []}


def test_list_event_registrations_returns_registration_date_as_iso_text(setup):
    """
    Summary: Each registration's date is shown in a standard date-time format.
    AC3: The Event Coordinator can click on an event to view detailed
        registration information including list of registered Attendees with
        name, email, organisation (if provided), registration date,
        registration status (Confirmed, Withdrawn), total registration count,
        event capacity (if set), remaining available spots (capacity -
        confirmed registrations)
    Double: Stub (cursor returns a row with a timezone-aware date)
    """
    client, _, cursor = setup
    signed_in(client, role="Event Coordinator")
    cursor.fetchall.return_value = [registration_row()]

    response = client.get(f"/registrations?eventId={EVENT_ID}")

    assert response.json["registrations"][0]["registration_date"] == "2026-09-13T01:15:00+00:00"


def test_list_event_registrations_returns_no_profile_details(setup):
    """
    Summary: Registration rows carry only the attendee id; names and emails are added by the composite.
    AC3: The Event Coordinator can click on an event to view detailed
        registration information including list of registered Attendees with
        name, email, organisation (if provided), registration date,
        registration status (Confirmed, Withdrawn), total registration count,
        event capacity (if set), remaining available spots (capacity -
        confirmed registrations)
    Double: Stub (cursor returns a row)
    """
    client, _, cursor = setup
    signed_in(client, role="Event Coordinator")
    cursor.fetchall.return_value = [registration_row(attendee_id=ATTENDEE_ID)]

    response = client.get(f"/registrations?eventId={EVENT_ID}")

    assert set(response.json["registrations"][0]) == {
            "registration_id", "event_id", "attendee_id", "registration_date", "status", "withdrawn_at",
    }
    query = cursor.execute.call_args.args[0]
    assert "attendee_email" not in query


def test_list_event_registrations_with_missing_date_returns_null(setup):
    """
    Summary: A registration with no recorded date is shown as having none rather than failing.
    AC3: The Event Coordinator can click on an event to view detailed
        registration information including list of registered Attendees with
        name, email, organisation (if provided), registration date,
        registration status (Confirmed, Withdrawn), total registration count,
        event capacity (if set), remaining available spots (capacity -
        confirmed registrations)
    Double: Stub (cursor returns a row without a date)
    """
    client, _, cursor = setup
    signed_in(client, role="Event Coordinator")
    cursor.fetchall.return_value = [registration_row(registration_date=None)]

    response = client.get(f"/registrations?eventId={EVENT_ID}")

    assert response.json["registrations"][0]["registration_date"] is None


@pytest.mark.parametrize("query_string", ["?eventId=", "?eventId=not-a-uuid"], ids=["blank", "not_a_uuid"])
def test_list_event_registrations_with_blank_or_bad_event_id_returns_400(query_string, setup):
    """
    Summary: Listing an event's registrations needs a valid event id.
    AC3: The Event Coordinator can click on an event to view detailed
        registration information including list of registered Attendees with
        name, email, organisation (if provided), registration date,
        registration status (Confirmed, Withdrawn), total registration count,
        event capacity (if set), remaining available spots (capacity -
        confirmed registrations)
    Double: Stub (cursor; not executed)
    """
    client, _, cursor = setup
    signed_in(client, role="Event Coordinator")
    response = client.get(f"/registrations{query_string}")
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_registration_counts_return_total_and_confirmed_with_zero_for_empty(setup):
    """
    Summary: Each event's total and confirmed registrations are counted, with zero for events nobody registered for.
    AC2: For each managed event, the Event Coordinator can see the total number
        of registrations.
    SCRUM-41 AC2: For each approved event, the Event Organiser can see the
        total number of registrations.
    Double: Stub (cursor returns counts for one of two events)
    """
    client, _, cursor = setup
    cursor.fetchall.return_value = [{"event_id": EVENT_ID, "total": 5, "confirmed": 3}]

    response = client.get(f"/registrations/counts?eventIds={EVENT_ID},{OTHER_EVENT_ID},{EVENT_ID}")

    assert response.status_code == 200
    assert response.json["counts"] == {
        EVENT_ID: {"total": 5, "confirmed": 3},
        OTHER_EVENT_ID: {"total": 0, "confirmed": 0},
    }
    assert cursor.execute.call_args.args[1] == [[EVENT_ID, OTHER_EVENT_ID]]


@pytest.mark.parametrize("value", ["", "nope", f"{EVENT_ID},nope"], ids=["empty", "not_a_uuid", "one_bad_in_list"])
def test_registration_counts_with_missing_or_bad_event_ids_return_400(setup, value):
    """
    Summary: Counts need a list of valid event ids.
    AC2: For each managed event, the Event Coordinator can see the total number
        of registrations.
    Double: Stub (cursor; not executed)
    """
    client, _, cursor = setup
    assert client.get(f"/registrations/counts?eventIds={value}").status_code == 400
    cursor.execute.assert_not_called()


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_list_registrations_with_internal_token_and_no_event_returns_400(setup, monkeypatch):
    """
    Summary: A background worker must say which event's registrations it wants.
    Supporting design check: the dispatcher reads registrations one event at a
        time
    Double: None
    """
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "internal-test-token")
    client, _, cursor = setup
    unsigned = client.application.test_client()
    response = unsigned.get("/registrations", headers={"X-Internal-Token": "internal-test-token"})
    assert response.status_code == 400
    cursor.execute.assert_not_called()
