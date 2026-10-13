"""SCRUM-149: submit an event for its Operational Safety Check.

The workflow needs facts from three atomics and writes to two, so it is a
composite (AGENTS.md; `c4_diagram/export/c4.jpg`). The records themselves are
owned by `safety-check-record-service`, and the event's status by
`event-service`; neither of them knows about the other.
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

from flask import Blueprint, jsonify, request

from app import clients
from app.readiness import outstanding_arrangements

bp = Blueprint("safety_check_service", __name__)
logger = logging.getLogger(__name__)

NOTES_LIMIT = 2000
NOTE_FIELDS = (
    ("equipmentPlacementNotes", "Equipment placement notes"),
    ("crowdMovementNotes", "Expected crowd movement notes"),
)
PENDING_SAFETY_CHECK = "Pending Safety Check"
READY_STATUS = "Approved"
SAFETY_OFFICER = "Safety Officer"
CONFIRMED = "Confirmed"
SAFETY_APPROVED = "Safety Approved"

NOT_ASSIGNED = (
    "Only the event's assigned coordinator can submit it for a safety check."
)
NOT_SAFETY_OFFICER = (
    "Only a Safety Officer can approve an event's Operational Safety Check."
)
UNREADABLE_ARRANGEMENTS = "Unable to check the event's arrangements right now."
UNREADABLE_ROLE = "Unable to check the caller's role right now."


@bp.get("/health")
def health():
    return jsonify(status="ok")


@bp.post("/safety-checks")
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
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(message="Send a JSON object."), 400
    event_id = _uuid_or_none(data.get("eventId"))
    coordinator_id = _uuid_or_none(data.get("coordinatorId"))
    if not event_id or not coordinator_id:
        return jsonify(message="eventId and coordinatorId must be valid UUIDs."), 400
    notes, failure = _notes(data)
    if failure:
        return failure

    event, failure = _load_event(event_id, coordinator_id)
    if failure:
        return failure
    failure = _status_failure(event, event_id)
    if failure:
        return failure

    outstanding, failure = _outstanding(event_id, coordinator_id)
    if failure:
        return failure
    if outstanding:
        # AC2: blocked, and the outstanding arrangements are listed. Nothing
        # has been written at this point.
        return jsonify(
            code="ARRANGEMENTS_OUTSTANDING",
            message=(
                "This event can't be submitted for a safety check until every "
                "venue booking and equipment request is approved."
            ),
            outstanding=outstanding,
        ), 422

    try:
        record = clients.create_safety_check_record(event_id, coordinator_id, *notes)
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
            coordinator_id=coordinator_id,
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
    event_id = _uuid_or_none(data.get("eventId"))
    safety_officer_id = _uuid_or_none(data.get("safetyOfficerId"))
    if not event_id or not safety_officer_id:
        return jsonify(message="eventId and safetyOfficerId must be valid UUIDs."), 400
    remarks, failure = _approval_remarks(data)
    if failure:
        return failure

    failure = _check_safety_officer(safety_officer_id)
    if failure:
        return failure

    event, failure = _load_event_for_officer(event_id, safety_officer_id)
    if failure:
        return failure
    failure = _approve_status_failure(event)
    if failure:
        return failure

    open_round, failure = _open_round(event_id)
    if failure:
        return failure
    if not open_round:
        return jsonify(
            code="NO_OPEN_SAFETY_CHECK",
            message="This event has no safety check awaiting a decision.",
        ), 409

    try:
        decided = clients.decide_safety_check_record(
            open_round["id"], SAFETY_APPROVED, safety_officer_id, remarks
        )
    except clients.SafetyCheckAlreadyDecidedError as already:
        return jsonify(
            code="SAFETY_CHECK_ALREADY_DECIDED",
            message="This safety check has already been decided.",
            safetyCheck=already.existing,
        ), 409
    except clients.RecordNotFoundError:
        return jsonify(
            code="NO_OPEN_SAFETY_CHECK",
            message="This event has no safety check awaiting a decision.",
        ), 409
    except clients.DownstreamTimeout:
        return jsonify(message="Approving took too long. Please try again."), 504
    except clients.DownstreamError:
        return jsonify(message="Unable to approve this safety check right now."), 502

    try:
        updated = clients.set_event_safety_status(
            event_id,
            CONFIRMED,
            decided["id"],
            decided["roundNumber"],
            decided_by=safety_officer_id,
            remarks=remarks,
        )
    except Exception as error:  # noqa: BLE001 — every failure compensates alike
        _compensate_decision(decided["id"], decided["decidedAt"])
        return _approve_event_update_failure(error)

    return jsonify(safetyCheck=decided, event=updated), 200


@bp.get("/safety-checks/readiness")
def safety_check_readiness():
    """Can this event be submitted yet, and if not, what's outstanding (AC2)?

    The read-only half of `POST /safety-checks` — the same checks, the same
    readiness rule, no writes. The panel calls this on mount so a coordinator
    sees what is missing before clicking rather than after.
    """
    event_id = _uuid_or_none(request.args.get("eventId"))
    coordinator_id = _uuid_or_none(request.args.get("coordinatorId"))
    if not event_id or not coordinator_id:
        return jsonify(message="eventId and coordinatorId must be valid UUIDs."), 400

    event, failure = _load_event(event_id, coordinator_id)
    if failure:
        return failure

    open_round = None
    if event.get("status") == PENDING_SAFETY_CHECK:
        open_round, failure = _open_round(event_id)
        if failure:
            return failure

    outstanding, failure = _outstanding(event_id, coordinator_id)
    if failure:
        return failure

    return jsonify(
        ready=event.get("status") == READY_STATUS and not outstanding,
        eventStatus=event.get("status"),
        outstanding=outstanding,
        openSafetyCheck=open_round,
    ), 200


# --- Steps shared by both routes --------------------------------------------


def _load_event(event_id, coordinator_id):
    """Step 2: the event, and AC5 — Event Service answers 403 for a stranger."""
    try:
        return clients.get_event(event_id, coordinator_id), None
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


def _status_failure(event, event_id):
    """Step 3: only an `Approved` event is at the point of being submitted."""
    status = event.get("status")
    if status == READY_STATUS:
        return None
    if status == PENDING_SAFETY_CHECK:
        open_round, failure = _open_round(event_id)
        return failure or _already_pending(open_round)
    return (
        jsonify(
            code="EVENT_NOT_READY_FOR_SAFETY_CHECK",
            message=(
                "Only an Approved event can be submitted for a safety check "
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


def _outstanding(event_id, coordinator_id):
    """Step 4: read both sets of arrangements and apply the readiness rule.

    The two calls are independent, so this costs the slower one rather than
    both. A read that fails is never treated as "nothing outstanding" — an
    unreadable arrangement blocks the submission (fail closed).
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        bookings_call = pool.submit(clients.get_event_venue_bookings, event_id)
        requests_call = pool.submit(
            clients.get_event_equipment_requests, event_id, coordinator_id
        )
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


def _load_event_for_officer(event_id, safety_officer_id):
    """Step 3 of approve: read the event as the Safety Officer, not a coordinator."""
    try:
        return (
            clients.get_event(event_id, safety_officer_id, viewer_role=SAFETY_OFFICER),
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
    """Step 3's status check (AC3): only a 'Pending Safety Check' event qualifies."""
    status = event.get("status")
    if status == PENDING_SAFETY_CHECK:
        return None
    return (
        jsonify(
            code="EVENT_NOT_PENDING_SAFETY_CHECK",
            message=(
                "Only an event 'Pending Safety Check' can be approved "
                f"(current status: '{status}')."
            ),
            currentStatus=status,
        ),
        409,
    )


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


def _approve_event_update_failure(error):
    """Map Event Service's refusal of approve's step 6 after the decision has been undone."""
    if isinstance(error, clients.ServiceCredentialsError):
        return jsonify(message="Event Service refused this service's credentials."), 502
    if isinstance(error, clients.EventNotFoundError):
        return jsonify(message="Event request not found."), 404
    if isinstance(error, clients.EventTransitionError):
        return jsonify(
            code="EVENT_NOT_PENDING_SAFETY_CHECK",
            message=error.body.get("message")
            or "Only an event 'Pending Safety Check' can be approved.",
            currentStatus=error.body.get("currentStatus"),
        ), 409
    if isinstance(error, clients.DownstreamTimeout):
        return jsonify(message="Approving took too long. Please try again."), 504
    return jsonify(message="Unable to approve this safety check right now."), 502


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
