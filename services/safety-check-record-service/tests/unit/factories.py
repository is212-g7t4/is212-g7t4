"""Shared helpers for Safety Check Record Service's unit tests."""
from datetime import UTC, datetime

EVENT_ID = "00000000-0000-0000-0000-000000000001"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
OFFICER_ID = "33333333-3333-4333-8333-333333333333"
RECORD_ID = "44444444-4444-4444-8444-444444444444"
NEXT_RECORD_ID = "55555555-5555-4555-8555-555555555555"


def record_row(
    round_number=1,
    status="Pending",
    safety_check_id=RECORD_ID,
    equipment_placement_notes=None,
    crowd_movement_notes=None,
    decided=False,
    remarks=None,
    withdrawn=False,
    withdrawal_reason=None,
    event_id=EVENT_ID,
):
    """A `public."SafetyCheck"` row as `RealDictCursor` would return it."""
    return {
        "safety_check_id": safety_check_id,
        "event_id": event_id,
        "round_number": round_number,
        "submitted_by": COORDINATOR_ID,
        "submitted_at": datetime(2026, 11, 1, 2, 30, tzinfo=UTC),
        "equipment_placement_notes": equipment_placement_notes,
        "crowd_movement_notes": crowd_movement_notes,
        "status": status,
        "decided_by": OFFICER_ID if decided else None,
        "decided_at": datetime(2026, 11, 2, 3, tzinfo=UTC) if decided else None,
        "remarks": (remarks or "Looks safe.") if decided else None,
        # SCRUM-153: set only on a round whose approval was withdrawn. The
        # decision fields above stay populated — that is AC3.
        "withdrawn_at": datetime(2026, 11, 3, 4, tzinfo=UTC) if withdrawn else None,
        "withdrawn_by": COORDINATOR_ID if withdrawn else None,
        "withdrawal_reason": (
            withdrawal_reason or "Date/time changed after safety approval."
        )
        if withdrawn
        else None,
    }
