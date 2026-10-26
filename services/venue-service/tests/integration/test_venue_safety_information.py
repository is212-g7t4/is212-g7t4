"""SCRUM-167 Record Venue Safety Information: Venue Service integration tests.

Story:      As a Venue Staff member, I want to record a venue's emergency access details
            and known operational restrictions, so that the Safety Officer can take them
            into account when reviewing events at that venue.
Real:       Flask app and routes, the X-Dev-* role check, validation, app/models.py SQL,
            postgres:17.6 with the full migration chain (including the User FK on
            safety_info_updated_by).
Doubled:    nothing (Venue Service makes no outbound calls).
Not proven: authentication (identity is whatever the X-Dev-* headers say; guide §12.2);
            that the Safety Officer sees the values (Safety Check Service's tests); the UI
            parts of AC1, AC2 and AC4 (frontend Vitest and Playwright).

AC1  Given authorised Venue Staff edit a venue, when they enter emergency access details
     (e.g. exits, assembly point, emergency vehicle access) and known restrictions (e.g.
     noise curfew, no open flames, floor load limit), then the details are saved with the
     venue and shown on its details page.
AC2  Given a venue has no safety information recorded, when it is viewed, then the fields
     show "Not provided" rather than appearing blank.
AC3  Given safety information is updated, when it is saved, then the editor and timestamp
     are recorded.
AC4  Given a user who is not Venue Staff, when they attempt to edit venue safety
     information through the UI or API, then the change is rejected and the existing
     values are unchanged.
"""

from datetime import timedelta
from uuid import uuid4

import pytest

from tests.integration.factories import (
    EMERGENCY,
    OLD_STAMP,
    OTHER_STAFF_ID,
    PROFILE,
    RESTRICTIONS,
    STAFF_ID,
    UNKNOWN_ID,
    make_user,
    make_venue,
    staff_headers,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

SAFETY_BODY = {"emergencyAccessDetails": EMERGENCY, "knownRestrictions": RESTRICTIONS}
SAFETY_COLUMNS = (
    "emergency_access_details",
    "known_restrictions",
    "safety_info_updated_by",
    "safety_info_updated_at",
)


def recorded_venue(db):
    """A venue whose safety information STAFF_ID recorded at OLD_STAMP."""
    make_user(db, STAFF_ID)
    return make_venue(
        db,
        emergency_access_details=EMERGENCY,
        known_restrictions=RESTRICTIONS,
        safety_info_updated_by=STAFF_ID,
        safety_info_updated_at=OLD_STAMP,
    )


def safety_state(db, venue_id):
    row = db.venue(venue_id)
    return {column: row[column] for column in SAFETY_COLUMNS}


def put_safety(client, venue_id, body=SAFETY_BODY, headers=None):
    return client.put(
        f"/venues/{venue_id}/safety-info",
        json=body,
        headers=staff_headers() if headers is None else headers,
    )


# AC1 ----------------------------------------------------------------------


def test_ac1_venue_staff_saves_safety_details_with_the_venue(client, db):
    """Normal: the texts Venue Staff enter are stored on the venue's own row."""
    make_user(db, STAFF_ID)
    venue_id = make_venue(db)

    response = put_safety(client, venue_id)

    assert response.status_code == 200
    row = db.venue(venue_id)
    assert row["emergency_access_details"] == EMERGENCY
    assert row["known_restrictions"] == RESTRICTIONS
    assert response.json["venue"]["emergencyAccessDetails"] == EMERGENCY
    assert response.json["venue"]["knownRestrictions"] == RESTRICTIONS


def test_ac1_saved_details_are_returned_on_the_details_and_catalogue_reads(client, db):
    """Normal: the details page and the catalogue (which Safety Check reads) both return them."""
    make_user(db, STAFF_ID)
    venue_id = make_venue(db)
    assert put_safety(client, venue_id).status_code == 200

    details = client.get(f"/venues/{venue_id}").json["venue"]
    catalogue = client.get("/venues").json["venues"]

    assert details["emergencyAccessDetails"] == EMERGENCY
    assert details["knownRestrictions"] == RESTRICTIONS
    assert [(v["id"], v["emergencyAccessDetails"], v["knownRestrictions"]) for v in catalogue] == [
        (venue_id, EMERGENCY, RESTRICTIONS)
    ]


def test_ac1_text_of_exactly_2000_characters_is_saved(client, db):
    """Boundary: the longest allowed text is stored in full."""
    make_user(db, STAFF_ID)
    venue_id = make_venue(db)

    response = put_safety(
        client, venue_id, {"emergencyAccessDetails": "x" * 2000, "knownRestrictions": "y" * 2000}
    )

    assert response.status_code == 200
    assert db.venue(venue_id)["emergency_access_details"] == "x" * 2000
    assert db.venue(venue_id)["known_restrictions"] == "y" * 2000


def test_ac1_2001_characters_is_refused_and_nothing_changes(client, db):
    """Boundary: one character over the limit is refused and the stored values stay."""
    venue_id = recorded_venue(db)
    before = safety_state(db, venue_id)

    response = put_safety(client, venue_id, {**SAFETY_BODY, "knownRestrictions": "y" * 2001})

    assert response.status_code == 400
    assert response.json["errors"] == ["Known Restrictions must be at most 2000 characters."]
    assert safety_state(db, venue_id) == before


# AC2 ----------------------------------------------------------------------


def test_ac2_venue_without_safety_information_reads_as_null(client, db):
    """Boundary: nothing recorded reads as null (the UI shows "Not provided"), not "" or missing."""
    venue_id = make_venue(db)

    venue = client.get(f"/venues/{venue_id}").json["venue"]

    for key in ("emergencyAccessDetails", "knownRestrictions", "safetyInfoUpdatedBy", "safetyInfoUpdatedAt"):
        assert key in venue
        assert venue[key] is None


def test_ac2_clearing_the_fields_stores_null_not_empty_text(client, db):
    """Boundary: whitespace and null both clear a field to NULL, so it reads as "Not provided"."""
    venue_id = recorded_venue(db)

    response = put_safety(client, venue_id, {"emergencyAccessDetails": "   ", "knownRestrictions": None})

    assert response.status_code == 200
    row = db.venue(venue_id)
    assert row["emergency_access_details"] is None
    assert row["known_restrictions"] is None
    assert response.json["venue"]["emergencyAccessDetails"] is None
    assert response.json["venue"]["knownRestrictions"] is None


# AC3 ----------------------------------------------------------------------


def test_ac3_save_records_editor_and_time(client, db):
    """Normal: the editor's id and the database's time are stamped on the row."""
    make_user(db, STAFF_ID)
    venue_id = make_venue(db)

    response = put_safety(client, venue_id)

    row = db.venue(venue_id)
    now = db.now()
    assert str(row["safety_info_updated_by"]) == STAFF_ID
    assert now - timedelta(minutes=1) <= row["safety_info_updated_at"] <= now
    assert response.json["venue"]["safetyInfoUpdatedBy"] == STAFF_ID
    assert response.json["venue"]["safetyInfoUpdatedAt"].endswith("+08:00")


def test_ac3_a_later_edit_by_another_staff_member_restamps(client, db):
    """Normal: the stamp follows the latest editor, not the first one."""
    venue_id = recorded_venue(db)
    make_user(db, OTHER_STAFF_ID)

    response = put_safety(
        client,
        venue_id,
        {**SAFETY_BODY, "knownRestrictions": "Noise curfew 11pm"},
        headers=staff_headers(user_id=OTHER_STAFF_ID),
    )

    assert response.status_code == 200
    row = db.venue(venue_id)
    assert row["known_restrictions"] == "Noise curfew 11pm"
    assert str(row["safety_info_updated_by"]) == OTHER_STAFF_ID
    # OLD_STAMP is a far-future fixture date (guide §5), so compare with the DB clock.
    now = db.now()
    assert row["safety_info_updated_at"] != OLD_STAMP
    assert now - timedelta(minutes=1) <= row["safety_info_updated_at"] <= now


def test_ac3_saving_identical_values_does_not_restamp(client, db):
    """Boundary: nothing was updated, so the earlier editor and time stand."""
    venue_id = recorded_venue(db)
    make_user(db, OTHER_STAFF_ID)

    response = put_safety(client, venue_id, headers=staff_headers(user_id=OTHER_STAFF_ID))

    assert response.status_code == 200
    row = db.venue(venue_id)
    assert str(row["safety_info_updated_by"]) == STAFF_ID
    assert row["safety_info_updated_at"] == OLD_STAMP
    assert response.json["venue"]["safetyInfoUpdatedBy"] == STAFF_ID


# AC4 ----------------------------------------------------------------------


@pytest.mark.parametrize("role", ["Event Coordinator", "Safety Officer"])
def test_ac4_non_venue_staff_role_is_refused_and_values_are_unchanged(role, client, db):
    """Failure: an Event Coordinator or Safety Officer cannot change safety information."""
    venue_id = recorded_venue(db)
    make_user(db, OTHER_STAFF_ID, role=role)
    before = safety_state(db, venue_id)

    response = put_safety(
        client,
        venue_id,
        {"emergencyAccessDetails": "Changed", "knownRestrictions": None},
        headers=staff_headers(user_id=OTHER_STAFF_ID, role=role),
    )

    assert response.status_code == 403
    assert response.json["code"] == "VENUE_STAFF_ONLY"
    assert safety_state(db, venue_id) == before


def test_ac4_request_without_identity_is_refused_and_values_are_unchanged(client, db):
    """Failure: an anonymous API call cannot change safety information."""
    venue_id = recorded_venue(db)
    before = safety_state(db, venue_id)

    response = put_safety(client, venue_id, {"emergencyAccessDetails": "Changed", "knownRestrictions": None}, headers={})

    assert response.status_code == 401
    assert safety_state(db, venue_id) == before


def test_ac4_unknown_editor_is_refused_and_values_are_unchanged(client, db):
    """Failure: the real User FK refuses an editor id that is not a user, and nothing is written."""
    venue_id = recorded_venue(db)
    before = safety_state(db, venue_id)

    response = put_safety(
        client,
        venue_id,
        {"emergencyAccessDetails": "Changed", "knownRestrictions": None},
        headers=staff_headers(user_id=UNKNOWN_ID),
    )

    assert response.status_code == 403
    assert response.json["code"] == "UNKNOWN_EDITOR"
    assert safety_state(db, venue_id) == before


def test_ac4_profile_edit_cannot_change_safety_information(client, db):
    """Conflict: the unguarded profile route ignores safety keys, so it is no way around the role check."""
    venue_id = recorded_venue(db)
    make_user(db, OTHER_STAFF_ID)
    before = safety_state(db, venue_id)

    response = client.put(
        f"/venues/{venue_id}",
        json={
            **PROFILE,
            "emergencyAccessDetails": "Smuggled exits",
            "knownRestrictions": "Smuggled restrictions",
            "safetyInfoUpdatedBy": OTHER_STAFF_ID,
        },
    )

    assert response.status_code == 200
    assert safety_state(db, venue_id) == before


# Other failures -----------------------------------------------------------


def test_unknown_venue_is_404(client, db):
    """Failure: saving safety information for a venue that does not exist creates nothing."""
    make_user(db, STAFF_ID)

    response = put_safety(client, str(uuid4()))

    assert response.status_code == 404
    assert db.venue_count() == 0
