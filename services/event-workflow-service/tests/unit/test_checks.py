"""SCRUM-20 AC3: the contradiction rules, as pure functions and via find_conflicts."""
from datetime import datetime

import pytest

from app import checks, clients

EVENT_ID = "00000000-0000-0000-0000-000000000001"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
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
    monkeypatch.setattr(clients, "list_event_equipment_requests", lambda event_id, viewer: data["own"])
    monkeypatch.setattr(clients, "list_overlapping_events", lambda *args: data["others"])
    monkeypatch.setattr(clients, "list_approved_equipment_requests", lambda ids, viewer: data["approved"])
    monkeypatch.setattr(clients, "list_equipment", lambda: data["equipment"])
    return data


def conflicts(changes, high):
    return checks.find_conflicts(EVENT, changes, high, COORDINATOR_ID)


# --- dates vs venue bookings ---------------------------------------------------


def test_new_dates_overlapping_a_booking_are_fine(world):
    assert conflicts({"preferredEndDate": "2026-11-10T18:00"}, ["preferredEndDate"]) == []


def test_new_dates_overlapping_no_live_booking_contradict_it(world):
    result = conflicts(
        {"preferredStartDate": "2026-11-20T09:00", "preferredEndDate": "2026-11-20T12:00"},
        ["preferredStartDate", "preferredEndDate"],
    )

    assert [item["area"] for item in result] == ["venue"]
    assert "10 Nov 2026 09:00 to 10 Nov 2026 12:00" in result[0]["message"]


def test_a_cancelled_booking_is_not_a_contradiction(world):
    world["bookings"] = [booking(status="Cancelled")]

    assert conflicts(
        {"preferredStartDate": "2026-11-20T09:00", "preferredEndDate": "2026-11-20T12:00"},
        ["preferredStartDate"],
    ) == []


def test_an_event_with_no_booking_has_nothing_to_contradict(world):
    world["bookings"] = []

    assert conflicts({"preferredEndDate": "2026-11-10T18:00"}, ["preferredEndDate"]) == []


# --- dates vs equipment --------------------------------------------------------


def moved_dates():
    return {"preferredStartDate": "2026-11-10T08:00", "preferredEndDate": "2026-11-10T18:00"}


def test_equipment_within_stock_is_fine(world):
    world["others"] = [{"id": "other"}]
    world["approved"] = [{"equipmentId": MIC, "quantityRequested": 3}]

    assert conflicts(moved_dates(), ["preferredStartDate"]) == []


def test_equipment_held_by_an_overlapping_event_contradicts(world):
    world["others"] = [{"id": "other"}]
    world["approved"] = [{"equipmentId": MIC, "quantityRequested": 4}]

    result = conflicts(moved_dates(), ["preferredStartDate"])

    assert [item["area"] for item in result] == ["equipment"]
    assert "Microphone: 2 requested but only 1 available" in result[0]["message"]


def test_equipment_that_is_not_available_has_no_stock(world):
    world["equipment"] = [{**MICROPHONES, "status": "Maintenance"}]

    result = conflicts(moved_dates(), ["preferredStartDate"])

    assert "only 0 available" in result[0]["message"]


def test_an_unknown_equipment_item_has_no_stock(world):
    world["equipment"] = []

    result = conflicts(moved_dates(), ["preferredStartDate"])

    assert result[0]["message"].startswith("Requested equipment: 2 requested")


def test_rejected_lines_are_ignored(world):
    world["own"] = [line(quantity=99, status="Rejected")]

    assert conflicts(moved_dates(), ["preferredStartDate"]) == []


def test_no_equipment_requests_skips_the_stock_lookup(world, monkeypatch):
    world["own"] = []

    def fail():
        raise AssertionError("stock should not be read")

    monkeypatch.setattr(clients, "list_equipment", fail)

    assert conflicts(moved_dates(), ["preferredStartDate"]) == []


# --- attendance vs venue capacity ----------------------------------------------


def test_attendance_above_a_venues_capacity_contradicts(world):
    result = conflicts({"expectedAttendance": "200"}, ["expectedAttendance"])

    assert result[0]["message"] == "Hall A holds up to 150 people, fewer than the new attendance of 200."


def test_attendance_within_capacity_is_fine(world):
    assert conflicts({"expectedAttendance": "150"}, ["expectedAttendance"]) == []


def test_a_decrease_is_never_checked(world):
    world["venues"] = [{**HALL_A, "capacity": 10}]

    assert conflicts({"expectedAttendance": "50"}, ["expectedAttendance"]) == []


def test_a_venue_missing_from_the_catalogue_is_skipped(world):
    world["venues"] = []

    assert conflicts({"expectedAttendance": "900"}, ["expectedAttendance"]) == []


def test_an_unnamed_venue_is_still_described(world):
    world["venues"] = [{"id": HALL, "capacity": 10}]

    assert conflicts({"expectedAttendance": "900"}, ["expectedAttendance"])[0]["message"].startswith(
        "The booked venue holds up to 10"
    )


def test_attendance_with_no_live_booking_skips_the_catalogue(world, monkeypatch):
    world["bookings"] = []

    def fail():
        raise AssertionError("venues should not be read")

    monkeypatch.setattr(clients, "list_venues", fail)

    assert conflicts({"expectedAttendance": "900"}, ["expectedAttendance"]) == []


def test_a_blank_current_attendance_counts_as_an_increase():
    assert checks.attendance_increased({"expectedAttendance": ""}, {"expectedAttendance": "5"})
    assert checks.attendance_increased({"expectedAttendance": "n/a"}, {"expectedAttendance": "5"})


def test_a_non_numeric_new_attendance_is_not_an_increase():
    assert not checks.attendance_increased(EVENT, {"expectedAttendance": "many"})
    assert not checks.attendance_increased(EVENT, {})


# --- fields with no rule -------------------------------------------------------


@pytest.mark.parametrize("field", ["venueRequirements", "equipmentRequirements", "accessibilityNeeds"])
def test_fields_without_a_rule_read_nothing(world, monkeypatch, field):
    def fail(*args):
        raise AssertionError("nothing should be read")

    monkeypatch.setattr(clients, "get_event_venue_bookings", fail)

    assert conflicts({field: "anything"}, [field]) == []


def test_dates_missing_on_a_legacy_event_are_skipped(world, monkeypatch):
    def fail(*args):
        raise AssertionError("nothing should be read")

    monkeypatch.setattr(clients, "get_event_venue_bookings", fail)

    assert checks.find_conflicts(
        {**EVENT, "preferredStartDate": "", "preferredEndDate": ""},
        {"preferredEndDate": ""},
        ["preferredEndDate"],
        COORDINATOR_ID,
    ) == []


def test_timezone_aware_booking_times_are_read_as_singapore_time():
    assert checks._naive("2026-11-10T01:00:00+00:00") == datetime(2026, 11, 10, 9)
    assert checks._naive(None) is None
