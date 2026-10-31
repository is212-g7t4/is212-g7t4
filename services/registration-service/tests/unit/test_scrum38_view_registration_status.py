"""
SCRUM-38: View Registration Status

User Story
----------
As an Attendee, I want to view my registration status for an event, so that I
can confirm my place is secured.

Acceptance Criteria
-------------------
AC1: The Attendee can view a list of events they have registered for.
AC2: For each registered event, the Attendee can see, Event name, date and
     time, venue, registration status (e.g., Confirmed, Withdrawn, Pending),
     registration date
AC3: The Attendee can click on a registered event to view detailed registration
     information including all registration details they submitted (name,
     email, organisation), event details (date, time, venue, description)
AC4: Given the Attendee has not registered for any events, the system displays
     a message stating so

SCRUM-8: User Authentication and Authorization

User Story
----------
As a system user, I want to securely access the system, so that I can use the
information and functionality available to me.

Acceptance Criteria
-------------------
AC1: Given a system user has not been successfully authenticated, when they
     attempt to access protected information or functionality, then access is
     denied.
AC2: Given a system user successfully authenticates, when they access protected
     information or functionality, then their access is evaluated according to
     their role and relationship to the relevant event.
AC3: Given a system user's authentication attempt is unsuccessful, when the
     authentication attempt is completed, then they remain unable to access
     protected information or functionality.

Real
----
- GET /registrations for an Attendee: the token-scoped query that returns only
  the caller's own registrations runs for real.
- Assertions are on the rows returned and the attendee id sent to the database.

Doubled
-------
- psycopg2.connect: Stub / Mock (tests/unit/conftest.py `setup`) - the cursor
  returns canned Registration rows (or raises); executed SQL and parameters are
  inspected; the model functions are replaced by a Stub where a route test only
  needs their result or error.

Not proven
----------
- AC1's attendee list plus event name, date, time, venue and the "no
  registrations" message (AC2-AC4) are joined in and shown by Attendee
  Registration Service and the UI (->
  attendee-registration-service unit tests and frontend
  AttendeeRegistrationsPage.test.tsx).
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


def test_scrum8_ac2_list_registrations_when_attendee_returns_only_their_own(setup):
    """
    Summary: An attendee sees the list of their own registrations and nobody else's.
    AC1: The Attendee can view a list of events they have registered for.
    SCRUM-8 AC2: Given a system user successfully authenticates, when they
        access protected information or functionality, then their access is
        evaluated according to their role and relationship to the relevant
        event.
    Double: Stub (cursor returns one row; query parameters inspected)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchall.return_value = [registration_row(attendee_id=ATTENDEE_ID)]

    # Act (When)
    response = client.get("/registrations")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["registrations"][0]["attendee_id"] == ATTENDEE_ID
    query, params = cursor.execute.call_args.args
    assert "WHERE attendee_id = %s" in query
    assert "ORDER BY registration_date DESC" in query
    assert params == [ATTENDEE_ID]


def test_ac4_list_registrations_when_attendee_has_none_returns_empty_list(setup):
    """
    Summary: An attendee with no registrations gets an empty list.
    AC4: Given the Attendee has not registered for any events, the system
        displays a message stating so
    Double: Stub (cursor returns no rows)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchall.return_value = []

    # Act (When)
    response = client.get("/registrations")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json == {"registrations": []}


def test_scrum8_ac2_list_registrations_with_forged_attendee_id_uses_token_user(setup):
    """
    Summary: An attendee id in the query is ignored; the list is always the caller's own.
    AC1: The Attendee can view a list of events they have registered for.
    SCRUM-8 AC2: Given a system user successfully authenticates, when they
        access protected information or functionality, then their access is
        evaluated according to their role and relationship to the relevant
        event.
    Double: Stub (cursor returns no rows; query parameters inspected)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchall.return_value = []

    # Act (When)
    response = client.get("/registrations?attendeeId=11111111-1111-4111-8111-111111111111")

    # Assert (Then)
    assert response.status_code == 200
    assert cursor.execute.call_args.args[1] == [ATTENDEE_ID]
