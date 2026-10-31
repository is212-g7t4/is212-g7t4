"""SCRUM-149: submit an event for its Operational Safety Check.

The workflow needs facts from three atomics and writes to two, so it is a
composite (AGENTS.md; `c4_diagram/export/c4.png`). The records themselves are
owned by `safety-check-record-service`, and the event's status by
`event-service`; neither of them knows about the other.
"""
import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from flask import Blueprint, g, jsonify, request

from app import clients
from app.readiness import outstanding_arrangements

bp = Blueprint("safety_check_service", __name__)
logger = logging.getLogger(__name__)


class _RequestPool(ThreadPoolExecutor):
    """Worker threads run in this request's context, so they forward the caller's token (SCRUM-8)."""

    def submit(self, fn, /, *args, **kwargs):
        return super().submit(contextvars.copy_context().run, fn, *args, **kwargs)

# Event Service's API works in naive Singapore local time (its `SINGAPORE`),
# so a date is compared the same way on both sides of the call.
SINGAPORE = ZoneInfo("Asia/Singapore")

NOTES_LIMIT = 2000
NOTE_FIELDS = (
    ("equipmentPlacementNotes", "Equipment placement notes"),
    ("crowdMovementNotes", "Expected crowd movement notes"),
)
PENDING_SAFETY_CHECK = "Pending Safety Check"
READY_STATUS = "Approved"
SAFETY_OFFICER = "Safety Officer"
LEAD_ROLE = "Event Coordinator Lead"
CONFIRMED = "Confirmed"
SAFETY_APPROVED = "Safety Approved"
SAFETY_CHANGES_REQUESTED = "Safety Changes Requested"
CANCELLED = "Cancelled"
CHANGES_REQUESTED = "Changes Requested"
SAFETY_REJECTED = "Safety Rejected"
FLAG_AREAS = ("venue arrangement", "technical arrangement", "event details")
RELEASED_BOOKING_STATUSES = ("Cancelled", "Expired", "Rejected")

# SCRUM-153. These mirror `event-service/app/models.py` — there is no shared
# package by design (AGENTS.md), so they are copied, and Event Service stays
# the authority: the check below is an early, friendly one, and its gate on
# PATCH /events/<id>/details is what actually decides.
LOW_IMPACT_FIELDS = ("eventName", "description", "purpose", "registrationNeeds")
HIGH_IMPACT_FIELDS = (
    "preferredStartDate",
    "preferredEndDate",
    "expectedAttendance",
    "venueRequirements",
    "equipmentRequirements",
    "accessibilityNeeds",
)
EDITABLE_FIELDS = (*LOW_IMPACT_FIELDS, *HIGH_IMPACT_FIELDS)
FIELD_LABELS = {
    "preferredStartDate": "Date/time",
    "preferredEndDate": "Date/time",
    "expectedAttendance": "Expected attendance",
    "venueRequirements": "Venue requirements",
    "equipmentRequirements": "Equipment requirements",
    "accessibilityNeeds": "Accessibility needs",
    "eventName": "Event name",
    "description": "Description",
    "purpose": "Purpose",
    "registrationNeeds": "Registration needs",
}

NOT_ASSIGNED = (
    "Only the event's assigned coordinator can submit it for a safety check."
)
NOT_SAFETY_OFFICER = (
    "Only a Safety Officer can decide an event's Operational Safety Check."
)
UNREADABLE_ARRANGEMENTS = "Unable to check the event's arrangements right now."
COORDINATOR_ROLES = ("Event Coordinator", LEAD_ROLE)


def _cannot_modify(roles):
    """SCRUM-10: the 403 for a signed-in caller whose role may not change this information, else None.

    Runs first in the handler, so a refused change reads and writes nothing, here or downstream.
    A caller with no user passes and meets the handler's own sign-in check.
    """
    if g.user_id is None or g.role in roles:
        return None
    return jsonify(message="Your role cannot change this information."), 403


UNREADABLE_ROLE = "Unable to check the caller's role right now."
UNREADABLE_QUEUE = "Unable to load the safety check queue right now."
VENUE_CHANGE_TIMEOUT = "Updating the event's safety approval took too long. Please try again."
VENUE_CHANGE_FAILED = "Unable to update the event's safety approval right now."
QUEUE_WORKERS = 8


@bp.get("/health")
def health():
    return jsonify(status="ok")


@bp.get("/safety-checks/<uuid:event_id>/review")
def review_safety_check(event_id):
    """Read the complete safety context for a Safety Officer (SCRUM-163)."""
    safety_officer_id = g.user_id
    failure = _token_safety_officer()
    if failure:
        return failure

    event, failure = _load_event_for_officer(str(event_id))
    if failure:
        return failure
    if event.get("status") != PENDING_SAFETY_CHECK:
        return jsonify(
            code="EVENT_NOT_PENDING_SAFETY_CHECK",
            message="Only an event awaiting a safety decision can be reviewed.",
        ), 409

    try:
        with _RequestPool(max_workers=5) as pool:
            bookings_call = pool.submit(clients.get_event_venue_bookings, str(event_id))
            requests_call = pool.submit(clients.get_event_equipment_requests, str(event_id))
            rounds_call = pool.submit(clients.list_safety_check_records, str(event_id))
            venues_call = pool.submit(clients.list_venues)
            equipment_call = pool.submit(clients.list_equipment)
            bookings = bookings_call.result()
            requests = requests_call.result()
            rounds = rounds_call.result()
            venues = venues_call.result()
            equipment = equipment_call.result()
    except clients.DownstreamTimeout:
        return jsonify(message=UNREADABLE_ARRANGEMENTS), 504
    except Exception:  # noqa: BLE001 — never leak downstream URLs or error text
        return jsonify(message=UNREADABLE_ARRANGEMENTS), 502

    venue_by_id = {venue.get("id"): venue for venue in venues}
    equipment_by_id = {item.get("id"): item for item in equipment}
    expected_attendance = event.get("expectedAttendance")
    try:
        attendance_number = int(expected_attendance)
    except (TypeError, ValueError):
        attendance_number = None

    review_venues = []
    for booking in bookings:
        venue = venue_by_id.get(booking.get("venueId"), {})
        capacity = venue.get("capacity")
        review_venues.append({
            "bookingId": booking.get("id"),
            "venueId": booking.get("venueId"),
            "name": venue.get("name"),
            "expectedAttendance": expected_attendance,
            "capacity": capacity,
            "overCapacity": (
                attendance_number is not None
                and isinstance(capacity, int)
                and attendance_number > capacity
            ),
            "layout": ", ".join(venue.get("supportedLayouts") or []) or None,
            "emergencyAccess": venue.get("emergencyAccessDetails"),
            "accessibility": venue.get("accessibility"),
            "restrictions": venue.get("knownRestrictions"),
            "venueRequirements": booking.get("venueRequirements"),
            "status": booking.get("status"),
        })

    review_equipment = []
    for equipment_request in requests:
        item = equipment_by_id.get(equipment_request.get("equipmentId"), {})
        review_equipment.append({
            "requestId": equipment_request.get("id"),
            "name": item.get("type") or item.get("description"),
            "description": item.get("description"),
            "quantity": equipment_request.get("quantityRequested"),
            "technicalRequirements": equipment_request.get("technicalRequirements"),
            "status": equipment_request.get("status"),
        })

    current_round = next(
        (item for item in rounds if item.get("status") == "Pending"), None
    )
    if current_round is None:
        return jsonify(
            code="NO_OPEN_SAFETY_CHECK",
            message="No open safety check was found for this event.",
        ), 409

    history = sorted(
        (item for item in rounds if item.get("id") != current_round.get("id")),
        key=lambda item: item.get("roundNumber", 0),
    )
    return jsonify(
        event=event,
        safetyCheck=current_round,
        venues=review_venues,
        equipment=review_equipment,
        history=history,
    )


@bp.post("/safety-checks")
@bp.post("/safety-checks/resubmit")
def submit_safety_check():
    """Submit an `Approved` event for its Operational Safety Check.

    Body: `eventId`, `coordinatorId`, and the optional
    `equipmentPlacementNotes` / `crowdMovementNotes` (AC3).

    The order of the two writes matters. The record is created **first**,
    because the record service is the duplicate guard (AC4): two
    near-simultaneous submits can't both get past it to move the event. If the
    event update then fails, the round just created is deleted again — there is
    no distributed transaction, so this compensates by hand.
    """
    if (forbidden := _cannot_modify(COORDINATOR_ROLES)):
        return forbidden
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(message="Send a JSON object."), 400
    coordinator_id = g.user_id
    event_id = _uuid_or_none(data.get("eventId"))
    if not event_id:
        return jsonify(message="eventId must be a valid UUID."), 400
    notes, failure = _notes(data)
    if failure:
        return failure

    event, failure = _load_event(event_id)
    if failure:
        return failure
    resubmitting = request.path == "/safety-checks/resubmit"
    failure = _status_failure(event, event_id, resubmitting=resubmitting)
    if failure:
        return failure

    outstanding, failure = _outstanding(event_id)
    if failure:
        return failure
    if outstanding:
        # AC2: something is still pending, or no approved venue booking is
        # left, so submission is blocked and the outstanding arrangements are
        # listed. Rejected ones were already dropped by the rule. Nothing has
        # been written at this point.
        return jsonify(
            code="ARRANGEMENTS_OUTSTANDING",
            message=(
                "This event can't be submitted for a safety check until it has "
                "an approved venue booking and no venue booking or equipment "
                "request is still waiting for a decision."
            ),
            outstanding=outstanding,
        ), 422

    try:
        record = clients.create_safety_check_record(event_id, *notes)
    except clients.SafetyCheckAlreadyPendingError as open_round:
        # AC4's race: another submit opened the round between our status read
        # and this call.
        return _already_pending(open_round.existing)
    except clients.DownstreamTimeout:
        return jsonify(message="Submitting took too long. Please try again."), 504
    except clients.DownstreamError:
        return jsonify(message="Unable to submit for a safety check right now."), 502

    try:
        updated = clients.set_event_safety_status(
            event_id,
            PENDING_SAFETY_CHECK,
            record["id"],
            record["roundNumber"],
        )
    except Exception as error:  # noqa: BLE001 — every failure compensates alike
        _compensate(record["id"])
        return _event_update_failure(error, event_id)

    return jsonify(safetyCheck=record, event=updated), 201


@bp.post("/safety-checks/approve")
def approve_safety_check():
    """Approve an event's Operational Safety Check (SCRUM-150).

    Body: `eventId`, `safetyOfficerId`, optional `remarks` (AC2).

    Record first, then event, as submit does: the record service is the race
    guard (AC3) — if two Safety Officers click at once, only one decide can
    win the open round; the second gets `409` before the event is touched.
    If the event move then fails, the decision is undone, so the event never
    reads 'Pending Safety Check' with a decided round, nor 'Confirmed'
    without one.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(message="Send a JSON object."), 400
    safety_officer_id = g.user_id
    event_id = _uuid_or_none(data.get("eventId"))
    if not event_id:
        return jsonify(message="eventId must be a valid UUID."), 400
    remarks, failure = _approval_remarks(data)
    if failure:
        return failure

    decided, updated, failure = _decide(
        event_id, safety_officer_id, SAFETY_APPROVED, CONFIRMED, remarks, verb="approve"
    )
    if failure:
        return failure

    return jsonify(safetyCheck=decided, event=updated), 200


@bp.post("/safety-checks/request-changes")
def request_safety_changes():
    """Request changes to an event's safety arrangements (SCRUM-151 AC1, AC2, AC6).

    Body: `eventId`, `safetyOfficerId`, `reason`, `flags: [{area, changeRequired}]`.

    Shares every step with approve and reject (see `_decide`): only the
    record's decided status, the event's target status and the extra
    `areas` on the event-side history entry differ. Flagged active venue
    bookings and equipment records return to staff review. Unflagged
    arrangements and terminal booking history are retained unchanged.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(message="Send a JSON object."), 400
    safety_officer_id = g.user_id
    event_id = _uuid_or_none(data.get("eventId"))
    if not event_id:
        return jsonify(message="eventId must be a valid UUID."), 400
    reason, failure = _required_reason(data)
    if failure:
        return failure
    flags, areas, failure = _change_flags(data)
    if failure:
        return failure

    decided, updated, failure = _decide(
        event_id,
        safety_officer_id,
        CHANGES_REQUESTED,
        SAFETY_CHANGES_REQUESTED,
        reason,
        flags=flags,
        areas=areas,
        verb="request-changes",
    )
    if failure:
        return failure

    return jsonify(safetyCheck=decided, event=updated), 200


@bp.post("/safety-checks/reject")
def reject_safety_check():
    """Reject an event's Operational Safety Check (SCRUM-151 AC3, AC4, AC5, AC6).

    Body: `eventId`, `safetyOfficerId`, `reason`, `confirmed: true`.

    Shares every step up to the event move with approve and request-changes
    (see `_decide`). Once the event is definitely 'Cancelled', its venue
    bookings are released (AC5) — last, and only here, because cancelling a
    booking can't be undone the way the decision itself can be.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(message="Send a JSON object."), 400
    safety_officer_id = g.user_id
    event_id = _uuid_or_none(data.get("eventId"))
    if not event_id:
        return jsonify(message="eventId must be a valid UUID."), 400
    reason, failure = _required_reason(data)
    if failure:
        return failure
    if data.get("confirmed") is not True:
        return jsonify(
            code="REJECTION_NOT_CONFIRMED",
            message="Confirm the rejection before it can be saved.",
        ), 400

    decided, updated, failure = _decide(
        event_id, safety_officer_id, SAFETY_REJECTED, CANCELLED, reason, verb="reject"
    )
    if failure:
        return failure

    released, not_released = _release_venue_bookings(event_id)
    return jsonify(
        safetyCheck=decided,
        event=updated,
        release={
            "venueBookingsReleased": released,
            "venueBookingsNotReleased": not_released,
            "equipment": (
                "Released: equipment held by a Cancelled event no longer "
                "counts against availability."
            ),
        },
    ), 200


@bp.post("/safety-checks/recheck")
def recheck_safety():
    """Withdraw a safety approval after a high-impact change (SCRUM-153).

    Body: `eventId`, `coordinatorId`, `changes: {<EDITABLE_FIELDS>: text}` —
    the same `changes` the UI already sent to Event Service and got
    `409 SAFETY_RECHECK_REQUIRED` for, now confirmed by the coordinator.

    **Record first, then event**, as in SCRUM-149 to 151: the record service's
    row lock on the event's latest round is the race guard, so two concurrent
    re-checks can't both open round N+1 — the second gets
    `409 ROUND_NOT_APPROVED`. If the event write then fails, the withdrawal is
    undone, so the event never reads 'Confirmed' with its approval withdrawn,
    nor 'Pending Safety Check' with the old approval still standing.

    The withdrawal and the edit are deliberately one request: the event's
    details and its safety status must change together, or AC1's guarantee
    (never prepared on an outdated review) doesn't hold.
    """
    if (forbidden := _cannot_modify(COORDINATOR_ROLES)):
        return forbidden
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(message="Send a JSON object."), 400
    coordinator_id = g.user_id
    event_id = _uuid_or_none(data.get("eventId"))
    if not event_id:
        return jsonify(message="eventId must be a valid UUID."), 400
    changes, failure = _changes(data)
    if failure:
        return failure

    event, failure = _load_event(event_id)
    if failure:
        return failure
    if event.get("status") != CONFIRMED:
        return _recheck_not_needed(
            "Only a Confirmed event has a safety approval to withdraw "
            f"(current status: '{event.get('status')}').",
            event.get("status"),
        )
    high = [
        field
        for field in changes
        if field in HIGH_IMPACT_FIELDS
        and _normalised(field, changes[field]) != _normalised(field, event.get(field))
    ]
    if not high:
        # An early, friendly check only — Event Service decides for real under
        # its lock. Catching it here keeps a no-op edit from withdrawing an
        # approval and then having to be compensated back.
        return _recheck_not_needed(
            "None of these changes affects the event's safety review, so its "
            "approval stands. Save them as an ordinary edit.",
            event.get("status"),
        )

    latest_round, failure = _latest_round(event_id)
    if failure:
        return failure
    if not latest_round or latest_round.get("status") != SAFETY_APPROVED:
        return jsonify(
            code="NO_APPROVED_SAFETY_CHECK",
            message="This event has no approved safety check to withdraw.",
            safetyCheck=latest_round,
        ), 409

    reason = (
        f"{_sentence_list([FIELD_LABELS[field] for field in high])} changed "
        "after safety approval."
    )
    try:
        withdrawn, opened = clients.withdraw_safety_approval(latest_round["id"], reason)
    except clients.RoundNotApprovedError as refused:
        # The race's loser: another re-check withdrew this approval between
        # our read and this call. Nothing has been written by us.
        return jsonify(
            code=refused.code or "ROUND_NOT_APPROVED",
            message=(
                refused.body.get("message")
                or "This event's safety approval has already been withdrawn."
            ),
            safetyCheck=refused.body.get("safetyCheck"),
        ), 409
    except clients.RecordNotFoundError:
        return jsonify(
            code="NO_APPROVED_SAFETY_CHECK",
            message="This event has no approved safety check to withdraw.",
        ), 409
    except clients.DownstreamTimeout:
        return jsonify(message="The re-check took too long. Please try again."), 504
    except clients.DownstreamError:
        return jsonify(message="Unable to re-check this event's safety right now."), 502

    try:
        updated = clients.update_event_details(
            event_id,
            changes,
            {
                "withdrawnSafetyCheckId": withdrawn["id"],
                "safetyCheckId": opened["id"],
                "roundNumber": opened["roundNumber"],
            },
        )
    except Exception as error:  # noqa: BLE001 — every failure compensates alike
        _compensate_withdrawal(withdrawn["id"], opened["id"])
        return _recheck_event_update_failure(error)

    return jsonify(
        event=updated,
        safetyCheck=opened,
        withdrawnSafetyCheck=withdrawn,
        changedFields=high,
        reason=reason,
    ), 200


def _recheck_not_needed(message, current_status):
    return jsonify(
        code="RECHECK_NOT_NEEDED", message=message, currentStatus=current_status
    ), 409


def _latest_round(event_id):
    """The event's newest round — `list_rounds` returns them newest first."""
    try:
        rounds = clients.list_safety_check_records(event_id)
    except clients.DownstreamTimeout:
        return None, (jsonify(message=UNREADABLE_ARRANGEMENTS), 504)
    except clients.DownstreamError:
        return None, (jsonify(message=UNREADABLE_ARRANGEMENTS), 502)
    return (rounds[0] if rounds else None), None


def _compensate_withdrawal(withdrawn_id, opened_id):
    """Undo the withdrawal when the edit couldn't then be saved.

    If this also fails there is nothing left to try, so both ids go to the log
    at ERROR and the caller still gets the original error. The event then
    reads 'Confirmed' with its approval withdrawn and a round waiting, which
    the README says how to clear by hand.
    """
    try:
        clients.restore_safety_approval(withdrawn_id, opened_id)
    except Exception:  # noqa: BLE001 — the original error is what matters
        logger.error(
            "Could not restore safety approval %s (and remove the round %s it "
            "opened) after the event update failed; the event is left Confirmed "
            "with its approval withdrawn and must be fixed by hand.",
            withdrawn_id,
            opened_id,
        )


def _recheck_event_update_failure(error):
    """Map Event Service's refusal of the edit, after the withdrawal has been undone."""
    if isinstance(error, clients.ServiceCredentialsError):
        return jsonify(message="Event Service refused this service's credentials."), 502
    if isinstance(error, clients.EventNotAssignedError):
        # Reassigned between the read and the write.
        return jsonify(code="NOT_ASSIGNED_COORDINATOR", message=NOT_ASSIGNED), 403
    if isinstance(error, clients.EventNotFoundError):
        return jsonify(message="Event request not found."), 404
    if isinstance(error, clients.EventDetailsRejectedError):
        # Passed through as Event Service sent it: it is the authority on the
        # fields, the gate and the event's status, and its body already says
        # what the coordinator has to fix.
        return jsonify(error.body), error.status
    if isinstance(error, clients.DownstreamTimeout):
        return jsonify(message="The re-check took too long. Please try again."), 504
    return jsonify(message="Unable to re-check this event's safety right now."), 502


@bp.post("/safety-checks/withdraw-for-venue-change")
def withdraw_for_venue_change():
    """SCRUM-28 Part B: a venue booking of a Confirmed event is about to change.

    Body: `eventId`, `coordinatorId`, `bookingId`, `reason`. Called by Venue
    Booking Service **before** it edits or cancels the booking (Clarice,
    25 Oct): the approval was given for the old arrangement, so it is
    withdrawn and the event goes back to 'Approved'. Unlike SCRUM-153's
    re-check no round is opened — Venue Staff re-review the booking first,
    and the coordinator then resubmits through SCRUM-149.

    Record first, then event, as in `recheck_safety`: the record service's row
    lock is the race guard. If the event move fails, the withdrawal is undone.
    """
    if (forbidden := _cannot_modify(COORDINATOR_ROLES)):
        return forbidden
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(message="Send a JSON object."), 400
    coordinator_id = g.user_id
    event_id = _uuid_or_none(data.get("eventId"))
    booking_id = _uuid_or_none(data.get("bookingId"))
    if not event_id or not booking_id:
        return jsonify(message="eventId and bookingId must be valid UUIDs."), 400
    reason, failure = _required_reason(data)
    if failure:
        return failure

    event, failure = _load_event(event_id)
    if failure:
        return failure
    if event.get("status") != CONFIRMED:
        return jsonify(
            code="EVENT_NOT_CONFIRMED",
            message="Only a Confirmed event has a safety approval to withdraw.",
            currentStatus=event.get("status"),
        ), 409
    latest_round, failure = _latest_round(event_id)
    if failure:
        return failure
    if not latest_round or latest_round.get("status") != SAFETY_APPROVED:
        return jsonify(
            code="NO_APPROVED_SAFETY_CHECK",
            message="This event has no approved safety check to withdraw.",
            safetyCheck=latest_round,
        ), 409

    try:
        withdrawn = clients.withdraw_approval_without_next_round(latest_round["id"], reason)
    except clients.RoundNotApprovedError as refused:
        return jsonify(
            code=refused.code or "ROUND_NOT_APPROVED",
            message=(
                refused.body.get("message")
                or "This event's safety approval has already been withdrawn."
            ),
        ), 409
    except clients.RecordNotFoundError:
        return jsonify(
            code="NO_APPROVED_SAFETY_CHECK",
            message="This event has no approved safety check to withdraw.",
        ), 409
    except clients.DownstreamTimeout:
        return jsonify(message=VENUE_CHANGE_TIMEOUT), 504
    except clients.DownstreamError:
        return jsonify(message=VENUE_CHANGE_FAILED), 502

    try:
        updated = clients.set_event_venue_change_status(
            event_id, withdrawn["id"], withdrawn["roundNumber"], True, reason
        )
    except Exception as error:  # noqa: BLE001 — every failure compensates alike
        try:
            clients.restore_approval_without_next_round(withdrawn["id"])
        except Exception:  # noqa: BLE001 — the original error is what matters
            logger.error(
                "Could not restore safety approval %s after the event move failed; "
                "event %s is left Confirmed with its approval withdrawn and must be "
                "fixed by hand.",
                withdrawn["id"],
                event_id,
            )
        return _venue_change_event_failure(error)

    return jsonify(event=updated, withdrawnSafetyCheck=withdrawn, bookingId=booking_id), 200


@bp.post("/safety-checks/restore-after-venue-change")
def restore_after_venue_change():
    """SCRUM-28 Part B, compensation only: the booking change could not be saved.

    Body: `eventId`, `coordinatorId`, `withdrawnSafetyCheckId` — the round
    `withdraw-for-venue-change` returned. Venue Booking Service calls this when
    the edit or cancel it was about to make then failed, so the event's
    approval still describes its real arrangement.

    Record first, then event, so a failure part-way never leaves the event
    reading 'Confirmed' with no approval in force: at worst it stays
    'Approved' with its round approved again, and the coordinator resubmits.
    """
    if (forbidden := _cannot_modify(COORDINATOR_ROLES)):
        return forbidden
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(message="Send a JSON object."), 400
    coordinator_id = g.user_id
    event_id = _uuid_or_none(data.get("eventId"))
    withdrawn_id = _uuid_or_none(data.get("withdrawnSafetyCheckId"))
    if not event_id or not withdrawn_id:
        return jsonify(message="eventId and withdrawnSafetyCheckId must be valid UUIDs."), 400

    event, failure = _load_event(event_id)
    if failure:
        return failure
    if event.get("status") != READY_STATUS:
        return jsonify(
            code="EVENT_NOT_WITHDRAWN",
            message="Only an event sent back to Approved by a venue change can be restored.",
            currentStatus=event.get("status"),
        ), 409

    try:
        restored = clients.restore_approval_without_next_round(withdrawn_id)
    except clients.RecordNotFoundError:
        return jsonify(message="Safety check not found."), 404
    except clients.RoundNotApprovedError as refused:
        return jsonify(
            code=refused.code or "NOT_RESTORABLE",
            message=refused.body.get("message") or "This withdrawal can no longer be undone.",
        ), 409
    except clients.DownstreamTimeout:
        return jsonify(message=VENUE_CHANGE_TIMEOUT), 504
    except clients.DownstreamError:
        return jsonify(message=VENUE_CHANGE_FAILED), 502

    try:
        updated = clients.set_event_venue_change_status(
            event_id, withdrawn_id, restored["roundNumber"], False
        )
    except Exception as error:  # noqa: BLE001 — reported, nothing left to undo
        logger.error(
            "Restored safety approval %s but could not move event %s back to "
            "Confirmed; it is left Approved and the coordinator must resubmit it.",
            withdrawn_id,
            event_id,
        )
        return _venue_change_event_failure(error)

    return jsonify(event=updated, safetyCheck=restored), 200


def _venue_change_event_failure(error):
    """Map Event Service's refusal of a venue-change status move."""
    if isinstance(error, clients.ServiceCredentialsError):
        return jsonify(message="Event Service refused this service's credentials."), 502
    if isinstance(error, clients.EventNotAssignedError):
        return jsonify(code="NOT_ASSIGNED_COORDINATOR", message=NOT_ASSIGNED), 403
    if isinstance(error, clients.EventNotFoundError):
        return jsonify(message="Event request not found."), 404
    if isinstance(error, clients.EventTransitionError):
        return jsonify(error.body), 409
    if isinstance(error, clients.DownstreamTimeout):
        return jsonify(message=VENUE_CHANGE_TIMEOUT), 504
    return jsonify(message=VENUE_CHANGE_FAILED), 502


def _decide(
    event_id,
    safety_officer_id,
    record_status,
    event_status,
    remarks,
    flags=None,
    areas=None,
    verb="decide",
):
    """Steps shared by approve, request-changes and reject (SCRUM-150, SCRUM-151).

    Technical flags select only affected Approved equipment requests for reset;
    targeted membership is checked against all event requests before eligibility.
    Pending and Rejected requests are not sent for reset.

    Role check -> load the event as the officer -> check it's 'Pending
    Safety Check' (AC7) -> decide the open round (the race guard) -> move
    the event, undoing the decision if that fails. Returns
    `(decided, updated, None)` on success, or `(None, None, failure)` where
    `failure` is the `(response, status)` tuple a route should return as is.
    """
    failure = _check_safety_officer(safety_officer_id)
    if failure:
        return None, None, failure

    event, failure = _load_event_for_officer(event_id)
    if failure:
        return None, None, failure
    failure = _approve_status_failure(event)
    if failure:
        return None, None, failure

    open_round, failure = _open_round(event_id)
    if failure:
        return None, None, failure
    if not open_round:
        return None, None, (
            jsonify(
                code="NO_OPEN_SAFETY_CHECK",
                message="This event has no safety check awaiting a decision.",
            ),
            409,
        )

    attendee_venue = None
    if event_status == CONFIRMED:
        for entry in reversed(event.get("actionHistory", [])):
            if entry.get("status") == CONFIRMED:
                break
            if "venueName" in entry.get("attendeeBaseline", {}):
                try:
                    attendee_venue = clients.attendee_venue_name(event_id)
                except (clients.DownstreamTimeout, clients.DownstreamError) as error:
                    return None, None, _decide_failure(error, verb)
                break

    booking_ids = []
    venue_flags = [flag for flag in flags or [] if flag["area"] == "venue arrangement"]
    if venue_flags:
        try:
            bookings = clients.get_event_venue_bookings(event_id)
        except (clients.DownstreamTimeout, clients.DownstreamError) as error:
            return None, None, _decide_failure(error, verb)
        available_ids = {item["id"] for item in bookings}
        targeted_ids = {flag.get("bookingId") for flag in venue_flags}
        if None not in targeted_ids and not targeted_ids.issubset(available_ids):
            return None, None, (jsonify(message="Flagged bookings must belong to this event."), 400)
        booking_ids = [item["id"] for item in bookings
            if item["status"] in ("Approved", "Pending", "Pending Review")
            and (None in targeted_ids or item["id"] in targeted_ids)]

    equipment_ids = []
    technical_flags = [flag for flag in flags or [] if flag["area"] == "technical arrangement"]
    if technical_flags:
        try:
            equipment = clients.get_event_equipment_requests(event_id)
        except (clients.DownstreamTimeout, clients.DownstreamError) as error:
            return None, None, _decide_failure(error, verb)
        available_ids = {item["id"] for item in equipment}
        targeted_ids = {flag.get("equipmentRequestId") for flag in technical_flags}
        if None in targeted_ids:
            equipment_ids = [item["id"] for item in equipment if item["status"] == "Approved"]
        elif not targeted_ids.issubset(available_ids):
            return None, None, (jsonify(message="Flagged equipment requests must belong to this event."), 400)
        else:
            equipment_ids = sorted(item["id"] for item in equipment
                if item["status"] == "Approved" and item["id"] in targeted_ids)

    try:
        decided = clients.decide_safety_check_record(
            open_round["id"], record_status, remarks, flags or []
        )
    except clients.SafetyCheckAlreadyDecidedError as already:
        return None, None, (
            jsonify(
                code="SAFETY_CHECK_ALREADY_DECIDED",
                message="This safety check has already been decided.",
                safetyCheck=already.existing,
            ),
            409,
        )
    except clients.RecordNotFoundError:
        return None, None, (
            jsonify(
                code="NO_OPEN_SAFETY_CHECK",
                message="This event has no safety check awaiting a decision.",
            ),
            409,
        )
    except (clients.DownstreamTimeout, clients.DownstreamError) as error:
        # The decide call may have actually gone through and only the
        # response was lost (a read timeout, a dropped connection) — check
        # before reporting failure. Otherwise a retry finds no 'Pending'
        # round left and gets stuck on NO_OPEN_SAFETY_CHECK forever.
        decided = _find_decided_round(event_id, open_round["id"], record_status)
        if decided is None:
            return None, None, _decide_failure(error, verb)

    if booking_ids:
        try:
            clients.reset_venue_safety_bookings(event_id, booking_ids)
        except (clients.DownstreamTimeout, clients.DownstreamError) as error:
            _compensate_decision(decided["id"], decided["decidedAt"])
            return None, None, _decide_failure(error, verb)

    if equipment_ids:
        try:
            clients.reset_equipment_safety_requests(event_id, equipment_ids)
        except (clients.DownstreamTimeout, clients.DownstreamError) as error:
            _compensate_decision(decided["id"], decided["decidedAt"])
            return None, None, _decide_failure(error, verb)

    try:
        updated = clients.set_event_safety_status(
            event_id,
            event_status,
            decided["id"],
            decided["roundNumber"],
            remarks=remarks,
            areas=areas,
            **({"attendee_venue": attendee_venue} if attendee_venue is not None else {}),
        )
    except (clients.DownstreamTimeout, clients.DownstreamError) as error:
        # Same reconciliation as above, one step later: Event Service may
        # have actually moved the event and only the response was lost.
        # Don't undo a decision that already succeeded end to end.
        event_after, _lookup_failure = _load_event_for_officer(event_id)
        if event_after and event_after.get("status") == event_status:
            return decided, event_after, None
        _compensate_decision(decided["id"], decided["decidedAt"])
        return None, None, _decide_failure(error, verb)
    except Exception as error:  # noqa: BLE001 — every other failure compensates alike
        _compensate_decision(decided["id"], decided["decidedAt"])
        return None, None, _approve_event_update_failure(error, verb)

    return decided, updated, None


def _release_venue_bookings(event_id):
    """AC5: release every live booking once the event is definitely 'Cancelled'.

    A booking already 'Cancelled', 'Expired' or 'Rejected' already blocks
    nothing, so it's left as is — its status stays accurate history. A
    cancel that fails is reported in `venueBookingsNotReleased` and logged
    at ERROR; the decision itself still stands, since the event really is
    cancelled (the README has the by-hand `curl` to clear it).
    """
    try:
        bookings = clients.get_event_venue_bookings(event_id)
    except (clients.DownstreamTimeout, clients.DownstreamError):
        logger.error(
            "Could not list venue bookings for event %s to release them "
            "after a safety rejection; they must be cancelled by hand.",
            event_id,
        )
        return [], []

    released = []
    not_released = []
    for booking in bookings:
        if booking.get("status") in RELEASED_BOOKING_STATUSES:
            continue
        booking_id = booking.get("id")
        try:
            clients.cancel_venue_booking(booking_id, event_id)
            released.append(booking_id)
        except Exception:  # noqa: BLE001 — the decision still stands
            not_released.append(booking_id)
            logger.error(
                "Could not release venue booking %s for event %s after a "
                "safety rejection; it must be cancelled by hand.",
                booking_id,
                event_id,
            )
    return released, not_released


@bp.get("/safety-checks/resubmit/readiness")
def safety_resubmission_readiness():
    coordinator_id = g.user_id
    event_id = _uuid_or_none(request.args.get("eventId"))
    if not event_id:
        return jsonify(message="eventId must be a valid UUID."), 400
    event, failure = _load_event(event_id)
    if failure:
        return failure
    outstanding, failure = _outstanding(event_id)
    if failure:
        return failure
    return jsonify(
        ready=event.get("status") == SAFETY_CHANGES_REQUESTED and not outstanding,
        eventStatus=event.get("status"),
        outstanding=outstanding,
    ), 200


@bp.get("/safety-checks/feedback")
def safety_check_feedback():
    coordinator_id = g.user_id
    event_id = _uuid_or_none(request.args.get("eventId"))
    if not event_id:
        return jsonify(message="eventId must be a valid UUID."), 400

    _, failure = _load_event_for_viewer(event_id)
    if failure:
        return failure

    try:
        rounds = clients.list_safety_check_records(event_id)
    except clients.DownstreamTimeout:
        return jsonify(message="Unable to load safety feedback right now."), 504
    except clients.DownstreamError:
        return jsonify(message="Unable to load safety feedback right now."), 502
    return jsonify(safetyChecks=rounds), 200


@bp.get("/safety-checks/readiness")
def safety_check_readiness():
    """Can this event be submitted yet, and if not, what's outstanding (AC2)?

    The read-only half of `POST /safety-checks` — the same checks, the same
    readiness rule, no writes. The panel calls this on mount so a coordinator
    sees what is missing before clicking rather than after.
    """
    coordinator_id = g.user_id
    event_id = _uuid_or_none(request.args.get("eventId"))
    if not event_id:
        return jsonify(message="eventId must be a valid UUID."), 400

    event, failure = _load_event(event_id)
    if failure:
        return failure

    open_round = None
    if event.get("status") == PENDING_SAFETY_CHECK:
        open_round, failure = _open_round(event_id)
        if failure:
            return failure

    outstanding, failure = _outstanding(event_id)
    if failure:
        return failure

    return jsonify(
        ready=event.get("status") == READY_STATUS and not outstanding,
        eventStatus=event.get("status"),
        outstanding=outstanding,
        openSafetyCheck=open_round,
    ), 200


@bp.get("/safety-checks/queue")
def safety_check_queue():
    """SCRUM-162: the events awaiting an Operational Safety Check, nearest first.

    Query: `safetyOfficerId`. Only events 'Pending Safety Check' are listed
    (AC1) — so a decided event drops out as soon as its status moves (AC4).
    Each entry carries the event's name, date/time, venues and expected
    attendance, plus the open round's submission time (AC2) and whether it
    is a resubmission, i.e. not the first round (AC3).

    Read-only, and fails closed like the rest of this service: if any part
    can't be read the whole queue is a 502/504, never a partial list that
    silently omits an event.
    """
    safety_officer_id = g.user_id
    failure = _token_safety_officer()
    if failure:
        return failure

    try:
        with _RequestPool(max_workers=QUEUE_WORKERS) as pool:
            events_call = pool.submit(
                clients.list_events_by_status,
                PENDING_SAFETY_CHECK,
                SAFETY_OFFICER,
            )
            venues_call = pool.submit(clients.list_venues)
            events = events_call.result()
            venue_names = {venue["id"]: venue["name"] for venue in venues_call.result()}
            # Each event needs its open round and its bookings; they're all
            # independent, so the queue costs the slowest read, not the sum.
            calls = [
                (
                    found,
                    pool.submit(
                        clients.list_safety_check_records, found["id"], "Pending"
                    ),
                    pool.submit(clients.get_event_venue_bookings, found["id"]),
                )
                for found in events
            ]
            details = [
                (found, rounds_call.result(), bookings_call.result())
                for found, rounds_call, bookings_call in calls
            ]
    except clients.DownstreamTimeout:
        return jsonify(message=UNREADABLE_QUEUE), 504
    except Exception:  # noqa: BLE001 — don't leak the URL or error text
        return jsonify(message=UNREADABLE_QUEUE), 502

    queue = []
    for found, rounds, bookings in details:
        if not rounds:
            # Out of step: the event says it's waiting but no round is open,
            # so there is nothing a Safety Officer could decide. Leave it
            # out rather than show a row with no submission date.
            logger.warning(
                "Event %s is 'Pending Safety Check' but has no open safety "
                "check round; left out of the queue.",
                found["id"],
            )
            continue
        queue.append(_queue_entry(found, rounds[0], bookings, venue_names))

    # AC2: nearest event date first. Event Service already returns its list
    # in this order, but the contract belongs here; an undated event goes last.
    queue.sort(
        key=lambda entry: (
            not entry["preferredStartDate"],
            entry["preferredStartDate"],
            entry["eventId"],
        )
    )
    return jsonify(events=queue), 200


def _queue_entry(event, open_round, bookings, venue_names):
    """One queue row: the event, its live venues and its open round."""
    venues = []
    seen = set()
    for booking in bookings:
        venue_id = booking.get("venueId")
        if booking.get("status") in RELEASED_BOOKING_STATUSES or venue_id in seen:
            continue
        seen.add(venue_id)
        venues.append({"id": venue_id, "name": venue_names.get(venue_id) or "Unknown venue"})
    return {
        "eventId": event["id"],
        "eventName": event.get("eventName") or "",
        "preferredStartDate": event.get("preferredStartDate") or "",
        "preferredEndDate": event.get("preferredEndDate") or "",
        "expectedAttendance": event.get("expectedAttendance") or "",
        "venues": venues,
        "safetyCheckId": open_round["id"],
        "submittedAt": open_round.get("submittedAt"),
        "roundNumber": open_round["roundNumber"],
        "resubmission": open_round["roundNumber"] > 1,
    }


# --- Steps shared by both routes --------------------------------------------


def _load_event(event_id):
    """Step 2: the event, and AC5 — Event Service answers 403 for a stranger."""
    try:
        return clients.get_event(event_id), None
    except clients.EventNotFoundError:
        return None, (jsonify(message="Event request not found."), 404)
    except clients.EventNotAssignedError:
        return None, (
            jsonify(code="NOT_ASSIGNED_COORDINATOR", message=NOT_ASSIGNED),
            403,
        )
    except clients.DownstreamTimeout:
        return None, (jsonify(message=UNREADABLE_ARRANGEMENTS), 504)
    except clients.DownstreamError:
        return None, (jsonify(message=UNREADABLE_ARRANGEMENTS), 502)


def _status_failure(event, event_id, resubmitting=False):
    """Step 3: only an `Approved` event is at the point of being submitted."""
    status = event.get("status")
    if status == (SAFETY_CHANGES_REQUESTED if resubmitting else READY_STATUS):
        return None
    if status == PENDING_SAFETY_CHECK:
        open_round, failure = _open_round(event_id)
        return failure or _already_pending(open_round)
    return (
        jsonify(
            code="EVENT_NOT_READY_FOR_SAFETY_CHECK",
            message=(
                ("Only a Safety Changes Requested event can be resubmitted for a safety check "
                 if resubmitting else "Only an Approved event can be submitted for a safety check ")
                +
                f"(current status: '{status}')."
            ),
            currentStatus=status,
        ),
        409,
    )


def _open_round(event_id):
    try:
        rounds = clients.list_safety_check_records(event_id, status="Pending")
    except clients.DownstreamTimeout:
        return None, (jsonify(message=UNREADABLE_ARRANGEMENTS), 504)
    except clients.DownstreamError:
        return None, (jsonify(message=UNREADABLE_ARRANGEMENTS), 502)
    return (rounds[0] if rounds else None), None


def _already_pending(open_round):
    """AC4: say so, and say when, rather than silently doing nothing."""
    submitted_at = (open_round or {}).get("submittedAt")
    message = "This event is already waiting for its safety check."
    if submitted_at:
        message = f"{message[:-1]}. It was submitted on {submitted_at}."
    return (
        jsonify(
            code="SAFETY_CHECK_ALREADY_PENDING",
            message=message,
            safetyCheck=open_round,
        ),
        409,
    )


def _outstanding(event_id):
    """Step 4: read both sets of arrangements and apply the readiness rule.

    The two calls are independent, so this costs the slower one rather than
    both. A read that fails is never treated as "nothing outstanding" — an
    unreadable arrangement blocks the submission (fail closed).
    """
    with _RequestPool(max_workers=2) as pool:
        bookings_call = pool.submit(clients.get_event_venue_bookings, event_id)
        requests_call = pool.submit(clients.get_event_equipment_requests, event_id)
        try:
            bookings, requests = bookings_call.result(), requests_call.result()
        except clients.DownstreamTimeout:
            return None, (jsonify(message=UNREADABLE_ARRANGEMENTS), 504)
        except Exception:  # noqa: BLE001 — don't leak the URL or error text
            return None, (jsonify(message=UNREADABLE_ARRANGEMENTS), 502)
    return outstanding_arrangements(bookings, requests), None


def _compensate(safety_check_id):
    """Undo the round we created when the event couldn't be moved.

    If this delete also fails there is nothing left to try, so the id goes to
    the log at ERROR and the caller still gets the original error. The event
    then reads `Approved` while the next submit gets `ALREADY_PENDING` — the
    README says how to clear that.
    """
    try:
        clients.delete_safety_check_record(safety_check_id)
    except Exception:  # noqa: BLE001 — the original error is what matters
        logger.error(
            "Could not remove safety check %s after the event status update "
            "failed; it is left open and must be removed by hand.",
            safety_check_id,
        )


def _token_safety_officer():
    """SCRUM-9 read routes: the caller's role from the signed token, no User Service lookup."""
    if g.role != SAFETY_OFFICER:
        return jsonify(code="NOT_SAFETY_OFFICER", message=NOT_SAFETY_OFFICER), 403
    return None


def _load_event_for_viewer(event_id):
    """The event for someone reading its safety feedback: the assigned coordinator,
    the Lead, or a Safety Officer. Every other role is refused."""
    if g.role == "Event Coordinator":
        return _load_event(event_id)
    if g.role not in (LEAD_ROLE, SAFETY_OFFICER):
        return None, (jsonify(message="Your role cannot view safety feedback."), 403)
    try:
        return clients.get_event(event_id, viewer_role=g.role), None
    except clients.EventNotFoundError:
        return None, (jsonify(message="Event request not found."), 404)
    except clients.EventNotAssignedError:
        return None, (jsonify(message="Your role cannot view safety feedback."), 403)
    except clients.DownstreamTimeout:
        return None, (jsonify(message=UNREADABLE_ARRANGEMENTS), 504)
    except clients.DownstreamError:
        return None, (jsonify(message=UNREADABLE_ARRANGEMENTS), 502)


def _check_safety_officer(user_id):
    """Step 2 of approve: the caller's role, looked up rather than trusted."""
    try:
        found = clients.get_user(user_id)
    except clients.UserNotFoundError:
        return jsonify(code="NOT_SAFETY_OFFICER", message=NOT_SAFETY_OFFICER), 403
    except clients.DownstreamTimeout:
        return jsonify(message=UNREADABLE_ROLE), 504
    except clients.DownstreamError:
        return jsonify(message=UNREADABLE_ROLE), 502
    if found.get("role") != SAFETY_OFFICER:
        return jsonify(code="NOT_SAFETY_OFFICER", message=NOT_SAFETY_OFFICER), 403
    return None


def _load_event_for_officer(event_id):
    """Step 3 of approve: read the event as the Safety Officer, not a coordinator."""
    try:
        return (
            clients.get_event(event_id, viewer_role=SAFETY_OFFICER),
            None,
        )
    except (clients.EventNotFoundError, clients.EventNotAssignedError):
        # EventNotAssignedError shouldn't occur here since viewerRole is
        # always sent, but if Event Service ever refused it anyway, there is
        # nothing more specific to tell this caller.
        return None, (jsonify(message="Event request not found."), 404)
    except clients.DownstreamTimeout:
        return None, (jsonify(message=UNREADABLE_ARRANGEMENTS), 504)
    except clients.DownstreamError:
        return None, (jsonify(message=UNREADABLE_ARRANGEMENTS), 502)


def _approve_status_failure(event):
    """Step 3's status check (AC3/AC7): only a 'Pending Safety Check' event qualifies."""
    status = event.get("status")
    if status == PENDING_SAFETY_CHECK:
        return None
    return (
        jsonify(
            code="EVENT_NOT_PENDING_SAFETY_CHECK",
            message=(
                "Only an event 'Pending Safety Check' can be decided "
                f"(current status: '{status}')."
            ),
            currentStatus=status,
        ),
        409,
    )


def _find_decided_round(event_id, safety_check_id, record_status):
    """Check whether a round was actually decided despite a lost response.

    Called only after decide_safety_check_record raises a timeout/transport
    error — ambiguous, since that can mean the record service never got the
    request or that it processed it and only the reply was lost. Returns the
    record if it is now decided as `record_status`, otherwise None (including
    when this lookup itself fails, which is just as ambiguous — the caller
    falls back to reporting the original failure).
    """
    try:
        rounds = clients.list_safety_check_records(event_id)
    except (clients.DownstreamTimeout, clients.DownstreamError):
        return None
    match = next((r for r in rounds if r.get("id") == safety_check_id), None)
    if match and match.get("status") == record_status:
        return match
    return None


# verb -> (present participle, infinitive used in "Unable to <x> this ..."),
# for the three decisions' downstream-failure messages.
VERB_FORMS = {
    "approve": ("Approving", "approve"),
    "request-changes": ("Requesting changes to", "request changes to"),
    "reject": ("Rejecting", "reject"),
}


def _decide_failure(error, verb):
    participle, infinitive = VERB_FORMS[verb]
    if isinstance(error, clients.DownstreamTimeout):
        return jsonify(message=f"{participle} took too long. Please try again."), 504
    return jsonify(message=f"Unable to {infinitive} this safety check right now."), 502


def _compensate_decision(safety_check_id, decided_at):
    """Undo the decision we just made when the event couldn't then be moved.

    If this also fails there is nothing left to try, so the id goes to the
    log at ERROR and the caller still gets the original error. The README
    says how to clear that by hand.
    """
    try:
        clients.reopen_safety_check_record(safety_check_id, decided_at)
    except Exception:  # noqa: BLE001 — the original error is what matters
        logger.error(
            "Could not reopen safety check %s after the event status update "
            "failed; it is left decided and must be reopened by hand.",
            safety_check_id,
        )


EVENT_TRANSITION_FALLBACK_MESSAGE = {
    "approve": "Only an event 'Pending Safety Check' can be approved.",
    "request-changes": "Only an event 'Pending Safety Check' can have changes requested.",
    "reject": "Only an event 'Pending Safety Check' can be rejected.",
}


def _approve_event_update_failure(error, verb):
    """Map Event Service's refusal of the event-move step after the decision has been undone.

    Only definite refusals reach here. Timeouts and transport errors are
    ambiguous — they may mean the event was moved and the reply lost — so
    `_decide` handles those itself, by reconciling before compensating.
    """
    if isinstance(error, clients.ServiceCredentialsError):
        return jsonify(message="Event Service refused this service's credentials."), 502
    if isinstance(error, clients.EventNotFoundError):
        return jsonify(message="Event request not found."), 404
    if isinstance(error, clients.EventTransitionError):
        return jsonify(
            code="EVENT_NOT_PENDING_SAFETY_CHECK",
            message=error.body.get("message") or EVENT_TRANSITION_FALLBACK_MESSAGE[verb],
            currentStatus=error.body.get("currentStatus"),
        ), 409
    return jsonify(message=f"Unable to {VERB_FORMS[verb][1]} this safety check right now."), 502


def _approval_remarks(data):
    """The Safety Officer's optional remarks (AC2). Blank is sent through as None."""
    value = data.get("remarks")
    if value is not None and not isinstance(value, str):
        return None, (jsonify(message="remarks must be text."), 400)
    if isinstance(value, str) and len(value) > NOTES_LIMIT:
        return None, (
            jsonify(message=f"remarks must be {NOTES_LIMIT} characters or fewer."),
            400,
        )
    cleaned = value.strip() or None if isinstance(value, str) else None
    return cleaned, None


def _event_update_failure(error, event_id):
    """Map Event Service's refusal of step 6 after the round has been undone."""
    if isinstance(error, clients.ServiceCredentialsError):
        # This service's own token was refused — a misconfiguration, not the
        # caller's fault, so it is not AC5's 403.
        return jsonify(message="Event Service refused this service's credentials."), 502
    if isinstance(error, clients.EventNotAssignedError):
        # Reassigned between step 2 and step 6 (AC5).
        return jsonify(code="NOT_ASSIGNED_COORDINATOR", message=NOT_ASSIGNED), 403
    if isinstance(error, clients.EventNotFoundError):
        return jsonify(message="Event request not found."), 404
    if isinstance(error, clients.EventTransitionError):
        if error.code == "SAFETY_CHECK_ALREADY_PENDING":
            open_round, failure = _open_round(event_id)
            return failure or _already_pending(open_round)
        return jsonify(
            code="EVENT_NOT_READY_FOR_SAFETY_CHECK",
            message=error.body.get("message")
            or "Only an Approved event can be submitted for a safety check.",
            currentStatus=error.body.get("currentStatus"),
        ), 409
    if isinstance(error, clients.DownstreamTimeout):
        return jsonify(message="Submitting took too long. Please try again."), 504
    return jsonify(message="Unable to submit for a safety check right now."), 502


# --- Input ------------------------------------------------------------------


def _uuid_or_none(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _notes(data):
    """The two optional note fields (AC3). Blank is stored as NULL downstream."""
    cleaned = []
    for key, label in NOTE_FIELDS:
        value = data.get(key)
        if value is not None and not isinstance(value, str):
            return None, (jsonify(message=f"{label} must be text."), 400)
        if isinstance(value, str) and len(value) > NOTES_LIMIT:
            return None, (
                jsonify(message=f"{label} must be {NOTES_LIMIT} characters or fewer."),
                400,
            )
        cleaned.append(value if isinstance(value, str) and value.strip() else None)
    return cleaned, None


def _changes(data):
    """The edited fields (SCRUM-153). Shape only — Event Service validates the values."""
    raw = data.get("changes")
    if not isinstance(raw, dict) or not raw:
        return None, (
            jsonify(message="changes must be a non-empty object of fields to update."),
            400,
        )
    unknown = sorted(set(raw) - set(EDITABLE_FIELDS))
    if unknown:
        return None, (
            jsonify(message=f"These fields can't be edited: {', '.join(unknown)}."),
            400,
        )
    if any(not isinstance(value, str) for value in raw.values()):
        return None, (jsonify(message="Every value in changes must be text."), 400)
    return raw, None


def _normalised(field, value):
    """`value` reduced to what "changed" means for its field.

    Mirrors `_normalised` in `event-service/app/models.py`: strings stripped,
    attendance compared as an int, dates as naive Singapore-local date-times.
    So resending the current value is not a change here either, and this
    service's early check agrees with the gate's verdict.
    """
    text = str(value or "").strip()
    if field == "expectedAttendance":
        return int(text) if text.isascii() and text.isdigit() else text
    if field in ("preferredStartDate", "preferredEndDate") and text:
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return text
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(SINGAPORE).replace(tzinfo=None)
        return parsed
    return text


def _sentence_list(labels):
    """"A", "A and B", "A, B and C" — deduplicated, so both dates read "Date/time" once."""
    distinct = list(dict.fromkeys(labels))
    if len(distinct) <= 1:
        return "".join(distinct)
    return f"{', '.join(distinct[:-1])} and {distinct[-1]}"


def _required_reason(data):
    """The reason for a change request or a rejection (AC1, AC3): required text."""
    value = data.get("reason")
    if not isinstance(value, str) or not value.strip():
        return None, (jsonify(message="reason is required."), 400)
    if len(value) > NOTES_LIMIT:
        return None, (
            jsonify(message=f"reason must be {NOTES_LIMIT} characters or fewer."),
            400,
        )
    return value.strip(), None


def _change_flags(data):
    """The affected areas and their change text for a change request (AC1).

    Returns `(flags, areas, failure)`, where `flags` is what Safety Check
    Record Service expects and `areas` is the plain list Event Service
    stores on the event's history entry — the same selection, two shapes.
    """
    raw = data.get("flags")
    if not isinstance(raw, list) or not raw:
        return None, None, (
            jsonify(message="Select at least one affected area."),
            400,
        )
    if len(raw) > 500 or (len(raw) > len(FLAG_AREAS) and not any(isinstance(item, dict) and (item.get("equipmentRequestId") or item.get("bookingId")) for item in raw)):
        return None, None, (
            jsonify(message="Each area may be selected at most once."),
            400,
        )

    seen = set()
    flags = []
    areas = []
    for item in raw:
        if not isinstance(item, dict):
            return None, None, (jsonify(message="Each flag must be an object."), 400)
        area = item.get("area")
        if area not in FLAG_AREAS:
            return None, None, (
                jsonify(message=f"area must be one of: {', '.join(FLAG_AREAS)}."),
                400,
            )
        equipment_request_id = item.get("equipmentRequestId")
        if equipment_request_id is not None:
            equipment_request_id = _uuid_or_none(equipment_request_id)
            if area != "technical arrangement" or not equipment_request_id:
                return None, None, (jsonify(message="equipmentRequestId must identify a technical arrangement request."), 400)
        booking_id = item.get("bookingId")
        if booking_id is not None:
            booking_id = _uuid_or_none(booking_id)
            if area != "venue arrangement" or not booking_id:
                return None, None, (jsonify(message="bookingId must identify a venue arrangement."), 400)
        target_id = equipment_request_id or booking_id
        identity = (area, target_id)
        if identity in seen or (area, None) in seen or (target_id is None and any(previous[0] == area for previous in seen)):
            return None, None, (
                jsonify(message="Each area may be selected at most once."),
                400,
            )
        seen.add(identity)
        change_required = item.get("changeRequired")
        if not isinstance(change_required, str) or not change_required.strip():
            return None, None, (
                jsonify(message="Describe the change needed for every selected area."),
                400,
            )
        if len(change_required) > NOTES_LIMIT:
            return None, None, (
                jsonify(
                    message=f"changeRequired must be {NOTES_LIMIT} characters or fewer."
                ),
                400,
            )
        flag = {"area": area, "changeRequired": change_required.strip()}
        if equipment_request_id:
            flag["equipmentRequestId"] = equipment_request_id
        if booking_id:
            flag["bookingId"] = booking_id
        flags.append(flag)
        if area not in areas:
            areas.append(area)
    return flags, areas, None
