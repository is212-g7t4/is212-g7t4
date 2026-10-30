"""Hand-written fakes for the downstream atomics (import as `from tests.unit.fakes import ...`)."""

from flask import g

USER = "ad3d6da3-7220-4f80-9157-2ee4abc0455c"
TARGET = "00000000-0000-4000-8000-0000000000a1"
OTHER = "00000000-0000-4000-8000-0000000000b2"
THIRD = "00000000-0000-4000-8000-0000000000c3"
MIC = "00000000-0000-4000-8000-00000000e001"
TABLE = "00000000-0000-4000-8000-00000000e002"
LAPTOP = "00000000-0000-4000-8000-00000000e003"
START, END = "2026-10-01T10:00:00", "2026-10-01T18:00:00"


def line(request_id, event_id, equipment_id, quantity, status="Pending"):
    return {"id": request_id, "eventId": event_id, "equipmentId": equipment_id, "quantityRequested": quantity,
            "technicalRequirements": "", "status": status, "reviewedBy": None}


def equipment(equipment_id, description, total, status="Available"):
    return {"id": equipment_id, "type": "Microphone", "description": description, "totalQuantity": total, "status": status,
            "location": "", "setupRequirements": ""}


class World:
    """In-memory stand-ins for Event, Equipment and Equipment Request Service."""

    def __init__(self):
        self.requests = []
        self.events = {TARGET: {"id": TARGET, "eventName": "Hackday", "status": "Under Review", "coordinatorId": None,
                                "startTime": START, "endTime": END}}
        self.coordinator_assignments = {}
        self.overlapping = []
        self.catalogue = [equipment(MIC, "Wireless mic", 10), equipment(TABLE, "Table", 50), equipment(LAPTOP, "Laptop", 8, "Unavailable")]
        self.calls = []
        self.safety_rounds = []

    def get_event_safety_checks(self, event_id):
        self.calls.append(("safety_checks", event_id))
        return self.safety_rounds

    def list_requests(self, status=None, event_ids=None):
        self.calls.append(("list_requests", status, event_ids))
        return [r for r in self.requests if (status is None or r["status"] == status) and (event_ids is None or r["eventId"] in event_ids)]

    def get_request(self, request_id):
        return next(r for r in self.requests if r["id"] == request_id)

    def review_request(self, request_id, status, rejection_reason=None):
        self.calls.append(("review_request", request_id, status))
        return {**self.get_request(request_id), "status": status, "reviewedBy": USER, "rejectionReason": rejection_reason}

    def review_event_requests(self, event_id, status, rejection_reason=None):
        self.calls.append(("review_event_requests", event_id, status))
        return [{**r, "status": status, "reviewedBy": USER, "rejectionReason": rejection_reason} for r in self.requests if r["eventId"] == event_id and r["status"] == "Pending"]

    def get_event_summaries(self, ids):
        return [self.events[i] for i in ids if i in self.events]

    def list_assigned_event_ids(self):
        coordinator_id = g.user_id  # Event Service reads the coordinator from the forwarded token.
        self.calls.append(("assigned_events", coordinator_id))
        return [event_id for event_id, assigned_id in self.coordinator_assignments.items() if assigned_id == coordinator_id]

    def list_assigned_events(self):
        return [self.events[event_id] for event_id in self.list_assigned_event_ids() if event_id in self.events]

    def create_event_requests(self, event_id, items):
        self.calls.append(("create_event_requests", event_id, items))
        return [{"id": f"new-{i}", "eventId": event_id, **item, "status": "Pending", "reviewedBy": None} for i, item in enumerate(items)]

    def get_overlapping_events(self, start, end, statuses, exclude_event_id):
        self.calls.append(("overlapping", start, end, tuple(statuses), exclude_event_id))
        return self.overlapping

    def list_equipment(self):
        return self.catalogue


class FakeResponse:
    def __init__(self, status=200, body=None, json_error=False):
        self.status_code, self._body, self._json_error = status, body, json_error
        self.is_success = 200 <= status < 300

    def json(self):
        if self._json_error:
            raise ValueError("not json")
        return self._body
