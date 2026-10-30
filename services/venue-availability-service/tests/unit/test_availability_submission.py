"""
SCRUM-30: Check Venue Availability

User Story
----------
As an Event Coordinator, I want to check availability for a selected venue and
booking period, so that I can avoid submitting a venue request that conflicts
with an existing event or closure.

Acceptance Criteria
-------------------
AC1: Given no conflicting confirmed bookings exist for the selected valid venue
     and booking start/end times, when the Event Coordinator submits the
     booking request, then the request is created with status Pending Review.
AC2: Given the selected date and time interval overlaps an approved booking,
     applicable tentative hold, or recorded closure for that venue, then the
     system reports the conflict type and indicates that the venue request
     cannot be submitted for that interval.

Real
----
- POST /venue-bookings and the conflict checker: half-open overlap against
  approved bookings, active holds and recorded closures for the same venue,
  each reported by type without inserting, and the insert as Pending Review
  when nothing conflicts.
- Assertions are on the status, the conflict types and the SQL sent.

Doubled
-------
- psycopg2.connect: Stub (`setup`/`client` fixtures) - fresh MagicMock
  connection; the cursor returns canned VenueBooking / VenueClosure rows (or
  raises); executed SQL, parameters and locks are inspected.

Not proven
----------
- That the overlap SQL, locks and constraints behave the same on real
  PostgreSQL (-> tests/integration/, throwaway postgres:17.6, and the opt-in
  tests/live/test_calendar.py).
- That the coordinator sees the conflict message (-> frontend
  venueBookings.test.ts).
"""

from datetime import datetime

import pytest

from app import create_app
from tests.unit.availability_db import AvailabilityDB
from tests.unit.factories import bearer, EVENT_ID, USER_ID, VENUE_ID, booking_row, signed_in

PAYLOAD = dict(
    eventId=EVENT_ID,
    venueId=VENUE_ID,
    requestedBy=USER_ID,
    requestedStartTime="2026-10-01T09:00",
    requestedEndTime="2026-10-01T12:00",
    requiredCapacity=80,
    venueRequirements="Projector",
)


@pytest.fixture
def submit(monkeypatch):
    databases = []

    def run(bookings=(), closures=(), payload=None):
        db = AvailabilityDB(bookings, closures)
        databases.append(db)
        monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: db)
        client = signed_in(create_app(
            {"TESTING": True, "DATABASE_URL": "isolated-sqlite"}
        ).test_client())
        return client.post("/venue-bookings", json=payload or PAYLOAD), db

    yield run
    for db in databases:
        db.db.close()


def test_create_booking_overlapping_approved_booking_reports_type_without_saving(submit):
    """
    Summary: A request overlapping an approved booking is refused with the conflict type and not saved.
    AC2: Given the selected date and time interval overlaps an approved
        booking, applicable tentative hold, or recorded closure for that venue,
        then the system reports the conflict type and indicates that the venue
        request cannot be submitted for that interval.
    Double: Stub (overlap query finds an approved booking), Mock (no insert)
    """
    # Arrange (Given): submit, from fixtures

    # Act (When)
    response, db = submit([booking_row(status="Approved")])

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "VENUE_UNAVAILABLE"
    assert response.json["conflictTypes"] == ["APPROVED_BOOKING"]
    assert db.count() == 1
    assert not any("INSERT" in sql for sql in db.statements)
    assert "FOR UPDATE" in db.statements[1]


def test_create_booking_overlapping_active_hold_reports_type_without_saving(submit):
    """
    Summary: A request overlapping an active hold is refused with the conflict type.
    AC2: Given the selected date and time interval overlaps an approved
        booking, applicable tentative hold, or recorded closure for that venue,
        then the system reports the conflict type and indicates that the venue
        request cannot be submitted for that interval.
    Double: Stub (overlap query finds a hold), Mock (no insert)
    """
    # Arrange (Given): submit, from fixtures

    # Act (When)
    response, db = submit(
        [booking_row(status="On Hold", hold_expires_at=datetime(2026, 10, 1, 12))]
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["conflictTypes"] == ["TENTATIVE_HOLD"]
    assert db.count() == 1
    assert not any("INSERT" in sql for sql in db.statements)


@pytest.mark.parametrize(
    "expiry", [datetime(2026, 10, 1, 9), datetime(2026, 10, 1, 10), None],
    ids=["expired_before", "expires_now", "no_expiry"],
)
def test_create_booking_with_expired_hold_is_not_blocked(submit, expiry):
    """
    Summary: A hold past its expiry does not block, even before the expiry job runs.
    AC1: Given no conflicting confirmed bookings exist for the selected valid
        venue and booking start/end times, when the Event Coordinator submits
        the booking request, then the request is created with status Pending
        Review.
    Double: Stub (hold with expiry at or before now)
    """
    # Arrange (Given): submit, expiry, from fixtures

    # Act (When)
    response, db = submit([booking_row(status="On Hold", hold_expires_at=expiry)])

    # Assert (Then)
    assert response.status_code == 201
    assert response.json["status"] == "Pending Review"
    assert db.count() == 2


def test_create_booking_during_closure_reports_type_without_saving(submit):
    """
    Summary: A request during a recorded closure is refused with the conflict type.
    AC2: Given the selected date and time interval overlaps an approved
        booking, applicable tentative hold, or recorded closure for that venue,
        then the system reports the conflict type and indicates that the venue
        request cannot be submitted for that interval.
    Double: Stub (overlap query finds a closure), Mock (no insert)
    """
    # Arrange (Given): submit, from fixtures

    # Act (When)
    response, db = submit(
        closures=[(VENUE_ID, datetime(2026, 10, 1, 10), datetime(2026, 10, 1, 11))]
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "VENUE_UNAVAILABLE"
    assert response.json["conflictTypes"] == ["VENUE_CLOSURE"]
    assert db.count() == 0
    assert not any("INSERT" in sql for sql in db.statements)


@pytest.mark.parametrize("action", ["edit", "approve"], ids=["edit", "approve"])
def test_edit_or_approve_during_closure_reports_closure_type(monkeypatch, action):
    """
    Summary: Editing or approving into a closure reports the closure.
    AC2: Given the selected date and time interval overlaps an approved
        booking, applicable tentative hold, or recorded closure for that venue,
        then the system reports the conflict type and indicates that the venue
        request cannot be submitted for that interval.
    Double: Stub (overlap query finds a closure)
    """
    from tests.unit.factories import BOOKING_ID

    db = AvailabilityDB(
        [booking_row()],
        [(VENUE_ID, datetime(2026, 10, 1, 10), datetime(2026, 10, 1, 11))],
    )
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: db)
    try:
        client = signed_in(create_app(
            {"TESTING": True, "DATABASE_URL": "isolated-sqlite"}
        ).test_client())
        path = f"/venue-bookings/{BOOKING_ID}" + (
            "/approve" if action == "approve" else ""
        )
        role = "Venue Staff" if action == "approve" else "Event Coordinator"
        response = client.patch(
            path, json={"reviewedBy": USER_ID} if action == "approve" else PAYLOAD,
            headers=bearer(USER_ID, role),
        )
        assert response.status_code == 409
        assert response.json["code"] == "VENUE_UNAVAILABLE"
        assert response.json["conflictTypes"] == ["VENUE_CLOSURE"]
        assert not any("UPDATE public" in sql for sql in db.statements)
    finally:
        db.db.close()


@pytest.mark.parametrize(
    "status", ["Pending", "Pending Review", "Rejected", "Cancelled", "Expired"],
    ids=["pending", "pending_review", "rejected", "cancelled", "expired"],
)
def test_create_booking_next_to_non_blocking_status_is_saved_pending_review(submit, status):
    """
    Summary: Pending, rejected, cancelled or expired bookings do not block; the request is saved as Pending Review.
    AC1: Given no conflicting confirmed bookings exist for the selected valid
        venue and booking start/end times, when the Event Coordinator submits
        the booking request, then the request is created with status Pending
        Review.
    Double: Stub (overlap query finds a non-blocking row), Mock (insert)
    """
    # Arrange (Given): submit, status, from fixtures

    # Act (When)
    response, db = submit(
        [booking_row(status=status, hold_expires_at=datetime(2026, 10, 1, 12))]
    )

    # Assert (Then)
    assert response.status_code == 201
    assert response.json["status"] == "Pending Review"
    assert response.json["requiredCapacity"] == 80
    assert response.json["venueRequirements"] == "Projector"
    assert db.count() == 2


@pytest.mark.parametrize(
    "kind", ["APPROVED_BOOKING", "TENTATIVE_HOLD", "VENUE_CLOSURE"],
    ids=["approved_booking", "tentative_hold", "venue_closure"],
)
@pytest.mark.parametrize(
    "start,end,blocked",
    [
        ("2026-10-01T08:00", "2026-10-01T09:00", False),  # touches start
        ("2026-10-01T12:00", "2026-10-01T13:00", False),  # touches end
        ("2026-10-01T07:00", "2026-10-01T08:00", False),
        ("2026-10-01T13:00", "2026-10-01T14:00", False),
        ("2026-10-01T08:00", "2026-10-01T10:00", True),
        ("2026-10-01T11:00", "2026-10-01T13:00", True),
        ("2026-10-01T09:00", "2026-10-01T12:00", True),  # identical
        ("2026-10-01T10:00", "2026-10-01T11:00", True),  # contained
        ("2026-10-01T08:00", "2026-10-01T13:00", True),  # containing
        ("2026-09-30T23:00", "2026-10-01T10:00", True),  # overnight
    ],
    ids=["2026_10_01t08_00_2026_10_01t09_00_false", "2026_10_01t12_00_2026_10_01t13_00_false", "2026_10_01t07_00_2026_10_01t08_00_false", "2026_10_01t13_00_2026_10_01t14_00_false", "2026_10_01t08_00_2026_10_01t10_00_true", "2026_10_01t11_00_2026_10_01t13_00_true", "2026_10_01t09_00_2026_10_01t12_00_true", "2026_10_01t10_00_2026_10_01t11_00_true", "2026_10_01t08_00_2026_10_01t13_00_true", "2026_09_30t23_00_2026_10_01t10_00_true"],
)
def test_conflict_sql_uses_half_open_overlap_for_each_blocker(submit, kind, start, end, blocked):
    """
    Summary: Touching end-to-start times never conflict; any real overlap does, for every kind of blocker.
    AC2: (boundary: touching and overlapping intervals)
    Double: Stub (cursor; SQL inspected)
    """
    # Arrange (Given)
    start, end = datetime.fromisoformat(start), datetime.fromisoformat(end)
    bookings, closures = [], []
    if kind == "VENUE_CLOSURE":
        closures = [(VENUE_ID, start, end)]
    else:
        bookings = [
            booking_row(
                status="Approved" if kind == "APPROVED_BOOKING" else "On Hold",
                requested_start_time=start,
                requested_end_time=end,
                hold_expires_at=datetime(2026, 10, 2),
            )
        ]

    # Act (When)
    response, db = submit(bookings, closures)

    # Assert (Then)
    assert response.status_code == (409 if blocked else 201)
    assert db.count() == len(bookings) + (0 if blocked else 1)
    if blocked:
        assert response.json["conflictTypes"] == [kind]
        assert not any("INSERT" in sql for sql in db.statements)


@pytest.mark.parametrize("kind", ["Approved", "On Hold", "closure"], ids=["approved", "on_hold", "closure"])
def test_create_booking_at_other_venue_is_not_blocked_by_same_event(submit, kind):
    """
    Summary: Another venue's booking, hold or closure never blocks this venue.
    AC1: Given no conflicting confirmed bookings exist for the selected valid
        venue and booking start/end times, when the Event Coordinator submits
        the booking request, then the request is created with status Pending
        Review.
    Double: Stub (overlap query scoped to the venue)
    """
    # Arrange (Given)
    other = "00000000-0000-0000-0000-000000000002"
    bookings, closures = [], []
    if kind == "closure":
        closures = [(other, datetime(2026, 10, 1, 9), datetime(2026, 10, 1, 12))]
    else:
        bookings = [
            booking_row(
                venue_id=other, status=kind, hold_expires_at=datetime(2026, 10, 2)
            )
        ]

    # Act (When)
    response, db = submit(bookings, closures)

    # Assert (Then)
    assert response.status_code == 201
    assert response.json["eventId"] == EVENT_ID
    assert db.count() == len(bookings) + 1


def test_create_booking_with_several_blockers_reports_each_type_once_in_order(submit):
    """
    Summary: Several conflicts are each reported once, in a stable order.
    AC2: Given the selected date and time interval overlaps an approved
        booking, applicable tentative hold, or recorded closure for that venue,
        then the system reports the conflict type and indicates that the venue
        request cannot be submitted for that interval.
    Double: Stub (overlap query finds all three)
    """
    # Arrange (Given): submit, from fixtures

    # Act (When)
    response, db = submit(
        [
            booking_row(status="Approved"),
            booking_row(status="Approved"),
            booking_row(status="On Hold", hold_expires_at=datetime(2026, 10, 2)),
        ],
        [(VENUE_ID, datetime(2026, 10, 1, 9), datetime(2026, 10, 1, 12))] * 2,
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["conflictTypes"] == [
        "APPROVED_BOOKING",
        "TENTATIVE_HOLD",
        "VENUE_CLOSURE",
    ]
    assert db.count() == 3


def test_create_booking_overnight_checks_whole_interval(submit):
    """
    Summary: An overnight booking is checked as one interval, not split at midnight.
    AC2: Given the selected date and time interval overlaps an approved
        booking, applicable tentative hold, or recorded closure for that venue,
        then the system reports the conflict type and indicates that the venue
        request cannot be submitted for that interval.
    Double: Stub (cursor; SQL inspected)
    """
    # Arrange (Given): submit, from fixtures

    # Act (When)
    response, db = submit(
        closures=[(VENUE_ID, datetime(2026, 10, 2), datetime(2026, 10, 2, 1))],
        payload=PAYLOAD
        | {
            "requestedStartTime": "2026-10-01T23:00",
            "requestedEndTime": "2026-10-02T02:00",
        },
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["conflictTypes"] == ["VENUE_CLOSURE"]
    assert db.count() == 0


@pytest.mark.parametrize("stage", ["connect", "check", "insert"], ids=["connect", "check", "insert"])
def test_create_booking_when_database_fails_never_reports_available(monkeypatch, stage):
    """
    Summary: A database failure never reports the venue as available or saves anything.
    AC1: Given no conflicting confirmed bookings exist for the selected valid
        venue and booking start/end times, when the Event Coordinator submits
        the booking request, then the request is created with status Pending
        Review.
    Double: Stub (connect, check or insert raises)
    """
    import psycopg2

    db = AvailabilityDB()
    execute = db.execute

    def failing_execute(sql, params=()):
        if (stage == "check" and "conflict_type" in sql) or (
            stage == "insert" and "INSERT" in sql
        ):
            raise psycopg2.OperationalError("private database detail")
        execute(sql, params)

    def connect(*args, **kwargs):
        if stage == "connect":
            raise psycopg2.OperationalError("private database detail")
        return db

    monkeypatch.setattr("app.models.psycopg2.connect", connect)
    monkeypatch.setattr(db, "execute", failing_execute)
    try:
        client = signed_in(create_app(
            {"TESTING": True, "DATABASE_URL": "isolated-sqlite"}
        ).test_client())
        response = client.post("/venue-bookings", json=PAYLOAD)
        assert response.status_code == 503
        assert response.json == {"message": "Unable to save or load venue bookings."}
        assert db.count() == 0
    finally:
        db.db.close()


def test_conflict_helper_returns_bool_and_excludes_the_booking_itself():
    """
    Summary: The conflict check ignores the booking being edited.
    AC2: Given the selected date and time interval overlaps an approved
        booking, applicable tentative hold, or recorded closure for that venue,
        then the system reports the conflict type and indicates that the venue
        request cannot be submitted for that interval.
    Double: Stub (cursor; SQL inspected)
    """
    from app.models import _has_conflict
    from tests.unit.factories import BOOKING_ID

    db = AvailabilityDB([booking_row(status="Approved")])
    try:
        args = (db, VENUE_ID, datetime(2026, 10, 1, 9), datetime(2026, 10, 1, 12))
        assert _has_conflict(*args) is True
        assert _has_conflict(*args, exclude_booking_id=BOOKING_ID) is False
    finally:
        db.db.close()


def test_create_booking_with_offset_times_keeps_same_instant():
    """
    Summary: Times sent with a time zone are compared at the same real instant.
    AC2: Given the selected date and time interval overlaps an approved
        booking, applicable tentative hold, or recorded closure for that venue,
        then the system reports the conflict type and indicates that the venue
        request cannot be submitted for that interval.
    Double: Stub (cursor; parameters inspected)
    """
    from datetime import timezone

    from app.models import _has_conflict

    db = AvailabilityDB([booking_row(status="Approved")])
    try:
        assert (
            _has_conflict(
                db,
                VENUE_ID,
                datetime(2026, 10, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 10, 1, 4, tzinfo=timezone.utc),
            )
            is True
        )
    finally:
        db.db.close()


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_event_bookings_when_database_url_missing_returns_503():
    """
    Summary: Reading an event's bookings reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured service answers 503
    Double: None
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client())
    assert client.get(f"/events/{EVENT_ID}/venue-bookings").status_code == 503
