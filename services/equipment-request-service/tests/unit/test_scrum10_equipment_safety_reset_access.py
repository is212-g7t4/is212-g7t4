"""
SCRUM-10: Role-Based Modification Control for Events

User Story
----------
As a registered user, I want to modify only information appropriate to my role and relationship to an event, so that I can perform my responsibilities without changing information outside my permissions.

Acceptance Criteria
-------------------
AC1: Given an authenticated user is permitted to modify information based on their role and relationship to the event, when they make a valid change to that information, then the change is allowed.
AC2: Given an authenticated user's role does not permit them to modify particular information, when they attempt to change that information, then the modification is prevented and the existing information remains unchanged.
AC3: Given an authenticated user's relationship to an event does not permit them to modify that event's information, when they attempt to make a change, then the modification is prevented and the existing information remains unchanged.
AC4: Given a user is permitted to view particular information but is not permitted to modify it, when they attempt to change that information, then the modification is prevented while their permitted viewing access remains unaffected.
AC5: Given a user is permitted to modify information for one event but does not have the required access to another event, when they attempt to modify information for both events, then only modifications to information for which they have the required access are allowed.

Real
----
- POST /events/<id>/equipment-requests/safety-reset: token verification, the
  Safety Officer role check and the internal-token check run for real.
- Assertions are on the status and on the database not being touched.

Doubled
-------
- psycopg2.connect: Mock (`safety_role_setup`; cursor access is asserted absent) - a MagicMock connection.

Not proven
----------
- That a role-refused safety reset leaves stored requests unchanged in real PostgreSQL (NOT PROVEN here). Membership-refused preservation is separately covered by the reset integration module.
- Create/list role refusals are in test_scrum8_equipment_authentication.py; review refusal/read compatibility is in test_scrum33_equipment_request_review.py.
AC1 valid reset is exercised in tests/integration/test_scrum164_equipment_safety_reset.py; the local empty-body 400 is supporting reach-validation evidence only. AC3/AC5 relationship policy belongs to composite/event owners; no assignment check is claimed here.

- Scope: input-validation access smoke only; successful persisted change is covered by reset integration. Applies to: `test_safety_reset_when_safety_officer_with_service_token_reaches_validation`.
"""
from unittest.mock import MagicMock

import pytest

from app import create_app
from tests.unit.factories import bearer

EVENT = "00000000-0000-0000-0000-000000000001"
REQUEST_ID = "2a1bfb57-a3c0-4450-897e-cc5c73690000"
USER_ID = "e7334aa9-eb3a-4c45-84b5-280501b6c109"
TOKEN = "internal-test-token"
PATH = f"/events/{EVENT}/equipment-requests/safety-reset"


@pytest.fixture
def safety_role_setup(monkeypatch):
    connection = MagicMock()
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"DATABASE_URL": "postgresql://x", "INTERNAL_SERVICE_TOKEN": TOKEN})
    return app.test_client(), connection


# AC1 ----

def test_safety_reset_when_safety_officer_with_service_token_reaches_validation(safety_role_setup):
    """Summary: A Safety Officer with the service token reaches input validation, not a successful modification.
    AC1: Given an authenticated user is permitted to modify information based on their role and relationship to the event, when they make a valid change to that information, then the change is allowed.
    Double: Stub (installed database adapter; may remain unused on validation refusals); Stub (test JWKS public key for user-token verification)
    """
    # Arrange (Given)
    client, _ = safety_role_setup

    # Act (When)
    response = client.post(PATH, json={}, headers={**bearer(USER_ID, "Safety Officer"), "X-Internal-Token": TOKEN})

    # Assert (Then)
    assert response.status_code == 400


# AC2 ----

@pytest.mark.parametrize(
    "role", ["Event Coordinator", "Event Coordinator Lead", "Technical Support", "Venue Staff", "Event Organiser", "Attendee"],
    ids=["event_coordinator", "event_coordinator_lead", "technical_support", "venue_staff", "event_organiser", "attendee"],
)
def test_safety_reset_when_not_safety_officer_returns_403_even_with_service_token(safety_role_setup, role):
    """Summary: The service token proves the route, not the person: any other role is refused.
    AC2: Given an authenticated user's role does not permit them to modify particular information, when they attempt to change that information, then the modification is prevented and the existing information remains unchanged.
    Double: Stub (canned database results/errors); Mock (database interactions inspected); Stub (test JWKS public key for user-token verification)
    """
    # Arrange (Given)
    client, connection = safety_role_setup

    # Act (When)
    response = client.post(
        PATH, json={"requestIds": [REQUEST_ID]},
        headers={**bearer(USER_ID, role), "X-Internal-Token": TOKEN},
    )

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["message"] == "Your role cannot change this information."
    connection.cursor.assert_not_called()


import psycopg2


from tests.unit.factories import EVENT_ID, MIC, REQUEST_ID, TABLE, USER_ID, bearer, db_row, item

TS = bearer(USER_ID, "Technical Support")

COORDINATOR = bearer(USER_ID, "Event Coordinator")

SAFETY_OFFICER = bearer(USER_ID, "Safety Officer")



@pytest.mark.parametrize("token,headers,code", [
    (None, SAFETY_OFFICER, 503), ("test-internal-token", SAFETY_OFFICER, 403),
    ("test-internal-token", TS, 403),
], ids=["token_not_configured", "officer_without_service_token", "technical_support"])
def test_safety_reset_without_internal_service_credentials_is_refused(setup, token, headers, code):
    """Summary: Only Safety Check Service, acting for a Safety Officer, can reset equipment requests.
    AC2: Given an authenticated user's role does not permit them to modify particular information, when they attempt to change that information, then the modification is prevented and the existing information remains unchanged.
    Double: Stub (canned database results/errors); Mock (database interactions inspected); Stub (test JWKS public key for user-token verification); Fake (CompositeClient adds synthetic service context to JSON writes; no HTTP service runs)
    """
    # Arrange (Given)
    client, _, connect = setup
    client.application.config["INTERNAL_SERVICE_TOKEN"] = token

    # Act + Assert (When / Then)
    assert client.post(f"/events/{EVENT_ID}/equipment-requests/safety-reset",
        headers=headers, json={"requestIds": [REQUEST_ID]}).status_code == code
    connect.assert_not_called()
