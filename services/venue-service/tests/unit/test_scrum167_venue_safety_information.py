"""
SCRUM-167: Record Venue Safety Information

User Story
----------
As a Venue Staff member, I want to record a venue's emergency access details
and known operational restrictions, so that the Safety Officer can take them
into account when reviewing events at that venue.

Acceptance Criteria
-------------------
AC1: Given authorised Venue Staff edit a venue, when they enter emergency
     access details (e.g. exits, assembly point, emergency vehicle access) and
     known restrictions (e.g. noise curfew, no open flames, floor load limit),
     then the details are saved with the venue and shown on its details page.
AC2: Given a venue has no safety information recorded, when it is viewed, then
     the fields show "Not provided" rather than appearing blank.
AC3: Given safety information is updated, when it is saved, then the editor and
     timestamp are recorded.
AC4: Given a user who is not Venue Staff, when they attempt to edit venue
     safety information through the UI or API, then the change is rejected and
     the existing values are unchanged.

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
- PUT /venues/<id>/safety-info: the Venue Staff role check, body and length
  validation, blank-to-NULL storage, the update that stamps the editor and the
  database clock only when something changed, and the Singapore-time
  serialisation run for real; GET /venues and GET /venues/<id> return the
  fields.
- Assertions are on the status, errors, the SQL and values sent, and the
  returned fields.

Doubled
-------
- psycopg2.connect: Stub / Mock (`setup` fixture) - the cursor returns canned
  Venue rows, an empty update (no change), or raises ForeignKeyViolation /
  OperationalError; SQL inspected; asserted not called for refused callers.

Not proven
----------
- That the details page shows "Not provided" (AC2, UI half) (-> frontend venue
  detail tests).
- That the Safety Officer's review shows these fields (-> safety-check- service
  unit tests for SCRUM-163).
- That the real User foreign key rejects unknown editors (->
  tests/integration/).
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock

import psycopg2
import psycopg2.errors
import pytest

from app import create_app
from tests.unit.factories import (
    signed_in,
    SAFETY_PAYLOAD,
    STAFF_ID,
    VALID_PAYLOAD,
    VENUE_ID,
    saved_row,
    staff_headers,
)

STAMPED_AT = datetime(2030, 1, 15, 2, 30, tzinfo=timezone.utc)
SAFETY_COLUMNS = (
    "emergency_access_details",
    "known_restrictions",
    "safety_info_updated_by",
    "safety_info_updated_at",
)


def safety_row(**overrides):
    return saved_row(**{
        "emergency_access_details": SAFETY_PAYLOAD["emergencyAccessDetails"],
        "known_restrictions": SAFETY_PAYLOAD["knownRestrictions"],
        "safety_info_updated_by": STAFF_ID,
        "safety_info_updated_at": STAMPED_AT,
        **overrides,
    })


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr("app.models.psycopg2.connect", connect)
    app = create_app({
        "TESTING": True,
        "DATABASE_URL": "unused-test-url",
        "FRONTEND_ORIGIN": "http://localhost:5174",
    })
    return signed_in(app.test_client(), role="Venue Staff"), cursor, connect


def put_safety(client, body=SAFETY_PAYLOAD, headers=None):
    return client.put(
        f"/venues/{VENUE_ID}/safety-info",
        json=body,
        headers=staff_headers() if headers is None else headers,
    )


# AC1 ----------------------------------------------------------------------


def test_ac1_save_safety_info_when_venue_staff_saves_and_returns_both_texts(setup):
    """
    Summary: Venue Staff can save emergency access details and known restrictions, and get them back.
    AC1: Given authorised Venue Staff edit a venue, when they enter emergency
        access details (e.g. exits, assembly point, emergency vehicle access)
        and known restrictions (e.g. noise curfew, no open flames, floor load
        limit), then the details are saved with the venue and shown on its
        details page.
    Double: Stub (cursor returns the updated row; update inspected)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchone.return_value = safety_row()

    # Act (When)
    response = put_safety(client, {
        "emergencyAccessDetails": f"  {SAFETY_PAYLOAD['emergencyAccessDetails']}  ",
        "knownRestrictions": f"\n{SAFETY_PAYLOAD['knownRestrictions']}\n",
    })

    # Assert (Then)
    assert response.status_code == 200
    _, params = cursor.execute.call_args_list[0].args
    assert params == {
        "venue_id": VENUE_ID,
        "editor": STAFF_ID,
        "emergency": SAFETY_PAYLOAD["emergencyAccessDetails"],
        "restrictions": SAFETY_PAYLOAD["knownRestrictions"],
    }
    venue = response.json["venue"]
    assert venue["emergencyAccessDetails"] == SAFETY_PAYLOAD["emergencyAccessDetails"]
    assert venue["knownRestrictions"] == SAFETY_PAYLOAD["knownRestrictions"]
    assert venue["safetyInfoUpdatedBy"] == STAFF_ID
    assert venue["safetyInfoUpdatedAt"] == "2030-01-15T10:30:00+08:00"


def test_ac1_get_venue_includes_safety_information(setup):
    """
    Summary: A venue's details include its recorded safety information.
    AC1: Given authorised Venue Staff edit a venue, when they enter emergency
        access details (e.g. exits, assembly point, emergency vehicle access)
        and known restrictions (e.g. noise curfew, no open flames, floor load
        limit), then the details are saved with the venue and shown on its
        details page.
    Double: Stub (cursor returns a row with both texts)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchone.return_value = safety_row()

    # Act (When)
    response = client.get(f"/venues/{VENUE_ID}")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["venue"]["emergencyAccessDetails"] == SAFETY_PAYLOAD["emergencyAccessDetails"]
    assert response.json["venue"]["knownRestrictions"] == SAFETY_PAYLOAD["knownRestrictions"]
    select_query = cursor.execute.call_args.args[0]
    assert all(column in select_query for column in SAFETY_COLUMNS)


def test_ac1_list_venues_includes_safety_information(setup):
    """
    Summary: The venue list carries safety information too, for the Safety Officer's review.
    AC1: Given authorised Venue Staff edit a venue, when they enter emergency
        access details (e.g. exits, assembly point, emergency vehicle access)
        and known restrictions (e.g. noise curfew, no open flames, floor load
        limit), then the details are saved with the venue and shown on its
        details page.
    Double: Stub (cursor returns a row with both texts)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchall.return_value = [safety_row()]

    # Act (When)
    response = client.get("/venues")

    # Assert (Then)
    assert response.status_code == 200
    venue = response.json["venues"][0]
    assert venue["emergencyAccessDetails"] == SAFETY_PAYLOAD["emergencyAccessDetails"]
    assert venue["knownRestrictions"] == SAFETY_PAYLOAD["knownRestrictions"]
    assert venue["safetyInfoUpdatedBy"] == STAFF_ID


def test_ac1_save_safety_info_with_2000_characters_is_accepted(setup):
    """
    Summary: Safety texts of up to 2000 characters are accepted.
    AC1: (boundary: length = 2000)
    Double: Stub (cursor returns the updated row)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchone.return_value = safety_row()

    # Act (When)
    response = put_safety(client, {"emergencyAccessDetails": "x" * 2000, "knownRestrictions": "y" * 2000})

    # Assert (Then)
    assert response.status_code == 200
    _, params = cursor.execute.call_args_list[0].args
    assert params["emergency"] == "x" * 2000
    assert params["restrictions"] == "y" * 2000


@pytest.mark.parametrize(
    ("key", "label"),
    [
        ("emergencyAccessDetails", "Emergency Access Details"),
        ("knownRestrictions", "Known Restrictions"),
    ],
    ids=["emergency_access", "known_restrictions"],
)
def test_ac1_save_safety_info_with_2001_characters_returns_400_before_database(key, label, setup):
    """
    Summary: A safety text one character over the limit is refused before anything is saved.
    AC1: (boundary: length = 2001)
    Double: Mock (cursor not executed)
    """
    # Arrange (Given)
    client, _, connect = setup

    # Act (When)
    response = put_safety(client, {**SAFETY_PAYLOAD, key: "x" * 2001})

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["errors"] == [f"{label} must be at most 2000 characters."]
    connect.assert_not_called()


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"knownRestrictions": "Noise curfew"}, "Emergency Access Details is required (send null to clear it)."),
        ({"emergencyAccessDetails": "Exits"}, "Known Restrictions is required (send null to clear it)."),
        ({**SAFETY_PAYLOAD, "emergencyAccessDetails": 123}, "Emergency Access Details must be text."),
        ({**SAFETY_PAYLOAD, "knownRestrictions": ["a"]}, "Known Restrictions must be text."),
        (["not", "an", "object"], "Send a JSON object."),
    ],
    ids=["missing-emergency", "missing-restrictions", "number", "list", "non-object"],
)
def test_ac1_save_safety_info_with_missing_or_non_text_field_returns_400(body, error, setup):
    """
    Summary: Both safety fields must be sent, as text or null.
    AC1: Given authorised Venue Staff edit a venue, when they enter emergency
        access details (e.g. exits, assembly point, emergency vehicle access)
        and known restrictions (e.g. noise curfew, no open flames, floor load
        limit), then the details are saved with the venue and shown on its
        details page.
    Double: Mock (cursor not executed)
    """
    # Arrange (Given)
    client, _, connect = setup

    # Act (When)
    response = put_safety(client, body)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "Please correct the safety information."
    assert error in response.json["errors"]
    connect.assert_not_called()


# AC2 ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "row",
    [
        saved_row(**{column: None for column in SAFETY_COLUMNS}),
        saved_row(),
    ],
    ids=["null-columns", "columns-absent"],
)
def test_ac2_get_venue_without_safety_info_returns_null_fields(row, setup):
    """
    Summary: A venue with nothing recorded returns null, never empty text, so the UI shows "Not provided".
    AC2: Given a venue has no safety information recorded, when it is viewed,
        then the fields show "Not provided" rather than appearing blank.
    Double: Stub (cursor returns null or absent safety columns)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchone.return_value = row

    # Act (When)
    venue = client.get(f"/venues/{VENUE_ID}").json["venue"]

    # Assert (Then)
    assert venue["emergencyAccessDetails"] is None
    assert venue["knownRestrictions"] is None
    assert venue["safetyInfoUpdatedBy"] is None
    assert venue["safetyInfoUpdatedAt"] is None


@pytest.mark.parametrize("blank", ["", "   ", None], ids=["empty", "whitespace", "null"])
def test_ac2_save_safety_info_with_blank_text_stores_null(blank, setup):
    """
    Summary: Clearing a safety field stores nothing rather than blank text.
    AC2: Given a venue has no safety information recorded, when it is viewed,
        then the fields show "Not provided" rather than appearing blank.
    Double: Stub (cursor returns the updated row; values inspected)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchone.return_value = saved_row()

    # Act (When)
    response = put_safety(client, {"emergencyAccessDetails": blank, "knownRestrictions": blank})

    # Assert (Then)
    assert response.status_code == 200
    _, params = cursor.execute.call_args_list[0].args
    assert params["emergency"] is None
    assert params["restrictions"] is None


# AC3 ----------------------------------------------------------------------


def test_ac3_save_safety_info_records_editor_and_database_time(setup):
    """
    Summary: Each save records who edited and the database's time.
    AC3: Given safety information is updated, when it is saved, then the editor
        and timestamp are recorded.
    Double: Stub (cursor returns the updated row; SQL inspected)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchone.return_value = safety_row()

    put_safety(client)

    query, params = cursor.execute.call_args_list[0].args

    # Act + Assert (When / Then)
    assert "safety_info_updated_by = %(editor)s" in query
    assert "safety_info_updated_at = now()" in query
    assert "IS DISTINCT FROM" in query
    assert params["editor"] == STAFF_ID


def test_ac3_save_safety_info_returns_timestamp_in_singapore_time(setup):
    """
    Summary: The edit time is shown in Singapore time.
    AC3: Given safety information is updated, when it is saved, then the editor
        and timestamp are recorded.
    Double: Stub (cursor returns a UTC timestamp)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchone.return_value = safety_row()

    # Act (When)
    venue = client.get(f"/venues/{VENUE_ID}").json["venue"]

    # Assert (Then)
    assert venue["safetyInfoUpdatedAt"] == "2030-01-15T10:30:00+08:00"


def test_ac3_save_safety_info_when_unchanged_keeps_previous_stamp(setup):
    """
    Summary: Saving the same values again does not change who edited or when.
    AC3: Given safety information is updated, when it is saved, then the editor
        and timestamp are recorded.
    Double: Stub (update changes no row; the venue is read back)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    other_staff = "0e6f7c55-1b2a-4d3e-8f90-123456789abc"
    cursor.fetchone.side_effect = [None, safety_row(safety_info_updated_by=other_staff)]

    # Act (When)
    response = put_safety(client)

    # Assert (Then)
    assert response.status_code == 200
    assert cursor.execute.call_count == 2
    assert cursor.execute.call_args_list[1].args[0].lstrip().startswith("SELECT")
    assert response.json["venue"]["safetyInfoUpdatedBy"] == other_staff
    assert response.json["venue"]["safetyInfoUpdatedAt"] == "2030-01-15T10:30:00+08:00"


# AC4 ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "role",
    [
        "Event Coordinator",
        "Event Coordinator Lead",
        "Safety Officer",
        "Event Organiser",
        "Technical Support Staff",
    ],
    ids=["event_coordinator", "event_coordinator_lead", "safety_officer", "event_organiser", "technical_support"],
)
def test_ac4_save_safety_info_when_not_venue_staff_returns_403_without_database(role, setup):
    """
    Summary: Nobody but Venue Staff can change safety information, and nothing is changed for them.
    AC4: Given a user who is not Venue Staff, when they attempt to edit venue
        safety information through the UI or API, then the change is rejected
        and the existing values are unchanged.
    Double: Mock (psycopg2.connect not called)
    """
    # Arrange (Given)
    client, _, connect = setup

    # Act (When)
    response = put_safety(client, headers=staff_headers(role=role))

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["code"] == "VENUE_STAFF_ONLY"
    connect.assert_not_called()


@pytest.mark.parametrize(
    ("headers", "message"),
    [
        ({}, "Sign in to continue."),
        ({"X-Dev-User-Id": STAFF_ID, "X-Dev-Role": "Venue Staff"}, "Sign in to continue."),
        ({"Authorization": "Bearer not-a-jwt"}, "Your session is invalid or has expired. Sign in again."),
    ],
    ids=["no-token", "dev-headers-only", "invalid-token"],
)
def test_scrum8_ac1_save_safety_info_without_valid_sign_in_returns_401_without_database(headers, message, setup):
    """
    Summary: A save without a valid sign-in never reaches the database.
    AC4: Given a user who is not Venue Staff, when they attempt to edit venue
        safety information through the UI or API, then the change is rejected
        and the existing values are unchanged.
    SCRUM-8 AC1: Given a system user has not been successfully authenticated,
        when they attempt to access protected information or functionality,
        then access is denied.
    Double: Mock (psycopg2.connect not called)
    """
    # Arrange (Given)
    _, _, connect = setup
    client = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"}).test_client()

    # Act (When)
    response = put_safety(client, headers=headers)

    # Assert (Then)
    assert response.status_code == 401
    assert response.json["message"] == message
    connect.assert_not_called()


def test_ac4_save_safety_info_when_editor_unknown_returns_403(setup):
    """
    Summary: An editor with no user record is refused rather than reported as an outage.
    AC4: Given a user who is not Venue Staff, when they attempt to edit venue
        safety information through the UI or API, then the change is rejected
        and the existing values are unchanged.
    Double: Stub (update raises ForeignKeyViolation)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.execute.side_effect = psycopg2.errors.ForeignKeyViolation("fk_venue_safety_editor")

    # Act (When)
    response = put_safety(client)

    # Assert (Then)
    assert response.status_code == 403
    assert response.json == {
        "code": "UNKNOWN_EDITOR",
        "message": "Your user account could not be found.",
    }


@pytest.mark.parametrize(
    ("method", "path", "fetches"),
    [
        ("put", f"/venues/{VENUE_ID}", [None, saved_row()]),
        ("post", "/venues", [None, saved_row()]),
    ],
    ids=["profile-edit", "profile-create"],
)
def test_ac4_profile_save_with_safety_fields_ignores_them(method, path, fetches, setup):
    """
    Summary: The general add and edit forms cannot change safety information.
    AC4: Given a user who is not Venue Staff, when they attempt to edit venue
        safety information through the UI or API, then the change is rejected
        and the existing values are unchanged.
    Double: Stub (cursor returns rows; SQL inspected)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchone.side_effect = fetches
    body = {
        **VALID_PAYLOAD,
        "emergencyAccessDetails": "Smuggled exits",
        "knownRestrictions": "Smuggled restrictions",
        "safetyInfoUpdatedBy": STAFF_ID,
    }

    # Act (When)
    response = getattr(client, method)(path, json=body)

    # Assert (Then)
    assert response.status_code in (200, 201)
    write_query, write_params = cursor.execute.call_args_list[-1].args
    written = write_query.split("RETURNING")[0]
    assert not any(column in written for column in SAFETY_COLUMNS)
    assert "Smuggled exits" not in write_params
    assert "Smuggled restrictions" not in write_params
    assert STAFF_ID not in write_params


# Other failures -----------------------------------------------------------


def test_ac1_save_safety_info_when_venue_unknown_returns_404(setup):
    """
    Summary: Saving safety information for a venue that does not exist is refused.
    AC1: Given authorised Venue Staff edit a venue, when they enter emergency
        access details (e.g. exits, assembly point, emergency vehicle access)
        and known restrictions (e.g. noise curfew, no open flames, floor load
        limit), then the details are saved with the venue and shown on its
        details page.
    Double: Stub (no row updated and none found)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchone.side_effect = [None, None]

    # Act (When)
    response = put_safety(client)

    # Assert (Then)
    assert response.status_code == 404
    assert response.json["message"] == "Venue not found."


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_support_save_safety_info_preflight_allows_authorization_header(setup):
    """
    Summary: The browser may send the sign-in token with a safety save.
    Supporting design check: CORS allows the Authorization header
    Double: None
    """
    client, _, _ = setup

    response = client.options(
        f"/venues/{VENUE_ID}/safety-info",
        headers={
            "Origin": "http://localhost:5174",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type, authorization",
        },
    )

    assert response.status_code == 200
    allowed = response.headers["Access-Control-Allow-Headers"]
    assert "Authorization" in allowed
    assert "X-Dev-Role" not in allowed
    assert "PUT" in response.headers["Access-Control-Allow-Methods"]


def test_support_save_safety_info_when_database_fails_returns_503_without_internals(setup, monkeypatch):
    """
    Summary: A database outage while saving gives a 503 without internals.
    Supporting design check: database errors answer 503 with a safe message
    Double: Stub (psycopg2.connect raises OperationalError)
    """
    client, _, _ = setup

    def explode(*args, **kwargs):
        raise psycopg2.OperationalError("connection refused to db.example")

    monkeypatch.setattr("app.models.psycopg2.connect", explode)

    response = put_safety(client)

    assert response.status_code == 503
    assert "db.example" not in response.get_data(as_text=True)


def test_support_save_safety_info_when_database_url_missing_returns_503():
    """
    Summary: Saving reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured Venue Service answers 503
    Double: None
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client(), role="Venue Staff")

    response = put_safety(client)

    assert response.status_code == 503
