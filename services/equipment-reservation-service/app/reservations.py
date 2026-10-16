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


OPEN_EVENT_STATUSES = ("Under Review",)


def _catalogue():
    return {item["id"]: item for item in clients.list_equipment()}


def _equipment_view(item):
    if item is None:
        return None
    return {key: item[key] for key in ("description", "type", "totalQuantity", "status")}


def _reserved_by_equipment(event, headers):
    """Quantity per equipment held by *other* non-rejected events overlapping this event's window."""
    start, end = event.get("startTime"), event.get("endTime")
    if not start or not end:
        return {}
    others = clients.get_overlapping_events(start, end, RESERVING_EVENT_STATUSES, event["id"])
    totals = defaultdict(int)
    for item in clients.list_requests(headers, "Approved", [other["id"] for other in others]):
        totals[item["equipmentId"]] += item["quantityRequested"]
    return totals


def _evaluate_pending(event, pending, catalogue, headers):
    reserved = _reserved_by_equipment(event, headers) if pending else {}
    return {
        item["id"]: evaluate_request(item, catalogue.get(item["equipmentId"]), reserved.get(item["equipmentId"], 0))
        for item in pending
    }


def build_event_views(requests, headers):
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
        availability = _evaluate_pending(event, pending, catalogue, headers)
        views.append({
            "eventId": event_id,
            "eventName": event.get("eventName") or "Unknown event",
            "eventStatus": event.get("status"),
            "coordinatorId": event.get("coordinatorId"),
            "startTime": event.get("startTime"),
            "endTime": event.get("endTime"),
            "requests": [
                {**item, "equipment": _equipment_view(catalogue.get(item["equipmentId"])), "availability": availability.get(item["id"])}
                for item in items
            ],
        })
    return views


def _ensure_sufficient(event_id, pending, headers):
    event = next(iter(clients.get_event_summaries([event_id])), {"id": event_id})
    catalogue = _catalogue()
    availability = _evaluate_pending(event, pending, catalogue, headers)
    short = [
        f"{(catalogue.get(item['equipmentId']) or {}).get('description', 'Unknown equipment')} "
        f"(requested {item['quantityRequested']}, available {availability[item['id']]['availableStock']})"
        for item in pending
        if availability[item["id"]]["isInsufficient"]
    ]
    if short:
        raise InsufficientStockError("Cannot approve, insufficient stock: " + "; ".join(short) + ".")


def review_request(headers, request_id, status):
    if status == "Approved":
        request = clients.get_request(headers, request_id)
        if request["status"] == "Pending":
            _ensure_sufficient(request["eventId"], [request], headers)
    return clients.review_request(headers, request_id, status)


def review_event(headers, event_id, status):
    if status == "Approved":
        pending = clients.list_requests(headers, "Pending", [event_id])
        if pending:
            _ensure_sufficient(event_id, pending, headers)
    return clients.review_event_requests(headers, event_id, status)


def create_requests(headers, coordinator_id, event_id, items):
    """Check assignment, event status and physical status, then save the lines as Pending.

    Stock over the event's window is not checked here; Technical Support checks it at review.
    """
    event = next((e for e in clients.list_assigned_events(coordinator_id) if e["id"] == event_id), None)
    if event is None:
        raise RequestNotAllowedError(403, "You can only request equipment for events assigned to you.")
    if event.get("status") not in OPEN_EVENT_STATUSES:
        raise RequestNotAllowedError(409, "Equipment can only be requested while the event is Under Review.")
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
    return clients.create_event_requests(headers, event_id, items)
