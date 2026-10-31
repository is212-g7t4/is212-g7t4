"""Commit-time stock enforcement using trusted composite inputs, never HTTP/foreign DBs."""
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from uuid import UUID

RESERVING_STATUSES = {
    "Approved", "Confirmed", "Under Review", "Clarification Requested",
    "Amendment Requested", "Pending Safety Check", "Safety Changes Requested",
}
RELEASED_STATUSES = {"Draft", "Submitted", "Rejected", "Cancelled"}
# One transaction-scoped key for every allocation-increasing review path.
APPROVAL_LOCK = 212607


class AllocationConflict(Exception):
    """Unavailable stock or incomplete/stale approval context; no rows are changed."""


def _uuid(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise AllocationConflict("Invalid approval identifier. Refresh and try again.") from None


def _window(event):
    try:
        values = [datetime.fromisoformat(event[key]) for key in ("startTime", "endTime")]
        start, end = [value if value.tzinfo else value.replace(tzinfo=timezone(timedelta(hours=8))) for value in values]
        if start >= end:
            raise ValueError
        return start, end
    except (ValueError, TypeError, KeyError):
        raise AllocationConflict("Missing or invalid event window. Refresh and try again.") from None


def context(payload, event_id=None, request_id=None):
    """Validate a full snapshot. Its trust comes from the existing internal-token + user guards."""
    value = payload.get("approvalContext")
    if not isinstance(value, dict):
        raise AllocationConflict("Approval stock and event context is required.")
    target = _uuid(value.get("eventId"))
    ids = value.get("requestIds")
    if not isinstance(ids, list):
        raise AllocationConflict("The exact checked requestIds are required.")
    ids = [_uuid(identifier) for identifier in ids]
    if len(set(ids)) != len(ids) or (event_id is not None and target != event_id) or (request_id is not None and ids != [request_id]):
        raise AllocationConflict("Approval selection does not match this decision.")
    events, equipment = value.get("events"), value.get("equipment")
    if not isinstance(events, list) or not isinstance(equipment, list):
        raise AllocationConflict("Complete event and stock context is required.")
    by_event, stock = {}, {}
    for event in events:
        if not isinstance(event, dict):
            raise AllocationConflict("Invalid event context.")
        identifier = _uuid(event.get("id"))
        status = event.get("status")
        if identifier in by_event or not isinstance(status, str) or status not in RESERVING_STATUSES | RELEASED_STATUSES:
            raise AllocationConflict("Unknown or duplicate event status/context.")
        by_event[identifier] = (status, _window(event))
    if target not in by_event or by_event[target][0] not in RESERVING_STATUSES:
        raise AllocationConflict("This event cannot reserve equipment.")
    for item in equipment:
        if not isinstance(item, dict):
            raise AllocationConflict("Invalid equipment context.")
        identifier = _uuid(item.get("id"))
        total = item.get("totalQuantity")
        if identifier in stock or isinstance(total, bool) or not isinstance(total, int) or total < 0 or item.get("status") not in ("Available", "Unavailable"):
            raise AllocationConflict("Invalid or unknown equipment stock/status.")
        stock[identifier] = total if item["status"] == "Available" else 0
    return dict(eventId=target, requestIds=ids, events=by_event, stock=stock)


def ensure_sufficient(checked, candidates, approved):
    """Use current owner rows, including own Approved lines and grouped candidates."""
    totals = defaultdict(int)
    target_start, target_end = checked["events"][checked["eventId"]][1]
    for row in candidates:
        totals[row["equipmentId"]] += row["quantityRequested"]
    for row in approved:
        event = checked["events"].get(row["eventId"])
        if event is None:
            raise AllocationConflict("An approved request has no event context. Refresh and try again.")
        status, (start, end) = event
        if status in RESERVING_STATUSES and start < target_end and end > target_start:
            totals[row["equipmentId"]] += row["quantityRequested"]
    for equipment_id, quantity in totals.items():
        if equipment_id not in checked["stock"] or quantity > checked["stock"][equipment_id]:
            raise AllocationConflict("Cannot approve, insufficient stock or missing equipment context.")
