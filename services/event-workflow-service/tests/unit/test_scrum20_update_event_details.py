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
- PATCH /events/<id>/details: the dry-run preview through Event Service, the
  high-impact arrangement checks, the 409 with reasons on a contradiction, the
  actor-role forwarding and the save run for real.
- app.checks: the contradiction rules for new dates against live venue
  bookings, equipment against stock held by overlapping events, and attendance
  against venue capacity, as pure functions and through find_conflicts().
- app.clients: each downstream wrapper's request (URL, token, dry-run flag,
  actor role) and its mapping of timeouts, transport and server errors and
  refusals to the service's own exceptions.
- Assertions are on the status, reasons, which downstream calls are made, and
  the request sent or exception returned by each client.

Doubled
-------
- Event, User, Venue Availability, Venue, Equipment Request and Equipment
  Services: Stub (`downstream` fixture for the route tests, `world` fixture
  for the checks) - canned answers set per test; calls recorded so tests can
  assert what was (or was not) read or saved.
- httpx (the `send` fixture, client tests only): Stub - canned responses or
  raised errors; the outgoing requests are recorded and inspected.

Not proven
----------
- Which fields are low or high impact: Event Service decides that (->
  event-service unit tests for SCRUM-20).
- That the downstream services return these shapes or accept these requests (->
  tests/integration/ with respx, and E2E journeys).
- That the coordinator sees the reason in the UI (-> frontend
  EventEditDialog.test.tsx).
"""
from datetime import datetime

import httpx
import pytest

from app import checks, clients, create_app
from tests.unit.factories import signed_in

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
    Summary: checks.RESERVING_EVENT_STATUSES contains "Clarification Requested",
        so equipment approved to an event in that status counts against stock
        when another event's dates are checked.
    Supporting design check: statuses whose approved equipment is treated as
        held
    Double: None (constant read directly; no client called)
    """
    # Act + Assert (When / Then)
    assert "Clarification Requested" in checks.RESERVING_EVENT_STATUSES


def test_reserving_statuses_include_amendment_requested():
    """
    Summary: checks.RESERVING_EVENT_STATUSES contains "Amendment Requested",
        so equipment approved to an event in that status counts against stock
        when another event's dates are checked.
    Supporting design check: statuses whose approved equipment is treated as
        held
    Double: None (constant read directly; no client called)
    """
    # Act + Assert (When / Then)
    assert "Amendment Requested" in checks.RESERVING_EVENT_STATUSES


# --- dates vs venue bookings ---------------------------------------------------


def test_ac4_find_conflicts_when_new_dates_overlap_booking_finds_none(world):
    """
    Summary: find_conflicts for a new preferredEndDate (18:00, same day) that
        still overlaps the booked 09:00-12:00 venue slot returns no conflicts.
    AC4: Given a high-impact update passes validation with no contradiction
        found, then the update is applied and saved.
    Double: Stub (get_event_venue_bookings returns one Approved booking
        10 Nov 09:00-12:00; list_venues, equipment and overlapping-event
        clients return the default world data)
    """
    # Arrange (Given): world, from fixtures

    # Act + Assert (When / Then)
    assert conflicts({"preferredEndDate": "2026-11-10T18:00"}, ["preferredEndDate"]) == []


def test_ac3_find_conflicts_when_new_dates_miss_booking_reports_it(world):
    """
    Summary: find_conflicts for new dates of 20 Nov 09:00-12:00 against a
        booking on 10 Nov 09:00-12:00 returns one "venue" conflict whose
        message names the booked slot.
    AC3: Given a high-impact update contradicts an existing arrangement, the
        update is blocked and the Coordinator is shown the reason.
    Double: Stub (get_event_venue_bookings returns one Approved booking
        10 Nov 09:00-12:00; other clients return the default world data)
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


def test_ac4_find_conflicts_ignores_cancelled_booking(world):
    """
    Summary: find_conflicts for new dates of 20 Nov returns no conflicts when
        the only venue booking (10 Nov) is Cancelled.
    AC4: Given a high-impact update passes validation with no contradiction
        found, then the update is applied and saved.
    Double: Stub (get_event_venue_bookings returns one Cancelled booking;
        other clients return the default world data)
    """
    # Arrange (Given)
    world["bookings"] = [booking(status="Cancelled")]

    # Act + Assert (When / Then)
    assert conflicts(
        {"preferredStartDate": "2026-11-20T09:00", "preferredEndDate": "2026-11-20T12:00"},
        ["preferredStartDate"],
    ) == []


def test_ac4_find_conflicts_without_bookings_finds_none(world):
    """
    Summary: find_conflicts for a new preferredEndDate returns no conflicts
        when the event has no venue booking at all.
    AC4: Given a high-impact update passes validation with no contradiction
        found, then the update is applied and saved.
    Double: Stub (get_event_venue_bookings returns []; other clients return
        the default world data)
    """
    # Arrange (Given)
    world["bookings"] = []

    # Act + Assert (When / Then)
    assert conflicts({"preferredEndDate": "2026-11-10T18:00"}, ["preferredEndDate"]) == []


# --- dates vs equipment --------------------------------------------------------


def moved_dates():
    return {"preferredStartDate": "2026-11-10T08:00", "preferredEndDate": "2026-11-10T18:00"}


def test_ac4_find_conflicts_when_equipment_within_stock_finds_none(world):
    """
    Summary: find_conflicts for the moved dates returns no conflicts when the
        event wants 2 microphones, 5 are in stock and an overlapping event
        already holds 3.
    AC4: Given a high-impact update passes validation with no contradiction
        found, then the update is applied and saved.
    Double: Stub (list_overlapping_events returns one other event;
        list_approved_equipment_requests returns 3 microphones for it;
        list_equipment returns 5 Available microphones; own request is 2)
    """
    # Arrange (Given)
    world["others"] = [{"id": "other"}]
    world["approved"] = [{"equipmentId": MIC, "quantityRequested": 3}]

    # Act + Assert (When / Then)
    assert conflicts(moved_dates(), ["preferredStartDate"]) == []


def test_ac3_find_conflicts_when_overlapping_event_holds_stock_reports_it(world):
    """
    Summary: find_conflicts for the moved dates returns one "equipment"
        conflict reading "Microphone: 2 requested but only 1 available" when
        an overlapping event already holds 4 of the 5 microphones.
    AC3: Given a high-impact update contradicts an existing arrangement, the
        update is blocked and the Coordinator is shown the reason.
    Double: Stub (list_overlapping_events returns one other event;
        list_approved_equipment_requests returns 4 microphones for it;
        list_equipment returns 5 Available microphones; own request is 2)
    """
    # Arrange (Given)
    world["others"] = [{"id": "other"}]
    world["approved"] = [{"equipmentId": MIC, "quantityRequested": 4}]

    # Act (When)
    result = conflicts(moved_dates(), ["preferredStartDate"])

    # Assert (Then)
    assert [item["area"] for item in result] == ["equipment"]
    assert "Microphone: 2 requested but only 1 available" in result[0]["message"]


def test_ac3_find_conflicts_when_equipment_unavailable_reports_it(world):
    """
    Summary: find_conflicts for the moved dates returns a conflict containing
        "only 0 available" when the requested microphones have status
        Maintenance in the catalogue.
    AC3: Given a high-impact update contradicts an existing arrangement, the
        update is blocked and the Coordinator is shown the reason.
    Double: Stub (list_equipment returns the microphones with status
        Maintenance; own request is 2; no overlapping events)
    """
    # Arrange (Given)
    world["equipment"] = [{**MICROPHONES, "status": "Maintenance"}]

    # Act (When)
    result = conflicts(moved_dates(), ["preferredStartDate"])

    # Assert (Then)
    assert "only 0 available" in result[0]["message"]


def test_ac3_find_conflicts_when_equipment_unknown_reports_it(world):
    """
    Summary: find_conflicts for the moved dates returns a conflict starting
        "Requested equipment: 2 requested" when the equipment is missing from
        the catalogue.
    AC3: Given a high-impact update contradicts an existing arrangement, the
        update is blocked and the Coordinator is shown the reason.
    Double: Stub (list_equipment returns []; own request is 2 microphones; no
        overlapping events)
    """
    # Arrange (Given)
    world["equipment"] = []

    # Act (When)
    result = conflicts(moved_dates(), ["preferredStartDate"])

    # Assert (Then)
    assert result[0]["message"].startswith("Requested equipment: 2 requested")


def test_ac4_find_conflicts_ignores_rejected_equipment_lines(world):
    """
    Summary: find_conflicts for the moved dates returns no conflicts when the
        event's only equipment line (99 microphones) has status Rejected.
    AC4: Given a high-impact update passes validation with no contradiction
        found, then the update is applied and saved.
    Double: Stub (list_event_equipment_requests returns one Rejected line of
        99; other clients return the default world data)
    """
    # Arrange (Given)
    world["own"] = [line(quantity=99, status="Rejected")]

    # Act + Assert (When / Then)
    assert conflicts(moved_dates(), ["preferredStartDate"]) == []


def test_ac4_find_conflicts_without_equipment_skips_stock_lookup(world, monkeypatch):
    """
    Summary: find_conflicts for the moved dates returns no conflicts, and
        never reads the equipment catalogue, when the event has no equipment
        lines.
    AC4: Given a high-impact update passes validation with no contradiction
        found, then the update is applied and saved.
    Double: Stub (list_event_equipment_requests returns []; booking and venue
        clients return the default world data), Mock (list_equipment raises
        AssertionError if called)
    """
    # Arrange (Given)
    world["own"] = []

    def fail():
        raise AssertionError("stock should not be read")

    monkeypatch.setattr(clients, "list_equipment", fail)

    # Act + Assert (When / Then)
    assert conflicts(moved_dates(), ["preferredStartDate"]) == []


# --- attendance vs venue capacity ----------------------------------------------


def test_ac3_find_conflicts_when_attendance_above_capacity_reports_it(world):
    """
    Summary: find_conflicts for expectedAttendance 200 returns a conflict
        reading "Hall A holds up to 150 people, fewer than the new attendance
        of 200."
    AC3: Given a high-impact update contradicts an existing arrangement, the
        update is blocked and the Coordinator is shown the reason.
    Double: Stub (get_event_venue_bookings returns one live booking at Hall A;
        list_venues returns Hall A with capacity 150)
    """
    # Arrange (Given): world, from fixtures

    # Act (When)
    result = conflicts({"expectedAttendance": "200"}, ["expectedAttendance"])

    # Assert (Then)
    assert result[0]["message"] == "Hall A holds up to 150 people, fewer than the new attendance of 200."


def test_ac4_find_conflicts_when_attendance_within_capacity_finds_none(world):
    """
    Summary: find_conflicts for expectedAttendance 150 returns no conflicts
        when the booked venue holds exactly 150.
    AC4: Given a high-impact update passes validation with no contradiction
        found, then the update is applied and saved.
    Double: Stub (get_event_venue_bookings returns one live booking at Hall A;
        list_venues returns Hall A with capacity 150)
    """
    # Arrange (Given): world, from fixtures

    # Act + Assert (When / Then)
    assert conflicts({"expectedAttendance": "150"}, ["expectedAttendance"]) == []


def test_ac4_find_conflicts_when_attendance_decreases_skips_check(world):
    """
    Summary: find_conflicts for expectedAttendance 50 (down from 100) returns
        no conflicts even though the booked venue's capacity is only 10.
    AC4: Given a high-impact update passes validation with no contradiction
        found, then the update is applied and saved.
    Double: Stub (get_event_venue_bookings returns one live booking;
        list_venues returns Hall A with capacity 10)
    """
    # Arrange (Given)
    world["venues"] = [{**HALL_A, "capacity": 10}]

    # Act + Assert (When / Then)
    assert conflicts({"expectedAttendance": "50"}, ["expectedAttendance"]) == []


def test_ac4_find_conflicts_skips_venue_missing_from_catalogue(world):
    """
    Summary: find_conflicts for expectedAttendance 900 returns no conflicts
        when the booked venue is not in the venue catalogue.
    AC4: Given a high-impact update passes validation with no contradiction
        found, then the update is applied and saved.
    Double: Stub (get_event_venue_bookings returns one live booking;
        list_venues returns [])
    """
    # Arrange (Given)
    world["venues"] = []

    # Act + Assert (When / Then)
    assert conflicts({"expectedAttendance": "900"}, ["expectedAttendance"]) == []


def test_ac3_find_conflicts_describes_unnamed_venue(world):
    """
    Summary: find_conflicts for expectedAttendance 900 returns a conflict whose
        message starts "The booked venue holds up to 10" when the venue record
        has capacity 10 and no name.
    AC3: Given a high-impact update contradicts an existing arrangement, the
        update is blocked and the Coordinator is shown the reason.
    Double: Stub (get_event_venue_bookings returns one live booking;
        list_venues returns one venue with capacity 10 and no name)
    """
    # Arrange (Given)
    world["venues"] = [{"id": HALL, "capacity": 10}]

    # Act + Assert (When / Then)
    assert conflicts({"expectedAttendance": "900"}, ["expectedAttendance"])[0]["message"].startswith(
        "The booked venue holds up to 10"
    )


def test_ac4_find_conflicts_without_live_booking_skips_capacity_lookup(world, monkeypatch):
    """
    Summary: find_conflicts for expectedAttendance 900 returns no conflicts,
        and never reads the venue catalogue, when the event has no venue
        booking.
    AC4: Given a high-impact update passes validation with no contradiction
        found, then the update is applied and saved.
    Double: Stub (get_event_venue_bookings returns []), Mock (list_venues
        raises AssertionError if called)
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
    Summary: checks.attendance_increased is true when the event's current
        expectedAttendance is "" or "n/a" and the new value is "5".
    Supporting design check: a first-time or non-numeric current attendance
        counts as an increase, so the capacity check runs
    Double: None (pure function; no client called)
    """
    # Act + Assert (When / Then)
    assert checks.attendance_increased({"expectedAttendance": ""}, {"expectedAttendance": "5"})
    assert checks.attendance_increased({"expectedAttendance": "n/a"}, {"expectedAttendance": "5"})


def test_attendance_increase_with_non_numeric_value_is_not_increase():
    """
    Summary: checks.attendance_increased is false when the new expectedAttendance
        is "many" or when the change has no expectedAttendance.
    Supporting design check: a non-numeric new attendance is not treated as an
        increase
    Double: None (pure function; no client called)
    """
    # Act + Assert (When / Then)
    assert not checks.attendance_increased(EVENT, {"expectedAttendance": "many"})
    assert not checks.attendance_increased(EVENT, {})


# --- fields with no rule -------------------------------------------------------


@pytest.mark.parametrize("field", ["venueRequirements", "equipmentRequirements", "accessibilityNeeds"], ids=["venue_requirements", "equipment_requirements", "accessibility_needs"])
def test_find_conflicts_for_field_without_rule_reads_nothing(world, monkeypatch, field):
    """
    Summary: find_conflicts for venueRequirements, equipmentRequirements or
        accessibilityNeeds returns no conflicts and never reads venue
        bookings, because no contradiction rule exists for those fields.
    Supporting design check: the high-impact fields with no contradiction rule
        are passed without any downstream read (AC2's check is a no-op here)
    Double: Mock (get_event_venue_bookings raises AssertionError if called);
        other world clients are stubbed but unused
    """
    # Arrange (Given)
    def fail(*args):
        raise AssertionError("nothing should be read")

    monkeypatch.setattr(clients, "get_event_venue_bookings", fail)

    # Act + Assert (When / Then)
    assert conflicts({field: "anything"}, [field]) == []


def test_ac4_find_conflicts_for_legacy_event_without_dates_skips_date_checks(world, monkeypatch):
    """
    Summary: find_conflicts for an event whose preferred start and end dates
        are blank, changing preferredEndDate to blank, returns no conflicts
        and never reads venue bookings.
    AC4: Given a high-impact update passes validation with no contradiction
        found, then the update is applied and saved.
    Double: Mock (get_event_venue_bookings raises AssertionError if called);
        other world clients are stubbed but unused
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
    Summary: checks._naive("2026-11-10T01:00:00+00:00") returns 10 Nov 09:00
        (Singapore time) and checks._naive(None) returns None.
    Supporting design check: booking times with a time zone offset are compared
        in Singapore time
    Double: None (pure function; no client called)
    """
    # Act + Assert (When / Then)
    assert checks._naive("2026-11-10T01:00:00+00:00") == datetime(2026, 11, 10, 9)
    assert checks._naive(None) is None


# --- PATCH /events/<id>/details ------------------------------------------------

COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
UPDATE_EVENT = {"id": EVENT_ID, "expectedAttendance": "100"}


@pytest.fixture
def client():
    return signed_in(create_app().test_client(), COORDINATOR_ID)


def patch(client, changes=None, **overrides):
    body = {"changes": changes or {"eventName": "New"}}
    body.update(overrides)
    return client.patch(f"/events/{EVENT_ID}/details", json=body)


def preview(high=(), changed=("eventName",)):
    return {
        "event": UPDATE_EVENT,
        "changedFields": list(changed),
        "highImpactFields": list(high),
        "labels": [],
    }


@pytest.fixture
def downstream(monkeypatch):
    calls = {"previewed": [], "saved": [], "checked": []}
    state = {"role": "Event Coordinator", "preview": preview(), "conflicts": []}

    monkeypatch.setattr(clients, "get_user", lambda user_id: {"role": state["role"]})

    def fake_preview(event_id, changes, actor_role=None):
        calls["previewed"].append(actor_role)
        return state["preview"]

    def fake_save(event_id, changes, actor_role=None):
        calls["saved"].append(changes)
        return {"id": event_id, "status": "Approved"}

    def fake_conflicts(event, changes, high):
        calls["checked"].append(high)
        return state["conflicts"]

    monkeypatch.setattr(clients, "preview_event_details", fake_preview)
    monkeypatch.setattr(clients, "save_event_details", fake_save)
    monkeypatch.setattr("app.checks.find_conflicts", fake_conflicts)
    return calls, state


def test_ac1_update_details_with_low_impact_change_saves_without_arrangement_checks(client, downstream):
    """
    Summary: PATCH /events/<id>/details changing only eventName, which the
        preview reports as having no high-impact fields, answers 200 and saves
        {"eventName": "New"} without running the arrangement check.
    AC1: Given a field being updated is one of the low-impact fields (Event
        Name, Description, Purpose, Registration Needs), when the assigned
        Event Coordinator saves the change, then the update is applied and the
        system records the new information.
    Double: Stub (get_user returns Event Coordinator; preview_event_details
        returns highImpactFields=[]; save_event_details returns the event),
        Mock (save_event_details called once with the changes; find_conflicts
        not called)
    """
    # Arrange (Given)
    calls, _ = downstream

    # Act (When)
    response = patch(client)

    # Assert (Then)
    assert response.status_code == 200
    assert calls["saved"] == [{"eventName": "New"}]
    assert calls["checked"] == []


def test_ac2_ac4_update_details_with_high_impact_change_and_no_conflict_saves(client, downstream):
    """
    Summary: PATCH /events/<id>/details changing expectedAttendance to 80,
        which the preview reports as high impact, runs the arrangement check
        for that field, finds no conflict, and answers 200 after one save.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    AC4: Given a high-impact update passes validation with no contradiction
        found, then the update is applied and saved.
    Double: Stub (preview_event_details returns highImpactFields=
        ["expectedAttendance"]; find_conflicts returns []; get_user returns
        Event Coordinator), Mock (find_conflicts called once with
        ["expectedAttendance"]; save_event_details called once)
    """
    # Arrange (Given)
    calls, state = downstream
    state["preview"] = preview(high=["expectedAttendance"], changed=["expectedAttendance"])

    # Act (When)
    response = patch(client, {"expectedAttendance": "80"})

    # Assert (Then)
    assert response.status_code == 200
    assert calls["checked"] == [["expectedAttendance"]]
    assert len(calls["saved"]) == 1


def test_ac3_update_details_with_contradiction_returns_409_with_reasons(client, downstream):
    """
    Summary: PATCH /events/<id>/details changing expectedAttendance to 900
        answers 409 CHANGE_CONTRADICTS_ARRANGEMENTS with the venue conflict
        reason and nothing is saved.
    AC3: Given a high-impact update contradicts an existing arrangement, the
        update is blocked and the Coordinator is shown the reason.
    Double: Stub (preview_event_details returns highImpactFields=
        ["expectedAttendance"]; find_conflicts returns one venue "Too many."
        conflict; get_user returns Event Coordinator), Mock
        (save_event_details not called)
    """
    # Arrange (Given)
    calls, state = downstream
    state["preview"] = preview(high=["expectedAttendance"], changed=["expectedAttendance"])
    state["conflicts"] = [{"field": "expectedAttendance", "area": "venue", "message": "Too many."}]

    # Act (When)
    response = patch(client, {"expectedAttendance": "900"})

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "CHANGE_CONTRADICTS_ARRANGEMENTS"
    assert response.json["conflicts"] == state["conflicts"]
    assert calls["saved"] == []


def test_update_details_by_lead_sends_lead_role_to_event_service(client, downstream):
    """
    Summary: When User Service says the signed-in user is the Lead, the
        preview call to Event Service carries actor role "Event Coordinator
        Lead".
    Supporting design check: the Lead's role is forwarded so Event Service
        skips its assigned-coordinator check
    Double: Stub (get_user returns role Event Coordinator Lead), Mock
        (preview_event_details records the actor role passed to it)
    """
    # Arrange (Given)
    calls, state = downstream
    state["role"] = "Event Coordinator Lead"

    # Act (When)
    patch(client)

    # Assert (Then)
    assert calls["previewed"] == ["Event Coordinator Lead"]


def test_update_details_by_coordinator_leaves_assignment_check_to_event_service(client, downstream):
    """
    Summary: When User Service says the signed-in user is a plain Event
        Coordinator, the preview call to Event Service carries no actor role
        (None), leaving the assigned-coordinator check to Event Service.
    Supporting design check: only the Lead's role is forwarded; a coordinator's
        assignment is decided by Event Service
    Double: Stub (get_user returns role Event Coordinator), Mock
        (preview_event_details records the actor role passed to it)
    """
    # Arrange (Given)
    calls, _ = downstream

    # Act (When)
    patch(client)

    # Assert (Then)
    assert calls["previewed"] == [None]


@pytest.mark.parametrize("status", [400, 403, 404, 409], ids=["bad_request", "forbidden", "not_found", "conflict"])
def test_update_details_when_event_service_refuses_returns_its_status(client, downstream, monkeypatch, status):
    """
    Summary: When preview_event_details raises a 400, 403, 404 or 409 refusal
        from Event Service, PATCH /events/<id>/details answers that status with
        the same {"code": "X", "message": "No."} body.
    Supporting design check: Event Service refusals reach the coordinator
        unchanged
    Double: Stub (preview_event_details raises EventRejectedError with the
        parametrized status; get_user returns Event Coordinator)
    """
    # Arrange (Given)
    def refuse(*args, **kwargs):
        raise clients.EventRejectedError(status, {"code": "X", "message": "No."})

    monkeypatch.setattr(clients, "preview_event_details", refuse)

    # Act (When)
    response = patch(client)

    # Assert (Then)
    assert response.status_code == status
    assert response.json == {"code": "X", "message": "No."}


def test_update_details_when_save_needs_safety_recheck_returns_409(client, downstream, monkeypatch):
    """
    Summary: When save_event_details raises Event Service's 409
        SAFETY_RECHECK_REQUIRED refusal (after the preview and checks pass),
        PATCH /events/<id>/details answers 409 with that code.
    Supporting design check: Event Service's safety re-check refusal on save
        reaches the coordinator unchanged
    Double: Stub (save_event_details raises EventRejectedError 409
        SAFETY_RECHECK_REQUIRED; preview is low impact; get_user returns Event
        Coordinator)
    """
    # Arrange (Given)
    def gate(*args, **kwargs):
        raise clients.EventRejectedError(409, {"code": "SAFETY_RECHECK_REQUIRED"})

    monkeypatch.setattr(clients, "save_event_details", gate)

    # Act (When)
    response = patch(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_RECHECK_REQUIRED"


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamTimeout, 504), (clients.DownstreamError, 502)],
    ids=["timeout", "downstream_error"],
)
def test_update_details_when_arrangements_unreadable_refuses_change(client, downstream, monkeypatch, error, status):
    """
    Summary: With preferredStartDate reported as high impact, a timeout (504)
        or downstream error (502) raised by the arrangement check makes PATCH
        /events/<id>/details answer that status with a message containing
        "Nothing was changed". The test does not assert that save was skipped.
    Supporting design check: an unreadable arrangement check fails closed with
        504/502 instead of saving
    Double: Stub (preview_event_details returns highImpactFields=
        ["preferredStartDate"]; find_conflicts raises DownstreamTimeout or
        DownstreamError; get_user returns Event Coordinator)
    """
    # Arrange (Given)
    _, state = downstream
    state["preview"] = preview(high=["preferredStartDate"])

    def unreadable(*args, **kwargs):
        raise error

    monkeypatch.setattr("app.checks.find_conflicts", unreadable)

    # Act (When)
    response = patch(client)

    # Assert (Then)
    assert response.status_code == status
    assert "Nothing was changed" in response.json["message"]


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"changes": {}},
        {"changes": {"expectedAttendance": 5}},
    ],
    ids=["no_body", "empty_object", "empty_changes", "bad_change"],
)
def test_update_details_with_malformed_body_returns_400(client, downstream, body):
    """
    Summary: PATCH /events/<id>/details with no body, an empty object, empty
        changes, or a non-text change value (expectedAttendance: 5) answers
        400.
    Supporting design check: changes must be a non-empty object of text values
    Double: Stub (get_user, preview and save stubbed by the downstream
        fixture); none is expected to be called, the body is refused first
    """
    # Arrange (Given): client, downstream, body, from fixtures

    # Act (When)
    response = client.patch(f"/events/{EVENT_ID}/details", json=body)

    # Assert (Then)
    assert response.status_code == 400


def test_update_details_with_non_json_body_returns_400(client):
    """
    Summary: PATCH /events/<id>/details with a plain-text body "x" answers
        400.
    Supporting design check: the body must be a JSON object
    Double: None (no downstream client reached; only the conftest Supabase
        signing-key stub is in place for the signed-in client)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.patch(f"/events/{EVENT_ID}/details", data="x")

    # Assert (Then)
    assert response.status_code == 400


def test_update_details_with_bad_event_id_returns_400(client):
    """
    Summary: PATCH /events/not-a-uuid/details with a valid body answers 400.
    Supporting design check: the event id must be a UUID
    Double: None (no downstream client reached; only the conftest Supabase
        signing-key stub is in place for the signed-in client)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.patch(
        "/events/not-a-uuid/details",
        json={"changes": {"eventName": "x"}},
    )

    # Assert (Then)
    assert response.status_code == 400


# --- app.clients wrappers ------------------------------------------------------


class Reply:
    def __init__(self, status=200, body=None, json_error=False):
        self.status_code = status
        self.is_success = 200 <= status < 300
        self._body = body
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError
        return self._body


@pytest.fixture
def send(monkeypatch):
    sent = []
    replies = []

    def fake(method, url, **kwargs):
        sent.append((method, url, kwargs))
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(httpx, "request", fake)
    return sent, replies


def test_downstream_call_when_timing_out_raises_timeout(send):
    """
    Summary: list_equipment raises DownstreamTimeout when httpx.request raises
        ReadTimeout.
    Supporting design check: a downstream timeout is reported as its own error
    Double: Stub (httpx.request raises ReadTimeout)
    """
    _, replies = send
    replies.append(httpx.ReadTimeout("slow"))
    with pytest.raises(clients.DownstreamTimeout):
        clients.list_equipment()


def test_downstream_call_when_transport_fails_raises_downstream_error(send):
    """
    Summary: list_equipment raises DownstreamError when httpx.request raises
        ConnectError.
    Supporting design check: a connection failure is reported as a downstream
        error
    Double: Stub (httpx.request raises ConnectError)
    """
    _, replies = send
    replies.append(httpx.ConnectError("down"))
    with pytest.raises(clients.DownstreamError):
        clients.list_equipment()


def test_downstream_call_when_server_errors_raises_downstream_error(send):
    """
    Summary: list_venues raises DownstreamError when the response status is
        500.
    Supporting design check: a downstream server error is reported as a
        downstream error
    Double: Stub (httpx.request returns 500 {})
    """
    _, replies = send
    replies.append(Reply(500, {}))
    with pytest.raises(clients.DownstreamError):
        clients.list_venues()


def test_get_user_returns_profile_or_raises_when_missing(send):
    """
    Summary: get_user("u1") returns the profile (role Event Coordinator Lead)
        from a 200 response; get_user("u2") raises UserNotFoundError on a 404.
    Supporting design check: a user's role is read from User Service and a
        missing user is reported
    Double: Stub (httpx.request returns 200 {"role": "Event Coordinator Lead"},
        then 404 {})
    """
    _, replies = send
    replies.extend([Reply(200, {"role": "Event Coordinator Lead"}), Reply(404, {})])
    assert clients.get_user("u1")["role"] == "Event Coordinator Lead"
    with pytest.raises(clients.UserNotFoundError):
        clients.get_user("u2")


def test_ac2_preview_details_sends_dry_run_with_internal_token(send, monkeypatch):
    """
    Summary: preview_event_details("e1", {"eventName": "x"}, "Event
        Coordinator Lead") sends PATCH /events/e1/details with body
        {"changes": ..., "dryRun": true, "actorRole": "Event Coordinator
        Lead"} and header X-Internal-Token "secret", so Event Service
        classifies the change without saving it.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (httpx.request returns 200 {"highImpactFields": []};
        INTERNAL_SERVICE_TOKEN set to "secret"), Mock (the recorded request's
        method, URL, body and headers are asserted)
    """
    sent, replies = send
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", "secret")
    replies.append(Reply(200, {"highImpactFields": []}))

    clients.preview_event_details("e1", {"eventName": "x"}, "Event Coordinator Lead")

    method, url, kwargs = sent[0]
    assert (method, url.endswith("/events/e1/details")) == ("PATCH", True)
    assert kwargs["json"] == {
        "changes": {"eventName": "x"},
        "dryRun": True,
        "actorRole": "Event Coordinator Lead",
    }
    assert kwargs["headers"] == {"X-Internal-Token": "secret"}


def test_ac1_ac4_save_details_sends_real_save_without_empty_role(send, monkeypatch):
    """
    Summary: save_event_details("e1", {"eventName": "x"}) with no
        INTERNAL_SERVICE_TOKEN sends body {"changes": ..., "dryRun": false}
        (no actorRole key), header X-Internal-Token "", and returns the
        event {"id": "e1"}.
    AC1: Given a field being updated is one of the low-impact fields (Event
        Name, Description, Purpose, Registration Needs), when the assigned
        Event Coordinator saves the change, then the update is applied and the
        system records the new information.
    AC4: Given a high-impact update passes validation with no contradiction
        found, then the update is applied and saved.
    Double: Stub (httpx.request returns 200 {"id": "e1"};
        INTERNAL_SERVICE_TOKEN set to None), Mock (the recorded request body
        and headers are asserted)
    """
    sent, replies = send
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", None)
    replies.append(Reply(200, {"id": "e1"}))

    assert clients.save_event_details("e1", {"eventName": "x"}) == {"id": "e1"}

    assert sent[0][2]["json"] == {"changes": {"eventName": "x"}, "dryRun": False}
    assert sent[0][2]["headers"] == {"X-Internal-Token": ""}


@pytest.mark.parametrize("status", [400, 403, 404, 409], ids=["bad_request", "forbidden", "not_found", "conflict"])
def test_event_client_when_refused_keeps_status_and_body(send, status):
    """
    Summary: save_event_details raises EventRejectedError carrying the same
        status (400, 403, 404 or 409) and body {"code": "X"} that Event Service
        answered with.
    Supporting design check: Event Service refusals of a save keep their status
        and body
    Double: Stub (httpx.request returns the parametrized status with body
        {"code": "X"})
    """
    _, replies = send
    replies.append(Reply(status, {"code": "X"}))
    with pytest.raises(clients.EventRejectedError) as raised:
        clients.save_event_details("e1", {"eventName": "x"})
    assert (raised.value.status, raised.value.body) == (status, {"code": "X"})


def test_event_client_when_refusal_unreadable_returns_empty_body(send):
    """
    Summary: save_event_details raises EventRejectedError with an empty body
        {} when Event Service answers 409 with a body that is not JSON.
    Supporting design check: an unreadable refusal body is passed on as empty
    Double: Stub (httpx.request returns 409 whose json() raises ValueError)
    """
    _, replies = send
    replies.append(Reply(409, json_error=True))
    with pytest.raises(clients.EventRejectedError) as raised:
        clients.save_event_details("e1", {"eventName": "x"})
    assert raised.value.body == {}


def test_ac2_overlapping_events_client_sends_the_time_window(send):
    """
    Summary: list_overlapping_events("s", "e", ("Approved", "Confirmed"), "e1")
        sends query params start=s, end=e, statuses="Approved,Confirmed" and
        excludeEventId=e1, and returns the "events" list from the response.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (httpx.request returns 200 {"events": [{"id": "o"}]}), Mock
        (the recorded request's query params are asserted)
    """
    sent, replies = send
    replies.append(Reply(200, {"events": [{"id": "o"}]}))

    assert clients.list_overlapping_events("s", "e", ("Approved", "Confirmed"), "e1") == [{"id": "o"}]

    assert sent[0][2]["params"] == {
        "start": "s",
        "end": "e",
        "statuses": "Approved,Confirmed",
        "excludeEventId": "e1",
    }


def test_list_clients_return_the_inner_list(send):
    """
    Summary: get_event_venue_bookings, list_venues, list_event_equipment_requests,
        list_approved_equipment_requests and list_equipment each return the
        list found under "bookings", "venues", "requests", "requests" and
        "equipment" in the response.
    Supporting design check: the arrangement reads unwrap the list from the
        response body
    Double: Stub (httpx.request returns five wrapped lists in call order)
    """
    _, replies = send
    replies.extend(
        [
            Reply(200, {"bookings": ["b"]}),
            Reply(200, {"venues": ["v"]}),
            Reply(200, {"requests": ["r"]}),
            Reply(200, {"requests": ["a"]}),
            Reply(200, {"equipment": ["q"]}),
        ]
    )
    assert clients.get_event_venue_bookings("e1") == ["b"]
    assert clients.list_venues() == ["v"]
    assert clients.list_event_equipment_requests("e1") == ["r"]
    assert clients.list_approved_equipment_requests(["o1", "o2"]) == ["a"]
    assert clients.list_equipment() == ["q"]


def test_equipment_requests_client_sends_callers_token(send):
    """
    Summary: Inside a request that carries an Authorization header,
        list_event_equipment_requests("e1") sends params eventId=e1 and
        list_approved_equipment_requests(["o1", "o2"]) sends params
        status=Approved, eventIds="o1,o2"; both forward the caller's
        Authorization header and no internal token.
    Supporting design check: equipment requests are read as the signed-in
        coordinator, not as a trusted service
    Double: Stub (httpx.request returns 200 {"requests": []} twice), Mock (the
        recorded requests' params and headers are asserted)
    """
    sent, replies = send
    replies.extend([Reply(200, {"requests": []}), Reply(200, {"requests": []})])

    with create_app().test_request_context(headers={"Authorization": "Bearer lead-token"}):
        clients.list_event_equipment_requests("e1")
        clients.list_approved_equipment_requests(["o1", "o2"])

    assert sent[0][2]["params"] == {"eventId": "e1"}
    assert sent[1][2]["params"] == {"status": "Approved", "eventIds": "o1,o2"}
    for _, _, kwargs in sent:
        assert kwargs["headers"] == {"Authorization": "Bearer lead-token"}
