"""SCRUM-167 Record Venue Safety Information: Venue Service.

As a Venue Staff member, I want to record a venue's emergency access details
and known operational restrictions, so that the Safety Officer can take them
into account when reviewing events at that venue.

Covers PUT /venues/<id>/safety-info (role check, validation, stamp), the four
safety fields on GET /venues and GET /venues/<id>, and that the profile routes
cannot be used to write them.
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


def test_ac1_safety_details_are_saved_and_returned(setup):
    """Normal: Venue Staff save both texts; they are written and echoed back."""
    client, cursor, _ = setup
    cursor.fetchone.return_value = safety_row()

    response = put_safety(client, {
        "emergencyAccessDetails": f"  {SAFETY_PAYLOAD['emergencyAccessDetails']}  ",
        "knownRestrictions": f"\n{SAFETY_PAYLOAD['knownRestrictions']}\n",
    })

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


def test_ac1_venue_details_include_safety_information(setup):
    """Normal: the details read returns the recorded texts."""
    client, cursor, _ = setup
    cursor.fetchone.return_value = safety_row()

    response = client.get(f"/venues/{VENUE_ID}")

    assert response.status_code == 200
    assert response.json["venue"]["emergencyAccessDetails"] == SAFETY_PAYLOAD["emergencyAccessDetails"]
    assert response.json["venue"]["knownRestrictions"] == SAFETY_PAYLOAD["knownRestrictions"]
    select_query = cursor.execute.call_args.args[0]
    assert all(column in select_query for column in SAFETY_COLUMNS)


def test_ac1_catalogue_list_includes_safety_information(setup):
    """Normal: the catalogue list carries the fields, because Safety Check reads it."""
    client, cursor, _ = setup
    cursor.fetchall.return_value = [safety_row()]

    response = client.get("/venues")

    assert response.status_code == 200
    venue = response.json["venues"][0]
    assert venue["emergencyAccessDetails"] == SAFETY_PAYLOAD["emergencyAccessDetails"]
    assert venue["knownRestrictions"] == SAFETY_PAYLOAD["knownRestrictions"]
    assert venue["safetyInfoUpdatedBy"] == STAFF_ID


def test_ac1_text_of_exactly_2000_characters_is_accepted(setup):
    """Boundary: 2000 characters is the longest text allowed."""
    client, cursor, _ = setup
    cursor.fetchone.return_value = safety_row()

    response = put_safety(client, {"emergencyAccessDetails": "x" * 2000, "knownRestrictions": "y" * 2000})

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
)
def test_ac1_text_of_2001_characters_is_refused(key, label, setup):
    """Boundary: one character over the limit is refused before the database."""
    client, _, connect = setup

    response = put_safety(client, {**SAFETY_PAYLOAD, key: "x" * 2001})

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
def test_ac1_missing_key_or_non_text_value_is_refused(body, error, setup):
    """Failure: the body must name both fields as text or null."""
    client, _, connect = setup

    response = put_safety(client, body)

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
def test_ac2_unrecorded_safety_information_serialises_as_null(row, setup):
    """Boundary: nothing recorded reads as null (the UI shows "Not provided"), never ""."""
    client, cursor, _ = setup
    cursor.fetchone.return_value = row

    venue = client.get(f"/venues/{VENUE_ID}").json["venue"]

    assert venue["emergencyAccessDetails"] is None
    assert venue["knownRestrictions"] is None
    assert venue["safetyInfoUpdatedBy"] is None
    assert venue["safetyInfoUpdatedAt"] is None


@pytest.mark.parametrize("blank", ["", "   ", None], ids=["empty", "whitespace", "null"])
def test_ac2_blank_or_whitespace_input_is_stored_as_null(blank, setup):
    """Boundary: a cleared field is stored as NULL, not empty text."""
    client, cursor, _ = setup
    cursor.fetchone.return_value = saved_row()

    response = put_safety(client, {"emergencyAccessDetails": blank, "knownRestrictions": blank})

    assert response.status_code == 200
    _, params = cursor.execute.call_args_list[0].args
    assert params["emergency"] is None
    assert params["restrictions"] is None


# AC3 ----------------------------------------------------------------------


def test_ac3_update_stamps_editor_and_server_time(setup):
    """Normal: the save records the editor id and the database's own clock."""
    client, cursor, _ = setup
    cursor.fetchone.return_value = safety_row()

    put_safety(client)

    query, params = cursor.execute.call_args_list[0].args
    assert "safety_info_updated_by = %(editor)s" in query
    assert "safety_info_updated_at = now()" in query
    assert "IS DISTINCT FROM" in query
    assert params["editor"] == STAFF_ID


def test_ac3_serialised_timestamp_is_singapore_time(setup):
    """Normal: a UTC timestamp is returned as Singapore time."""
    client, cursor, _ = setup
    cursor.fetchone.return_value = safety_row()

    venue = client.get(f"/venues/{VENUE_ID}").json["venue"]

    assert venue["safetyInfoUpdatedAt"] == "2030-01-15T10:30:00+08:00"


def test_ac3_unchanged_save_returns_venue_without_restamping(setup):
    """Boundary: saving identical values updates nothing, so the old stamp stays."""
    client, cursor, _ = setup
    other_staff = "0e6f7c55-1b2a-4d3e-8f90-123456789abc"
    cursor.fetchone.side_effect = [None, safety_row(safety_info_updated_by=other_staff)]

    response = put_safety(client)

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
)
def test_ac4_non_venue_staff_role_is_refused_before_any_db_call(role, setup):
    """Failure: only Venue Staff may change safety information."""
    client, _, connect = setup

    response = put_safety(client, headers=staff_headers(role=role))

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
def test_ac4_missing_or_invalid_identity_is_refused(headers, message, setup):
    """Failure (SCRUM-8): a request without a valid sign-in never reaches the database."""
    _, _, connect = setup
    client = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"}).test_client()

    response = put_safety(client, headers=headers)

    assert response.status_code == 401
    assert response.json["message"] == message
    connect.assert_not_called()


def test_ac4_unknown_editor_is_refused(setup):
    """Failure: the User FK refuses an editor that does not exist; that is a 403, not a 503."""
    client, cursor, _ = setup
    cursor.execute.side_effect = psycopg2.errors.ForeignKeyViolation("fk_venue_safety_editor")

    response = put_safety(client)

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
def test_ac4_profile_edit_does_not_write_safety_fields(method, path, fetches, setup):
    """Conflict: the profile routes have no role check, so they must ignore safety keys."""
    client, cursor, _ = setup
    cursor.fetchone.side_effect = fetches
    body = {
        **VALID_PAYLOAD,
        "emergencyAccessDetails": "Smuggled exits",
        "knownRestrictions": "Smuggled restrictions",
        "safetyInfoUpdatedBy": STAFF_ID,
    }

    response = getattr(client, method)(path, json=body)

    assert response.status_code in (200, 201)
    write_query, write_params = cursor.execute.call_args_list[-1].args
    written = write_query.split("RETURNING")[0]
    assert not any(column in written for column in SAFETY_COLUMNS)
    assert "Smuggled exits" not in write_params
    assert "Smuggled restrictions" not in write_params
    assert STAFF_ID not in write_params


def test_cors_allows_the_authorization_header(setup):
    """Normal: the browser preflight for the safety save is allowed to send the sign-in token."""
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


# Other failures -----------------------------------------------------------


def test_unknown_venue_is_404(setup):
    """Failure: no row updated and none found means the venue does not exist."""
    client, cursor, _ = setup
    cursor.fetchone.side_effect = [None, None]

    response = put_safety(client)

    assert response.status_code == 404
    assert response.json["message"] == "Venue not found."


def test_database_error_is_503(setup, monkeypatch):
    """Failure: a database outage is a 503 without internals."""
    client, _, _ = setup

    def explode(*args, **kwargs):
        raise psycopg2.OperationalError("connection refused to db.example")

    monkeypatch.setattr("app.models.psycopg2.connect", explode)

    response = put_safety(client)

    assert response.status_code == 503
    assert "db.example" not in response.get_data(as_text=True)


def test_database_not_configured_is_503():
    """Failure: no DATABASE_URL means the save cannot run."""
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client(), role="Venue Staff")

    response = put_safety(client)

    assert response.status_code == 503
