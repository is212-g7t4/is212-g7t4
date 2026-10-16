"""# Test scope and acceptance mapping — SCRUM-171 integration

- **SCRUM-171 AC3 API support:** snapshot serializes complete SGT period and operational reason; legacy null remains supported. This is not rendered detail evidence.
- **Separately approved rule:** all rejected requests refuse edit/cancel/approve/reject.
- **Supporting concurrency infrastructure:** all booking writers acquire the shared transaction gate before row locks; mock SQL ordering is not a live deadlock proof.
- **Upstream integration regression:** `test_buffer_reconciliation_joins_shared_write_gate_before_row_locks` covers the newly merged buffer-flag writer joining the same protocol; no extra acceptance criterion.

## Case/group traceability

- `test_all_rejected_requests_are_immutable`: Separate approved immutability rule — all rejected write actions refused; no direct closure AC.
- `test_booking_writers_take_shared_transaction_gate_before_row_locks`: Supporting concurrency infrastructure — booking writers take advisory gate before row locks; no direct AC.
- `test_rejection_snapshot_is_exposed_in_singapore_with_legacy_null`: AC3 backend data support — snapshot full SGT period and operational reason serialized; legacy-null compatibility supporting, no visual proof.

## Existing test contract and detailed cases

SCRUM-171: closure rejection and immutable historical requests."""

import pytest
from datetime import datetime
from app import models
from tests.unit.factories import BOOKING_ID, EVENT_ID, USER_ID, VENUE_ID, booking_row


@pytest.mark.parametrize("action", ["edit", "cancel", "approve", "reject"])
def test_all_rejected_requests_are_immutable(setup, action):
    client, cursor = setup
    cursor.fetchone.return_value = booking_row(status="Rejected")
    payload = dict(
        eventId=EVENT_ID,
        venueId=VENUE_ID,
        requestedStartTime="2027-10-01T09:00",
        requestedEndTime="2027-10-01T12:00",
        requiredCapacity=80,
        venueRequirements="Projector",
        reviewedBy=USER_ID,
    )
    suffix = "" if action == "edit" else "/" + action
    response = client.patch(f"/venue-bookings/{BOOKING_ID}{suffix}", json=payload)
    assert response.status_code == 409
    assert response.json["code"] == "BOOKING_IMMUTABLE"
    assert not any(
        "UPDATE public" in call.args[0] for call in cursor.execute.call_args_list
    )


@pytest.mark.parametrize("action", ["create", "update", "cancel", "approve", "hold"])
def test_booking_writers_take_shared_transaction_gate_before_row_locks(setup, action):
    client, cursor = setup
    cursor.fetchone.return_value = booking_row()
    try:
        if action == "create":
            models.create_booking(
                "unused",
                EVENT_ID,
                VENUE_ID,
                datetime(2027, 1, 1),
                datetime(2027, 1, 2),
                10,
                "",
                USER_ID,
            )
        elif action == "update":
            models.update_booking(
                "unused",
                BOOKING_ID,
                EVENT_ID,
                VENUE_ID,
                datetime(2027, 1, 1),
                datetime(2027, 1, 2),
                10,
                "",
            )
        elif action == "cancel":
            models.cancel_booking("unused", BOOKING_ID, EVENT_ID)
        elif action == "approve":
            models.decide_booking("unused", BOOKING_ID, USER_ID, "Approved")
        else:
            models.create_hold("unused", VENUE_ID, datetime(2027, 1, 1), USER_ID)
    except models.HoldConflictError:
        pass
    assert "pg_advisory_xact_lock" in cursor.execute.call_args_list[0].args[0]


def test_rejection_snapshot_is_exposed_in_singapore_with_legacy_null():
    row = booking_row(status="Rejected")
    assert models.serialize(row)["closureRejection"] is None
    row.update(
        rejection_closure_id=BOOKING_ID,
        rejection_closure_start=datetime.fromisoformat("2027-01-01T00:00:00+00:00"),
        rejection_closure_end=datetime.fromisoformat("2027-01-02T00:00:00+00:00"),
        rejection_closure_reason="Maintenance\n<script>plain text</script>",
        rejected_at=datetime.fromisoformat("2026-10-16T00:00:00+00:00"),
    )
    result = models.serialize(models._localize(row))["closureRejection"]
    assert result == dict(
        closureId=BOOKING_ID,
        startDateTime="2027-01-01T08:00:00+08:00",
        endDateTime="2027-01-02T08:00:00+08:00",
        reason=row["rejection_closure_reason"],
        rejectedAt="2026-10-16T08:00:00+08:00",
    )


def test_buffer_reconciliation_joins_shared_write_gate_before_row_locks(setup):
    """## Supporting concurrency integration (no direct SCRUM-171 AC)

    Upstream buffer reconciliation also locks/updates multiple booking rows.
    It must take the same gate before row locks, so closure and reconciliation
    cannot acquire those rows in opposite orders. This checks the SQL protocol,
    not PostgreSQL deadlock execution or AC5 persistence.
    """
    client, cursor = setup
    cursor.fetchall.return_value = []
    models.reconcile_legacy_conflicts("mocked", VENUE_ID, 30, 45)
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert "pg_advisory_xact_lock(171, 1)" in statements[0]
    assert "FOR UPDATE" in statements[1]
