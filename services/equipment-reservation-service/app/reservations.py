"""Orchestration: gathers event windows, equipment stock and approved requests from the atomics."""
from collections import defaultdict

from app import clients
from app.availability import RESERVING_EVENT_STATUSES, evaluate_request


class InsufficientStockError(Exception):
    pass


class RequestNotAllowedError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


OPEN_EVENT_STATUSES = ("Under Review", "Safety Changes Requested")


def _catalogue():
    return {item["id"]: item for item in clients.list_equipment()}


def _equipment_view(item):
    if item is None:
        return None
    return {key: item[key] for key in ("description", "type", "totalQuantity", "status")}


def _reserved_by_equipment(event):
    """Approved quantity held by this event and other eligible overlapping events."""
    start, end = event.get("startTime"), event.get("endTime")
    if not start or not end:
        return {}
    others = clients.get_overlapping_events(start, end, RESERVING_EVENT_STATUSES, event["id"])
    totals = defaultdict(int)
    for item in clients.list_requests("Approved", [other["id"] for other in others]):
        totals[item["equipmentId"]] += item["quantityRequested"]
    for item in clients.list_requests("Approved", [event["id"]]):
        totals[item["equipmentId"]] += item["quantityRequested"]
    return totals


def _evaluate_pending(event, pending, catalogue):
    reserved = _reserved_by_equipment(event) if pending else {}
    return {
        item["id"]: evaluate_request(item, catalogue.get(item["equipmentId"]), reserved.get(item["equipmentId"], 0))
        for item in pending
    }


def build_event_views(requests):
    """Group requests by event; only Pending lines carry an availability result."""
    event_ids = list(dict.fromkeys(item["eventId"] for item in requests))
    if not event_ids:
        return []
    summaries = {event["id"]: event for event in clients.get_event_summaries(event_ids)}
    catalogue = _catalogue()
    views = []
    for event_id in event_ids:
        event = summaries.get(event_id, {"id": event_id})
        items = [item for item in requests if item["eventId"] == event_id]
        pending = [item for item in items if item["status"] == "Pending"]
        availability = _evaluate_pending(event, pending, catalogue)
        safety_round = None
        if event.get("status") == "Safety Changes Requested":
            rounds = clients.get_event_safety_checks(event_id)
            latest = max(rounds, key=lambda review: review["roundNumber"], default=None)
            if latest and latest["status"] == "Changes Requested":
                safety_round = latest
        views.append({
            "eventId": event_id,
            "eventName": event.get("eventName") or "Unknown event",
            "eventStatus": event.get("status"),
            "coordinatorId": event.get("coordinatorId"),
            "startTime": event.get("startTime"),
            "endTime": event.get("endTime"),
            "requests": [
                {**item, "equipment": _equipment_view(catalogue.get(item["equipmentId"])),
                 "availability": availability.get(item["id"]), "safetyFeedback": _safety_feedback(safety_round, item["id"])}
                for item in items
            ],
        })
    return views


def _safety_feedback(safety_round, request_id):
    if safety_round is None:
        return None
    changes = [flag["changeRequired"] for flag in safety_round.get("flags", [])
        if flag["area"] == "technical arrangement"
        and flag.get("equipmentRequestId") in (None, request_id)]
    if not changes:
        return None
    return {"reason": safety_round.get("remarks"), "requestedChanges": changes}


def _ensure_sufficient(event_id, pending):
    event = next(iter(clients.get_event_summaries([event_id])), {"id": event_id})
    catalogue = _catalogue()
    # Every candidate for the same equipment competes for the same remaining pool.
    grouped = defaultdict(int)
    for item in pending:
        grouped[item["equipmentId"]] += item["quantityRequested"]
    availability = _evaluate_pending(event, pending, catalogue)
    short = [
        f"{(catalogue.get(item['equipmentId']) or {}).get('description', 'Unknown equipment')} "
        f"(requested {grouped[item['equipmentId']]}, available {availability[item['id']]['availableStock']})"
        for item in pending
        if grouped[item["equipmentId"]] > availability[item["id"]]["availableStock"]
    ]
    if short:
        raise InsufficientStockError("Cannot approve, insufficient stock: " + "; ".join(dict.fromkeys(short)) + ".")


def _approval_context(event_id, pending):
    """Include ALL eligible overlaps, even events with no Approved request yet.

    Holder summaries additionally let the owner distinguish released/non-overlapping
    Approved rows from missing context after waiting for its global approval lock.
    """
    holders = clients.list_requests()
    ids = list(dict.fromkeys([event_id, *(item["eventId"] for item in holders)]))
    events = {event["id"]: event for event in clients.get_event_summaries(ids)}
    target = events.get(event_id)
    if target is None or not target.get("startTime") or not target.get("endTime"):
        raise InsufficientStockError("Cannot approve without the event window. Refresh and try again.")
    for event in clients.get_overlapping_events(target["startTime"], target["endTime"], RESERVING_EVENT_STATUSES, event_id):
        events[event["id"]] = event
    return dict(eventId=event_id, requestIds=[item["id"] for item in pending],
                events=list(events.values()), equipment=clients.list_equipment())


def review_request(request_id, status, rejection_reason=None):
    if status == "Approved":
        request = clients.get_request(request_id)
        if request["status"] != "Pending":
            raise InsufficientStockError("Only Pending equipment requests can be reviewed.")
        _ensure_sufficient(request["eventId"], [request])
        checked = _approval_context(request["eventId"], [request])
        return clients.review_request(request_id, status, rejection_reason, approval_context=checked)
    return clients.review_request(request_id, status, rejection_reason)


def review_event(event_id, status, rejection_reason=None):
    if status == "Approved":
        pending = clients.list_requests("Pending", [event_id])
        if not pending:
            if not clients.list_requests(event_ids=[event_id]):
                raise RequestNotAllowedError(404, "No equipment requests found for this event.")
            raise InsufficientStockError("This event has no Pending equipment requests.")
        _ensure_sufficient(event_id, pending)
        checked = _approval_context(event_id, pending)
        return clients.review_event_requests(event_id, status, rejection_reason, approval_context=checked)
    return clients.review_event_requests(event_id, status, rejection_reason)


def create_requests(event_id, items):
    """Check assignment, event status and physical status, then save the lines as Pending.

    Stock over the event's window is not checked here; Technical Support checks it at review.
    """
    event = next((e for e in clients.list_assigned_events() if e["id"] == event_id), None)
    if event is None:
        raise RequestNotAllowedError(403, "You can only request equipment for events assigned to you.")
    if event.get("status") not in OPEN_EVENT_STATUSES:
        raise RequestNotAllowedError(409, "Equipment can only be requested while the event is Under Review or Safety Changes Requested.")
    catalogue = _catalogue()
    if any(item["equipmentId"] not in catalogue for item in items):
        raise RequestNotAllowedError(404, "An equipment item no longer exists in the catalogue.")
    unavailable = [
        catalogue[item["equipmentId"]]["description"]
        for item in items
        if catalogue[item["equipmentId"]].get("status") != "Available"
    ]
    if unavailable:
        raise RequestNotAllowedError(409, "This equipment is Unavailable: " + ", ".join(unavailable) + ".")
    return clients.create_event_requests(event_id, items)
