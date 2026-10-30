"""
SCRUM-20: Event Information Management & Impact Validation

User Story
----------
As the Event Coordinator assigned to an event, I want to update event
information during the planning process, so that event details remain up to
date without introducing conflicts with arrangements already made for the
event.

Acceptance Criteria
-------------------
AC1: Given a field being updated is one of the low-impact fields (Event Name,
     Description, Purpose, Registration Needs), when the assigned Event
     Coordinator saves the change, then the update is applied and the system
     records the new information.
AC2: Given a field being updated is one of the high-impact fields (Date/Time,
     Expected Attendance, Venue Requirements, Equipment Requirements,
     Accessibility Needs), when the assigned Event Coordinator attempts to save
     the change, then the system checks the update against other arrangements
     already made for the event (e.g. confirmed venue bookings, equipment
     reservations) for contradictions before the change is applied.
AC3: Given a high-impact update contradicts an existing arrangement, the update
     is blocked and the Coordinator is shown the reason.
AC4: Given a high-impact update passes validation with no contradiction found,
     then the update is applied and saved.

Real
----
- app.checks: the contradiction rules for new dates against live venue
  bookings, equipment against stock held by overlapping events, and attendance
  against venue capacity, as pure functions and through find_conflicts().
- Assertions are on the reasons returned and which reads happen.

Doubled
-------
- Event, User, Venue Availability, Venue, Equipment Request and Equipment
  Services: Stub (`downstream` / `world` fixtures) - canned answers set per
  test; calls recorded so tests can assert what was (or was not) read or saved.

Not proven
----------
- That the downstream services return these shapes (-> tests/integration/ with
  respx).
"""
from datetime import datetime

import pytest

from app import checks, clients

EVENT_ID = "00000000-0000-0000-0000-000000000001"
HALL = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MIC = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

EVENT = {
    "id": EVENT_ID,
    "preferredStartDate": "2026-11-10T09:00",
    "preferredEndDate": "2026-11-10T12:00",
    "expectedAttendance": "100",
}


def booking(status="Approved", start="2026-11-10T09:00:00", end="2026-11-10T12:00:00"):
    return {
        "id": "b1",
        "venueId": HALL,
        "status": status,
        "requestedStartTime": start,
        "requestedEndTime": end,
    }


def line(quantity=2, status="Approved"):
    return {"equipmentId": MIC, "quantityRequested": quantity, "status": status}


MICROPHONES = {"id": MIC, "description": "Microphone", "totalQuantity": 5, "status": "Available"}
HALL_A = {"id": HALL, "name": "Hall A", "capacity": 150}


@pytest.fixture
def world(monkeypatch):
    """Downstream data, replaceable per test."""
    data = {
        "bookings": [booking()],
        "venues": [HALL_A],
        "own": [line()],
        "others": [],
        "approved": [],
        "equipment": [MICROPHONES],
    }
    monkeypatch.setattr(clients, "get_event_venue_bookings", lambda event_id: data["bookings"])
    monkeypatch.setattr(clients, "list_venues", lambda: data["venues"])
    monkeypatch.setattr(clients, "list_event_equipment_requests", lambda event_id: data["own"])
    monkeypatch.setattr(clients, "list_overlapping_events", lambda *args: data["others"])
    monkeypatch.setattr(clients, "list_approved_equipment_requests", lambda ids: data["approved"])
    monkeypatch.setattr(clients, "list_equipment", lambda: data["equipment"])
    return data


def conflicts(changes, high):
    return checks.find_conflicts(EVENT, changes, high)


def test_reserving_statuses_include_clarification_requested():
    """
    Summary: An event awaiting clarification keeps its approved equipment held.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: None
    """
    # Act + Assert (When / Then)
    assert "Clarification Requested" in checks.RESERVING_EVENT_STATUSES


def test_reserving_statuses_include_amendment_requested():
    """
    Summary: An event awaiting amendment keeps its approved equipment held.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: None
    """
    # Act + Assert (When / Then)
    assert "Amendment Requested" in checks.RESERVING_EVENT_STATUSES


# --- dates vs venue bookings ---------------------------------------------------


def test_find_conflicts_when_new_dates_overlap_booking_finds_none(world):
    """
    Summary: New dates that still overlap the booked venue time are fine.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (world: one live booking)
    """
    # Arrange (Given): world, from fixtures

    # Act + Assert (When / Then)
    assert conflicts({"preferredEndDate": "2026-11-10T18:00"}, ["preferredEndDate"]) == []


def test_find_conflicts_when_new_dates_miss_booking_reports_it(world):
    """
    Summary: New dates outside every booked venue time contradict the booking.
    AC3: Given a high-impact update contradicts an existing arrangement, the
        update is blocked and the Coordinator is shown the reason.
    Double: Stub (world: one live booking)
    """
    # Arrange (Given): world, from fixtures

    # Act (When)
    result = conflicts(
        {"preferredStartDate": "2026-11-20T09:00", "preferredEndDate": "2026-11-20T12:00"},
        ["preferredStartDate", "preferredEndDate"],
    )

    # Assert (Then)
    assert [item["area"] for item in result] == ["venue"]
    assert "10 Nov 2026 09:00 to 10 Nov 2026 12:00" in result[0]["message"]


def test_find_conflicts_ignores_cancelled_booking(world):
    """
    Summary: A cancelled booking cannot be contradicted.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (world: one cancelled booking)
    """
    # Arrange (Given)
    world["bookings"] = [booking(status="Cancelled")]

    # Act + Assert (When / Then)
    assert conflicts(
        {"preferredStartDate": "2026-11-20T09:00", "preferredEndDate": "2026-11-20T12:00"},
        ["preferredStartDate"],
    ) == []


def test_find_conflicts_without_bookings_finds_none(world):
    """
    Summary: An event with no booking has nothing for new dates to contradict.
    AC4: Given a high-impact update passes validation with no contradiction
        found, then the update is applied and saved.
    Double: Stub (world: no bookings)
    """
    # Arrange (Given)
    world["bookings"] = []

    # Act + Assert (When / Then)
    assert conflicts({"preferredEndDate": "2026-11-10T18:00"}, ["preferredEndDate"]) == []


# --- dates vs equipment --------------------------------------------------------


def moved_dates():
    return {"preferredStartDate": "2026-11-10T08:00", "preferredEndDate": "2026-11-10T18:00"}


def test_find_conflicts_when_equipment_within_stock_finds_none(world):
    """
    Summary: Equipment that still fits the stock in the new window is fine.
    AC4: Given a high-impact update passes validation with no contradiction
        found, then the update is applied and saved.
    Double: Stub (world: enough stock)
    """
    # Arrange (Given)
    world["others"] = [{"id": "other"}]
    world["approved"] = [{"equipmentId": MIC, "quantityRequested": 3}]

    # Act + Assert (When / Then)
    assert conflicts(moved_dates(), ["preferredStartDate"]) == []


def test_find_conflicts_when_overlapping_event_holds_stock_reports_it(world):
    """
    Summary: Equipment already held by an overlapping event contradicts the change.
    AC3: Given a high-impact update contradicts an existing arrangement, the
        update is blocked and the Coordinator is shown the reason.
    Double: Stub (world: overlapping event holds stock)
    """
    # Arrange (Given)
    world["others"] = [{"id": "other"}]
    world["approved"] = [{"equipmentId": MIC, "quantityRequested": 4}]

    # Act (When)
    result = conflicts(moved_dates(), ["preferredStartDate"])

    # Assert (Then)
    assert [item["area"] for item in result] == ["equipment"]
    assert "Microphone: 2 requested but only 1 available" in result[0]["message"]


def test_find_conflicts_when_equipment_unavailable_reports_it(world):
    """
    Summary: Equipment marked unavailable has no stock.
    AC3: Given a high-impact update contradicts an existing arrangement, the
        update is blocked and the Coordinator is shown the reason.
    Double: Stub (world: equipment Unavailable)
    """
    # Arrange (Given)
    world["equipment"] = [{**MICROPHONES, "status": "Maintenance"}]

    # Act (When)
    result = conflicts(moved_dates(), ["preferredStartDate"])

    # Assert (Then)
    assert "only 0 available" in result[0]["message"]


def test_find_conflicts_when_equipment_unknown_reports_it(world):
    """
    Summary: Equipment missing from the catalogue has no stock.
    AC3: Given a high-impact update contradicts an existing arrangement, the
        update is blocked and the Coordinator is shown the reason.
    Double: Stub (world: catalogue without the item)
    """
    # Arrange (Given)
    world["equipment"] = []

    # Act (When)
    result = conflicts(moved_dates(), ["preferredStartDate"])

    # Assert (Then)
    assert result[0]["message"].startswith("Requested equipment: 2 requested")


def test_find_conflicts_ignores_rejected_equipment_lines(world):
    """
    Summary: Rejected equipment lines are not checked.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (world: a Rejected line)
    """
    # Arrange (Given)
    world["own"] = [line(quantity=99, status="Rejected")]

    # Act + Assert (When / Then)
    assert conflicts(moved_dates(), ["preferredStartDate"]) == []


def test_find_conflicts_without_equipment_skips_stock_lookup(world, monkeypatch):
    """
    Summary: With no equipment requests, stock is not even read.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (world), Mock (stock lookup not called)
    """
    # Arrange (Given)
    world["own"] = []

    def fail():
        raise AssertionError("stock should not be read")

    monkeypatch.setattr(clients, "list_equipment", fail)

    # Act + Assert (When / Then)
    assert conflicts(moved_dates(), ["preferredStartDate"]) == []


# --- attendance vs venue capacity ----------------------------------------------


def test_find_conflicts_when_attendance_above_capacity_reports_it(world):
    """
    Summary: Attendance above a booked venue's capacity contradicts the booking.
    AC3: Given a high-impact update contradicts an existing arrangement, the
        update is blocked and the Coordinator is shown the reason.
    Double: Stub (world: booked venue capacity)
    """
    # Arrange (Given): world, from fixtures

    # Act (When)
    result = conflicts({"expectedAttendance": "200"}, ["expectedAttendance"])

    # Assert (Then)
    assert result[0]["message"] == "Hall A holds up to 150 people, fewer than the new attendance of 200."


def test_find_conflicts_when_attendance_within_capacity_finds_none(world):
    """
    Summary: Attendance that still fits the booked venue is fine.
    AC4: Given a high-impact update passes validation with no contradiction
        found, then the update is applied and saved.
    Double: Stub (world: booked venue capacity)
    """
    # Arrange (Given): world, from fixtures

    # Act + Assert (When / Then)
    assert conflicts({"expectedAttendance": "150"}, ["expectedAttendance"]) == []


def test_find_conflicts_when_attendance_decreases_skips_check(world):
    """
    Summary: Lowering attendance is never a contradiction.
    AC4: Given a high-impact update passes validation with no contradiction
        found, then the update is applied and saved.
    Double: Stub (world)
    """
    # Arrange (Given)
    world["venues"] = [{**HALL_A, "capacity": 10}]

    # Act + Assert (When / Then)
    assert conflicts({"expectedAttendance": "50"}, ["expectedAttendance"]) == []


def test_find_conflicts_skips_venue_missing_from_catalogue(world):
    """
    Summary: A booked venue missing from the catalogue is skipped rather than failing.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (world: venue not in catalogue)
    """
    # Arrange (Given)
    world["venues"] = []

    # Act + Assert (When / Then)
    assert conflicts({"expectedAttendance": "900"}, ["expectedAttendance"]) == []


def test_find_conflicts_describes_unnamed_venue(world):
    """
    Summary: A venue without a name is still described in the reason.
    AC3: Given a high-impact update contradicts an existing arrangement, the
        update is blocked and the Coordinator is shown the reason.
    Double: Stub (world: venue without a name)
    """
    # Arrange (Given)
    world["venues"] = [{"id": HALL, "capacity": 10}]

    # Act + Assert (When / Then)
    assert conflicts({"expectedAttendance": "900"}, ["expectedAttendance"])[0]["message"].startswith(
        "The booked venue holds up to 10"
    )


def test_find_conflicts_without_live_booking_skips_capacity_lookup(world, monkeypatch):
    """
    Summary: With no live booking, capacity is not looked up.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (world), Mock (catalogue not read)
    """
    # Arrange (Given)
    world["bookings"] = []

    def fail():
        raise AssertionError("venues should not be read")

    monkeypatch.setattr(clients, "list_venues", fail)

    # Act + Assert (When / Then)
    assert conflicts({"expectedAttendance": "900"}, ["expectedAttendance"]) == []


def test_attendance_increase_from_blank_counts_as_increase():
    """
    Summary: Setting attendance where there was none counts as an increase.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: None
    """
    # Act + Assert (When / Then)
    assert checks.attendance_increased({"expectedAttendance": ""}, {"expectedAttendance": "5"})
    assert checks.attendance_increased({"expectedAttendance": "n/a"}, {"expectedAttendance": "5"})


def test_attendance_increase_with_non_numeric_value_is_not_increase():
    """
    Summary: A non-numeric attendance is not treated as an increase.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: None
    """
    # Act + Assert (When / Then)
    assert not checks.attendance_increased(EVENT, {"expectedAttendance": "many"})
    assert not checks.attendance_increased(EVENT, {})


# --- fields with no rule -------------------------------------------------------


@pytest.mark.parametrize("field", ["venueRequirements", "equipmentRequirements", "accessibilityNeeds"], ids=["venue_requirements", "equipment_requirements", "accessibility_needs"])
def test_find_conflicts_for_field_without_rule_reads_nothing(world, monkeypatch, field):
    """
    Summary: High-impact fields without a contradiction rule trigger no reads.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (world), Mock (no reads)
    """
    # Arrange (Given)
    def fail(*args):
        raise AssertionError("nothing should be read")

    monkeypatch.setattr(clients, "get_event_venue_bookings", fail)

    # Act + Assert (When / Then)
    assert conflicts({field: "anything"}, [field]) == []


def test_find_conflicts_for_legacy_event_without_dates_skips_date_checks(world, monkeypatch):
    """
    Summary: An older event without dates is not date-checked.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (world), Mock (no window reads)
    """
    # Arrange (Given)
    def fail(*args):
        raise AssertionError("nothing should be read")

    monkeypatch.setattr(clients, "get_event_venue_bookings", fail)

    # Act + Assert (When / Then)
    assert checks.find_conflicts(
        {**EVENT, "preferredStartDate": "", "preferredEndDate": ""},
        {"preferredEndDate": ""},
        ["preferredEndDate"],
    ) == []


def test_booking_times_with_offset_are_read_in_singapore_time():
    """
    Summary: Booking times with a time zone are compared in Singapore time.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: None
    """
    # Act + Assert (When / Then)
    assert checks._naive("2026-11-10T01:00:00+00:00") == datetime(2026, 11, 10, 9)
    assert checks._naive(None) is None
