"""Synthetic SCRUM-49 outbox facts; no database, network or production formatter."""

from typing import Any

EVENT = "20000000-0000-4000-8000-000000000001"
REQUEST = "30000000-0000-4000-8000-000000000001"
COORDINATOR = "10000000-0000-4000-8000-000000000001"
ORGANISER = "10000000-0000-4000-8000-000000000002"
LEAD = "10000000-0000-4000-8000-000000000003"
OTHER_LEAD = "10000000-0000-4000-8000-000000000004"
OUTBOX = "http://event.test/internal/notification-outbox"
CONTEXT = f"http://event.test/internal/events/{EVENT}/notification-context"


def change_job(kind="event.change-request-submitted", role="coordinator", **facts) -> dict[str, Any]:
    """Return a fresh claimed intent matching Event outbox.serialize's wire shape."""
    return dict(
        id="40000000-0000-4000-8000-000000000001", type=kind,
        leaseToken="50000000-0000-4000-8000-000000000001",
        createdAt="2030-03-01T01:00:00+00:00", attempts=1, envelope=None,
        source=dict(eventId=EVENT, eventName="Workshop", recipientRole=role, **facts),
    )


def change_envelope(item, recipient, message):
    """Describe the expected public envelope, with independently supplied literal text."""
    return dict(
        version=1, id=item["id"], type=item["type"], createdAt=item["createdAt"],
        recipientId=recipient, message=message,
        details={**item["source"], "recipientId": recipient},
        destination=(dict(kind="change-request-review", eventId=EVENT, changeRequestId=REQUEST)
                     if item["type"] == "event.change-request-submitted" else
                     dict(kind="event-details", eventId=EVENT)),
    )
