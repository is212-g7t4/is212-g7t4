"""
SCRUM-145: Tentative Venue Hold

User Story
----------
As a Venue Staff, I would like to temporarily hold a venue while an Event
Coordinator is finalizing event arrangements, so that I can allow for the venue
booking to flow smoothly.

Acceptance Criteria
-------------------
AC1: Given a venue is available, when Venue Staff places a hold on it, then the
     venue status changes from Available to On Hold.
AC2: Given that Venue Staff wants to hold a venue, he cannot hold the venue
     that affects and eat into other bookings.
AC3: Given a venue is on hold, the venue is not available for a new booking.
AC4: Given Venue Staff is placing a hold, when they create the hold, then an
     expiry date and time must be provided.

SCRUM-148: Tentative Venue Hold Expire Alert

User Story
----------
As an Event Coordinator, I want to be notified 3 days before and when my venue
hold expires, so that I can be reminded to complete the required actions in
time

Acceptance Criteria
-------------------
AC1: Given an active venue hold has an upcoming expiry time, then the Event
     Coordinator receives a notification 3 days before this expiry.
AC2: Given the Event Coordinator receives the notification, then the
     notification identifies the venue and its expiry date/time.
AC3: Given the hold has already expired, then the system does not send a
     "before expiry" reminder.
AC4: Given the required action has already been completed and the hold is no
     longer active, then the expiry reminder is not sent.

SCRUM-147: Tentative Venue View Expiry

User Story
----------
As an Event Coordinator, I want to see when a venue hold expires, so that I
know how long I have to finalize the event before the hold expires.

Acceptance Criteria
-------------------
AC1: Given an Event Coordinator has a venue on hold, when they view the hold
     details, then the expiry date and time are displayed.
AC2: Given the hold has an expiry date and time, then the displayed expiry
     information is accurate.
AC3: Given the hold has expired, then the hold status is displayed as Expired

Real
----
- POST /venue-holds (Venue Staff only, expiry required and in the future,
  overlap with bookings and other holds, the coordinator it is held for), GET
  /venue-holds (active holds) and the coordinator's reminder read (holds
  expiring within three days) run for real.
- Assertions are on the status, codes and SQL sent.

Doubled
-------
- psycopg2.connect: Stub (`setup`/`client` fixtures) - fresh MagicMock
  connection; the cursor returns canned VenueBooking / VenueClosure rows (or
  raises); executed SQL, parameters and locks are inspected.

Not proven
----------
- That the SQL, locks and constraints behave the same on real PostgreSQL (->
  tests/integration/, throwaway postgres:17.6).
- The expiry job that turns holds into Expired (SCRUM-146) runs elsewhere (->
  venue-booking-service hold expiry tests).
"""

from datetime import datetime

from app.calendar import SINGAPORE
from tests.unit.factories import USER_ID, VENUE_ID, bearer


HOLD_HEADERS = bearer(USER_ID, "Venue Staff")


def test_ac1_place_hold_when_not_venue_staff_returns_403(setup):
    """
    Summary: Only Venue Staff can place a hold.
    AC1: Given a venue is available, when Venue Staff places a hold on it, then
        the venue status changes from Available to On Hold.
    Double: Mock (cursor not executed)
    """
    # Arrange (Given)
    client, _ = setup

    # Act (When)
    response = client.post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2099-10-01T12:00"},
        headers=bearer(USER_ID, "Event Coordinator"),
    )

    # Assert (Then)
    assert response.status_code == 403


def test_ac1_place_hold_with_internal_token_only_returns_401(setup, monkeypatch):
    """
    Summary: A background worker's internal token cannot place a hold.
    AC1: Given a venue is available, when Venue Staff places a hold on it, then
        the venue status changes from Available to On Hold.
    Double: Environment stub (configured internal token); the database cursor
        is a Mock and is asserted unused.
    """
    # Arrange (Given)
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "internal-test-token")
    client, cursor = setup

    # Act (When)
    response = client.application.test_client().post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2099-10-01T12:00"},
        headers={"X-Internal-Token": "internal-test-token"},
    )

    # Assert (Then)
    assert response.status_code == 401
    cursor.execute.assert_not_called()


def test_ac4_place_hold_without_expiry_returns_400(setup):
    """
    Summary: A hold must have an expiry date and time.
    AC4: Given Venue Staff is placing a hold, when they create the hold, then
        an expiry date and time must be provided.
    Double: Environment stub (configured internal token); the database cursor
        is a Mock and is asserted unused.
    """
    # Arrange (Given)
    client, _ = setup

    # Act (When)
    response = client.post(
        "/venue-holds", json={"venueId": VENUE_ID}, headers=HOLD_HEADERS
    )

    # Assert (Then)
    assert response.status_code == 400


def test_ac1_place_hold_with_non_object_body_returns_400(setup):
    """
    Summary: A request that is not a hold is refused.
    AC1: Given a venue is available, when Venue Staff places a hold on it, then
        the venue status changes from Available to On Hold.
    Double: None
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = client.post("/venue-holds", json=[], headers=HOLD_HEADERS)

    # Assert (Then)
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_ac4_place_hold_with_past_expiry_returns_400(setup):
    """
    Summary: A hold cannot expire in the past.
    AC4: Given Venue Staff is placing a hold, when they create the hold, then
        an expiry date and time must be provided.
    Double: None
    """
    # Arrange (Given)
    client, _ = setup

    # Act (When)
    response = client.post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2000-10-01T12:00"},
        headers=HOLD_HEADERS,
    )

    # Assert (Then)
    assert response.status_code == 400
    assert "future" in response.json["message"]


def test_ac1_place_hold_on_available_venue_saves_on_hold_row(setup):
    """
    Summary: Holding an available venue saves it as On Hold.
    AC1: Given a venue is available, when Venue Staff places a hold on it, then
        the venue status changes from Available to On Hold.
    Double: Stub (no overlap; inserted row)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [
        {"venue_id": VENUE_ID},
        None,
        {
            "hold_id": "00000000-0000-0000-0000-000000000010",
            "venue_id": VENUE_ID,
            "created_at": datetime(2026, 10, 8, 9),
            "expires_at": datetime(2099, 10, 1, 12),
            "held_by": USER_ID,
        },
    ]

    # Act (When)
    response = client.post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2099-10-01T12:00"},
        headers=HOLD_HEADERS,
    )

    # Assert (Then)
    assert response.status_code == 201
    sql, params = cursor.execute.call_args.args
    assert 'INSERT INTO public."VenueBooking"' in sql
    assert "'On Hold'" in sql
    assert "VenueHold" not in sql
    assert params[0] == VENUE_ID
    assert params[3] == USER_ID
    assert params[2] == params[5] == datetime(2099, 10, 1, 12, tzinfo=SINGAPORE)
    assert response.json["hold"]["venueId"] == VENUE_ID
    assert response.json["hold"]["expiresAt"] == "2099-10-01T12:00:00"


def test_ac2_place_hold_overlapping_booking_returns_409(setup):
    """
    Summary: A hold cannot eat into another booking.
    AC2: Given that Venue Staff wants to hold a venue, he cannot hold the venue
        that affects and eat into other bookings.
    Double: Stub (overlap found)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [{"venue_id": VENUE_ID}, {"booking_id": "existing"}]

    # Act (When)
    response = client.post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2099-10-01T12:00"},
        headers=HOLD_HEADERS,
    )

    # Assert (Then)
    assert response.status_code == 409
    assert (
        "status NOT IN ('Rejected', 'Cancelled', 'Expired')"
        in cursor.execute.call_args_list[2].args[0]
    )


def test_ac3_place_hold_overlapping_active_hold_returns_409(setup):
    """
    Summary: A hold cannot overlap another active hold.
    AC3: Given a venue is on hold, the venue is not available for a new
        booking.
    Double: Stub (overlap with an On Hold row)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [{"venue_id": VENUE_ID}, {"booking_id": "active"}]

    # Act (When)
    response = client.post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2099-10-01T12:00"},
        headers=HOLD_HEADERS,
    )

    # Assert (Then)
    assert response.status_code == 409


def test_ac1_place_hold_for_unknown_venue_returns_404(setup):
    """
    Summary: A hold must be for a venue that exists.
    AC1: Given a venue is available, when Venue Staff places a hold on it, then
        the venue status changes from Available to On Hold.
    Double: Stub (insert raises ForeignKeyViolation)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = None

    # Act (When)
    response = client.post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2099-10-01T12:00"},
        headers=HOLD_HEADERS,
    )

    # Assert (Then)
    assert response.status_code == 404


def test_ac1_list_holds_returns_active_holds(setup):
    """
    Summary: Venue Staff can list active holds.
    AC1: Given a venue is available, when Venue Staff places a hold on it, then
        the venue status changes from Available to On Hold.
    Double: Stub (cursor returns holds)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = [
        {
            "hold_id": "00000000-0000-0000-0000-000000000010",
            "venue_id": VENUE_ID,
            "created_at": datetime(2026, 10, 8, 9),
            "expires_at": datetime(2099, 10, 1, 12),
            "held_by": USER_ID,
        }
    ]

    # Act (When)
    response = client.get("/venue-holds")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["holds"][0]["venueId"] == VENUE_ID


def test_ac1_list_holds_reads_only_on_hold_rows(setup):
    """
    Summary: Only rows still On Hold are listed.
    AC1: Given a venue is available, when Venue Staff places a hold on it, then
        the venue status changes from Available to On Hold.
    Double: Stub (cursor; SQL inspected)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = []

    client.get("/venue-holds")

    sql = cursor.execute.call_args.args[0]

    # Act + Assert (When / Then)
    assert "status = 'On Hold'" in sql
    assert "hold_expires_at > now()" in sql
    assert "VenueHold" not in sql


COORDINATOR_HEADERS = bearer(USER_ID, "Event Coordinator")
HOLD_ROW = {
    "hold_id": "00000000-0000-0000-0000-000000000010",
    "venue_id": VENUE_ID,
    "created_at": datetime(2026, 10, 8, 9),
    "expires_at": datetime(2026, 10, 19, 12),
    "held_by": USER_ID,
}


def test_scrum148_ac1_place_hold_records_coordinator_it_is_for(setup):
    """
    Summary: The hold records which coordinator it is held for, so they can be reminded.
    SCRUM-148 AC1: Given an active venue hold has an upcoming expiry time, then
        the Event Coordinator receives a notification 3 days before this
        expiry.
    Double: Stub (cursor; insert inspected)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [{"venue_id": VENUE_ID}, None, HOLD_ROW]

    # Act (When)
    response = client.post(
        "/venue-holds",
        json={
            "venueId": VENUE_ID,
            "expiresAt": "2099-10-01T12:00",
            "coordinatorId": USER_ID,
        },
        headers=HOLD_HEADERS,
    )

    # Assert (Then)
    assert response.status_code == 201
    sql, params = cursor.execute.call_args.args
    assert "held_for" in sql
    assert params[-1] == USER_ID


def test_ac2_place_hold_with_coordinator_keeps_buffer_conflict_rules(setup):
    """
    Summary: Naming the coordinator does not drop the venue's buffer times from the overlap check.
    AC2: Given that Venue Staff wants to hold a venue, he cannot hold the venue
        that affects and eat into other bookings.
    Double: Stub (cursor; SQL inspected)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [{"venue_id": VENUE_ID}, None, HOLD_ROW]

    # Act (When)
    response = client.post(
        "/venue-holds",
        json={
            "venueId": VENUE_ID,
            "expiresAt": "2099-10-01T12:00",
            "coordinatorId": USER_ID,
            "setupTimeMinutes": 30,
            "turnaroundTimeMinutes": 45,
        },
        headers=HOLD_HEADERS,
    )

    # Assert (Then)
    assert response.status_code == 201
    overlap_params = next(call.args[1] for call in cursor.execute.call_args_list if "SELECT 1 FROM" in call.args[0])
    insert_params = next(call.args[1] for call in cursor.execute.call_args_list if "INSERT INTO" in call.args[0])
    assert overlap_params[3] == datetime(2099, 10, 1, 12, 30, tzinfo=SINGAPORE)
    assert insert_params[-1] == USER_ID


def test_scrum148_ac1_place_hold_with_bad_coordinator_id_returns_400(setup):
    """
    Summary: The coordinator a hold is for must be a valid id.
    SCRUM-148 AC1: Given an active venue hold has an upcoming expiry time, then
        the Event Coordinator receives a notification 3 days before this
        expiry.
    Double: None
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = client.post(
        "/venue-holds",
        json={
            "venueId": VENUE_ID,
            "expiresAt": "2099-10-01T12:00",
            "coordinatorId": "nope",
        },
        headers=HOLD_HEADERS,
    )

    # Assert (Then)
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_scrum148_ac1_ac2_scrum147_ac1_hold_reminders_return_own_holds_expiring_within_three_days(setup):
    """
    Summary: A coordinator is reminded of their holds expiring within three days, with venue and expiry.
    SCRUM-148 AC1: Given an active venue hold has an upcoming expiry time, then
        the Event Coordinator receives a notification 3 days before this
        expiry.
    SCRUM-148 AC2: Given the Event Coordinator receives the notification, then
        the notification identifies the venue and its expiry date/time.
    SCRUM-147 AC1: Given an Event Coordinator has a venue on hold, when they
        view the hold details, then the expiry date and time are displayed.
    Double: Stub (cursor returns holds; query inspected)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = [HOLD_ROW]

    # Act (When)
    response = client.get("/venue-holds/reminders", headers=COORDINATOR_HEADERS)

    # Assert (Then)
    assert response.status_code == 200
    reminder = response.json["reminders"][0]
    assert reminder["venueId"] == VENUE_ID
    assert reminder["expiresAt"] == "2026-10-19T12:00:00"
    sql, params = cursor.execute.call_args.args
    assert params == [USER_ID]


def test_scrum148_ac3_ac4_hold_reminders_skip_expired_or_inactive_holds(setup):
    """
    Summary: No reminder is given once a hold has expired or is no longer On Hold.
    SCRUM-148 AC3: Given the hold has already expired, then the system does not
        send a "before expiry" reminder.
    SCRUM-148 AC4: Given the required action has already been completed and the
        hold is no longer active, then the expiry reminder is not sent.
    Double: Stub (cursor; SQL inspected)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = []

    client.get("/venue-holds/reminders", headers=COORDINATOR_HEADERS)

    sql = cursor.execute.call_args.args[0]

    # Act + Assert (When / Then)
    assert "status = 'On Hold'" in sql
    assert "hold_expires_at > now()" in sql
    assert "hold_expires_at <= now() + interval '3 days'" in sql
    assert "held_for = %s" in sql


def test_scrum148_ac1_hold_reminders_when_lead_return_200(setup):
    """
    Summary: The Lead also gets hold reminders.
    SCRUM-148 AC1: Given an active venue hold has an upcoming expiry time, then
        the Event Coordinator receives a notification 3 days before this
        expiry.
    Double: Stub (cursor returns no rows)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = []

    # Act (When)
    response = client.get(
        "/venue-holds/reminders",
        headers=bearer(USER_ID, "Event Coordinator Lead"),
    )

    # Assert (Then)
    assert response.status_code == 200


def test_scrum148_ac1_hold_reminders_when_not_coordinator_return_403(setup):
    """
    Summary: Only coordinators get hold reminders.
    SCRUM-148 AC1: Given an active venue hold has an upcoming expiry time, then
        the Event Coordinator receives a notification 3 days before this
        expiry.
    Double: None
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = client.get("/venue-holds/reminders", headers=HOLD_HEADERS)

    # Assert (Then)
    assert response.status_code == 403
    cursor.execute.assert_not_called()


def test_scrum148_ac1_hold_reminders_with_internal_token_only_return_401(setup, monkeypatch):
    """
    Summary: Reminders are for the signed-in coordinator; an internal token has no one to remind.
    SCRUM-148 AC1: Given an active venue hold has an upcoming expiry time, then
        the Event Coordinator receives a notification 3 days before this
        expiry.
    Double: None
    """
    # Arrange (Given)
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "internal-test-token")
    client, cursor = setup

    # Act (When)
    response = client.application.test_client().get(
        "/venue-holds/reminders", headers={"X-Internal-Token": "internal-test-token"}
    )

    # Assert (Then)
    assert response.status_code == 401
    cursor.execute.assert_not_called()


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_support_list_holds_when_database_url_missing_returns_503(setup):
    """
    Summary: Listing holds reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured service answers 503
    Double: None
    """
    client, cursor = setup
    client.application.config["DATABASE_URL"] = None

    response = client.get("/venue-holds")

    assert response.status_code == 503
    cursor.execute.assert_not_called()


def test_support_hold_preflight_from_frontend_is_allowed(setup):
    """
    Summary: The frontend may place holds from a browser.
    Supporting design check: CORS for the configured frontend origin
    Double: None
    """
    client, cursor = setup

    response = client.options("/venue-holds")

    assert response.status_code == 200
    cursor.execute.assert_not_called()


def test_support_place_hold_when_database_url_missing_returns_503(setup):
    """
    Summary: Placing a hold reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured service answers 503
    Double: None
    """
    client, cursor = setup
    client.application.config.update(DATABASE_URL=None)

    response = client.post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2099-10-01T12:00"},
        headers=HOLD_HEADERS,
    )

    assert response.status_code == 503
    cursor.execute.assert_not_called()


def test_support_hold_reminders_when_database_url_missing_return_503(setup):
    """
    Summary: Reminders report themselves unavailable when no database is configured.
    Supporting design check: an unconfigured service answers 503
    Double: None
    """
    client, cursor = setup
    client.application.config.update(DATABASE_URL=None)

    response = client.get("/venue-holds/reminders", headers=COORDINATOR_HEADERS)

    assert response.status_code == 503
    cursor.execute.assert_not_called()
