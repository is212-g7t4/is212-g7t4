"""# Test scope and acceptance mapping — SCRUM-171 integration

- **SCRUM-30 submission regression (no direct SCRUM-171 AC):** real route/model SQL rejects approved/hold/closure blockers, preserves no-insert failure behavior, half-open boundaries, venue isolation and UTC-equivalent instants.
- **SCRUM-171 compatibility only:** closure snapshot columns and the transaction gate are accommodated without weakening these original assertions. Submission overlap is not closure-triggered AC1/AC2 evidence.

## Case/group traceability

The named test functions/cases below implement the groups above; their existing
names and assertions specify the scenario. No group is credited with all five ACs.

## Existing test contract and detailed cases

SCRUM-30: exercise submission through Flask, models and actual SQL."""

from datetime import datetime

import pytest

from app import create_app
from tests.unit.availability_db import AvailabilityDB
from tests.unit.factories import EVENT_ID, USER_ID, VENUE_ID, booking_row, signed_in

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


def test_approved_overlap_returns_type_without_insert(submit):
    response, db = submit([booking_row(status="Approved")])
    assert response.status_code == 409
    assert response.json["code"] == "VENUE_UNAVAILABLE"
    assert response.json["conflictTypes"] == ["APPROVED_BOOKING"]
    assert db.count() == 1
    assert not any("INSERT" in sql for sql in db.statements)
    assert "FOR UPDATE" in db.statements[1]


def test_active_tentative_hold_returns_its_type_without_insert(submit):
    response, db = submit(
        [booking_row(status="On Hold", hold_expires_at=datetime(2026, 10, 1, 12))]
    )
    assert response.status_code == 409
    assert response.json["conflictTypes"] == ["TENTATIVE_HOLD"]
    assert db.count() == 1
    assert not any("INSERT" in sql for sql in db.statements)


@pytest.mark.parametrize(
    "expiry", [datetime(2026, 10, 1, 9), datetime(2026, 10, 1, 10), None]
)
def test_stale_on_hold_does_not_block_even_before_expiry_worker(submit, expiry):
    response, db = submit([booking_row(status="On Hold", hold_expires_at=expiry)])
    assert response.status_code == 201
    assert response.json["status"] == "Pending Review"
    assert db.count() == 2


def test_recorded_closure_returns_type_without_insert(submit):
    response, db = submit(
        closures=[(VENUE_ID, datetime(2026, 10, 1, 10), datetime(2026, 10, 1, 11))]
    )
    assert response.status_code == 409
    assert response.json["code"] == "VENUE_UNAVAILABLE"
    assert response.json["conflictTypes"] == ["VENUE_CLOSURE"]
    assert db.count() == 0
    assert not any("INSERT" in sql for sql in db.statements)


@pytest.mark.parametrize("action", ["edit", "approve"])
def test_existing_edit_and_approval_report_closure_type(monkeypatch, action):
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
        response = client.patch(
            path, json={"reviewedBy": USER_ID} if action == "approve" else PAYLOAD
        )
        assert response.status_code == 409
        assert response.json["code"] == "VENUE_UNAVAILABLE"
        assert response.json["conflictTypes"] == ["VENUE_CLOSURE"]
        assert not any("UPDATE public" in sql for sql in db.statements)
    finally:
        db.db.close()


@pytest.mark.parametrize(
    "status", ["Pending", "Pending Review", "Rejected", "Cancelled", "Expired"]
)
def test_nonblocking_statuses_allow_pending_review(submit, status):
    response, db = submit(
        [booking_row(status=status, hold_expires_at=datetime(2026, 10, 1, 12))]
    )
    assert response.status_code == 201
    assert response.json["status"] == "Pending Review"
    assert response.json["requiredCapacity"] == 80
    assert response.json["venueRequirements"] == "Projector"
    assert db.count() == 2


@pytest.mark.parametrize(
    "kind", ["APPROVED_BOOKING", "TENTATIVE_HOLD", "VENUE_CLOSURE"]
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
)
def test_raw_half_open_sql_for_each_blocker(submit, kind, start, end, blocked):
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
    response, db = submit(bookings, closures)
    assert response.status_code == (409 if blocked else 201)
    assert db.count() == len(bookings) + (0 if blocked else 1)
    if blocked:
        assert response.json["conflictTypes"] == [kind]
        assert not any("INSERT" in sql for sql in db.statements)


@pytest.mark.parametrize("kind", ["Approved", "On Hold", "closure"])
def test_other_venue_does_not_block_same_event(submit, kind):
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
    response, db = submit(bookings, closures)
    assert response.status_code == 201
    assert response.json["eventId"] == EVENT_ID
    assert db.count() == len(bookings) + 1


def test_all_conflict_types_return_once_in_stable_order(submit):
    response, db = submit(
        [
            booking_row(status="Approved"),
            booking_row(status="Approved"),
            booking_row(status="On Hold", hold_expires_at=datetime(2026, 10, 2)),
        ],
        [(VENUE_ID, datetime(2026, 10, 1, 9), datetime(2026, 10, 1, 12))] * 2,
    )
    assert response.status_code == 409
    assert response.json["conflictTypes"] == [
        "APPROVED_BOOKING",
        "TENTATIVE_HOLD",
        "VENUE_CLOSURE",
    ]
    assert db.count() == 3


def test_overnight_request_is_not_split_or_clipped(submit):
    response, db = submit(
        closures=[(VENUE_ID, datetime(2026, 10, 2), datetime(2026, 10, 2, 1))],
        payload=PAYLOAD
        | {
            "requestedStartTime": "2026-10-01T23:00",
            "requestedEndTime": "2026-10-02T02:00",
        },
    )
    assert response.status_code == 409
    assert response.json["conflictTypes"] == ["VENUE_CLOSURE"]
    assert db.count() == 0


@pytest.mark.parametrize("stage", ["connect", "check", "insert"])
def test_database_failure_never_reports_availability_or_persists(monkeypatch, stage):
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


def test_conflict_helper_keeps_boolean_contract_and_self_exclusion():
    from app.models import _has_conflict
    from tests.unit.factories import BOOKING_ID

    db = AvailabilityDB([booking_row(status="Approved")])
    try:
        args = (db, VENUE_ID, datetime(2026, 10, 1, 9), datetime(2026, 10, 1, 12))
        assert _has_conflict(*args) is True
        assert _has_conflict(*args, exclude_booking_id=BOOKING_ID) is False
    finally:
        db.db.close()


def test_aware_times_keep_same_instant_at_sql_boundary():
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


def test_event_bookings_without_database_configuration_returns_503():
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client())
    assert client.get(f"/events/{EVENT_ID}/venue-bookings").status_code == 503
