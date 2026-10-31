"""SCRUM-151 Reject or Request Changes to Safety Arrangements: Safety Check Record Service integration tests.

Story:      As a Safety Officer, I want to reject an event's safety arrangement or request
            changes, stating which planning area must be revisited, so that the Event
            Coordinator knows exactly what to fix before the event can proceed.
Real:       Flask app and routes, token verification and the role check, validation,
            app/models.py SQL (the decision and its SafetyCheckFlag rows in one transaction,
            real foreign keys to VenueBooking and EquipmentRequest), postgres:17.6 with the full
            migration chain.
Doubled:    nothing (Safety Check Record Service makes no outbound calls).
Not proven: the event's status, equipment resets and released bookings (Event Service,
            Equipment Request, Venue Availability, driven by Safety Check Service); the
            confirmation step (frontend); Supabase sign-in itself (SCRUM-8).

AC1  Given an event is 'Pending Safety Check', when I request changes, then I must select at
     least one affected area (venue arrangement, technical/equipment arrangement, event details)
     and describe the change needed; otherwise the decision is not saved.
AC2  Not covered here: the event's status and the equipment request reset run in Event Service
     and Equipment Request Service.
AC3  Given an event is 'Pending Safety Check', when I reject it, then a reason is required and I
     must confirm the rejection before it is saved.
     Covered here: the reason. The confirmation is a frontend dialog.
AC4  Not covered here: 'Cancelled' and the block on further stages are Event Service rules.
AC5  Not covered here: releasing venue bookings and equipment runs in Venue Availability and
     Equipment Request Service.
AC6  Given either decision, then the safety check is recorded with the status 'Changes
     Requested' or 'Safety Rejected' respectively, together with my identity, the timestamp and
     the reason (plus the selected areas for a change request), and the original event
     information is retained.
     Covered here: the safety check record. The event row is never written by this service.
AC7  Given an event is not 'Pending Safety Check', then these actions are not available and an
     API call is rejected without changing the event.
     Covered here: the round-level half (an already-decided round is refused, unchanged).
"""

from datetime import timedelta

import pytest

from tests.integration.factories import (
    OFFICER_ID,
    UNKNOWN_ID,
    as_user,
    make_booking,
    make_equipment_request,
    make_event,
    make_people,
    make_round,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

OFFICER = as_user(OFFICER_ID)


@pytest.fixture(autouse=True)
def people(db):
    make_people(db)


def decide(client, safety_check_id, body):
    return client.patch(f"/safety-check-records/{safety_check_id}/decision", json=body, **OFFICER)


def changes(*flags, remarks="Please revise the layout."):
    return {"status": "Changes Requested", "remarks": remarks, "flags": list(flags)}


# AC1 ----

def test_ac1_a_change_request_without_any_area_is_not_saved(client, db):
    """Failure: no area selected, so the round stays Pending and no flag is written."""
    pending = make_round(db, make_event(db, status="Pending Safety Check"))
    before = db.round(pending)

    response = decide(client, pending, changes())

    assert response.status_code == 400
    assert db.round(pending) == before
    assert db.flag_count() == 0


def test_ac1_a_change_request_without_a_description_is_not_saved(client, db):
    """Failure: an area with blank change text is as good as no description."""
    pending = make_round(db, make_event(db, status="Pending Safety Check"))
    before = db.round(pending)

    response = decide(client, pending, changes({"area": "event details", "changeRequired": "  "}))

    assert response.status_code == 400
    assert db.round(pending) == before
    assert db.flag_count() == 0


# AC3 ----

def test_ac3_a_rejection_without_a_reason_is_not_saved(client, db):
    """Failure: the reason is required, so the round stays Pending."""
    pending = make_round(db, make_event(db, status="Pending Safety Check"))
    before = db.round(pending)

    response = decide(client, pending, {"status": "Safety Rejected", "remarks": " "})

    assert response.status_code == 400
    assert db.round(pending) == before


# AC6 ----

def test_ac6_a_change_request_is_recorded_with_its_areas(client, db):
    """Normal: status, officer, time and reason on the round, plus one flag row per area with real FKs."""
    event_id = make_event(db, status="Pending Safety Check")
    pending = make_round(db, event_id)
    booking_id = make_booking(db, event_id)
    equipment_request_id = make_equipment_request(db, event_id)

    response = decide(
        client,
        pending,
        changes(
            {"area": "venue arrangement", "changeRequired": "Widen the aisles.", "bookingId": booking_id},
            {"area": "technical arrangement", "changeRequired": "Tape down cables.",
             "equipmentRequestId": equipment_request_id},
            {"area": "event details", "changeRequired": "Lower the attendance."},
        ),
    )

    assert response.status_code == 200
    stored = db.round(pending)
    assert (stored["status"], str(stored["decided_by"]), stored["remarks"]) == (
        "Changes Requested", OFFICER_ID, "Please revise the layout.",
    )
    assert timedelta(0) <= db.now() - stored["decided_at"] < timedelta(minutes=1)
    assert [
        (flag["area"], flag["change_required"], flag["booking_id"] and str(flag["booking_id"]),
         flag["equip_request_id"] and str(flag["equip_request_id"]))
        for flag in db.flags(pending)
    ] == [
        ("event details", "Lower the attendance.", None, None),
        ("technical arrangement", "Tape down cables.", None, equipment_request_id),
        ("venue arrangement", "Widen the aisles.", booking_id, None),
    ]


def test_ac6_a_rejection_is_recorded_with_its_reason_and_no_areas(client, db):
    """Normal: 'Safety Rejected' with who, when and why; a rejection carries no flags."""
    pending = make_round(db, make_event(db, status="Pending Safety Check"))

    response = decide(client, pending, {"status": "Safety Rejected", "remarks": "Venue has no fire exit."})

    stored = db.round(pending)
    assert response.status_code == 200
    assert (stored["status"], str(stored["decided_by"]), stored["remarks"]) == (
        "Safety Rejected", OFFICER_ID, "Venue has no fire exit.",
    )
    assert stored["decided_at"] is not None
    assert db.flags(pending) == []


def test_ac6_a_change_request_whose_area_cannot_be_saved_leaves_the_round_undecided(client, db):
    """Failure: a flag naming a booking that doesn't exist fails its real FK, and the decision rolls back with it."""
    pending = make_round(db, make_event(db, status="Pending Safety Check"))
    before = db.round(pending)

    response = decide(
        client,
        pending,
        changes({"area": "venue arrangement", "changeRequired": "Widen the aisles.", "bookingId": UNKNOWN_ID}),
    )

    assert response.status_code >= 400
    assert db.round(pending) == before
    assert db.flag_count() == 0


def test_ac6_undoing_a_change_request_also_removes_its_areas(client, db):
    """Normal: the composite's compensation returns the round to Pending with no flags left behind."""
    pending = make_round(db, make_event(db, status="Pending Safety Check"))
    decided_at = decide(
        client, pending, changes({"area": "event details", "changeRequired": "Lower the attendance."})
    ).get_json()["decidedAt"]

    response = client.post(f"/safety-check-records/{pending}/reopen", json={"decidedAt": decided_at}, **OFFICER)

    assert response.status_code == 200
    assert db.round(pending)["status"] == "Pending"
    assert db.flag_count() == 0


# AC7 ----

def test_ac7_a_round_already_decided_cannot_be_rejected(client, db):
    """Conflict: rejecting an approved round is refused, and the approval and its flags are unchanged."""
    approved = make_round(db, make_event(db, status="Confirmed"), status="Safety Approved")
    before = db.round(approved)

    response = decide(client, approved, {"status": "Safety Rejected", "remarks": "Changed my mind."})

    assert response.status_code == 409
    assert db.round(approved) == before
    assert db.flag_count() == 0
