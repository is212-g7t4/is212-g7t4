"""
SCRUM-166: Receive assignment notifications

User Story
----------
As an Event Coordinator, I want to receive in-app notifications when I am
assigned to or removed from an event, so that I know which events I am
responsible for.

Acceptance Criteria
-------------------
AC1: Given the Lead Coordinator successfully assigns an Event Coordinator to an
     event that previously had no assigned coordinator, the assigned
     coordinator receives an in-app assignment notification.
AC2: Given the Lead Coordinator successfully reassigns an event from one
     coordinator to a different coordinator:
     1. The new coordinator receives an in-app notification that they have been
     assigned.
     2. The previous coordinator receives an in-app notification that they have
     been removed.
AC3: Assignment notifications include the event name, Event Organiser name,
     proposed event date/time, and a link to view the newly assigned event.
AC4: Removal notifications include the event name, Event Organiser name,
     proposed event date/time, and a clear statement that the recipient is no
     longer assigned to the event.
AC5: Saving an assignment without changing the assigned coordinator does not
     create new assignment or removal notifications.

Real
----
- The event-workflow notification workers: they claim jobs from the owning
  service's outbox over HTTP, look up current recipients and display facts, ask
  the owner to freeze the envelope, publish the frozen envelope to RabbitMQ and
  mark it published, retrying or holding on failure.
- Assertions are on the envelopes frozen and published, call order, and
  retry/hold decisions.

Doubled
-------
- Owner outbox and lookup HTTP (Event, User, Registration, Venue Availability):
  Stub (respx / monkeypatched httpx fixtures) - canned replies; requests
  inspected.
- RabbitMQ publisher (pika): Mock - publish arguments, confirms and persistence
  inspected.

Not proven
----------
- That the owner freezes the envelope in the same transaction as the change (->
  the owning service's notification tests and integration tests).
- That Notification Service stores and shows the inbox item (->
  notification-service consumer tests and frontend NotificationCenter tests).
"""

import httpx
import pytest
from unittest.mock import Mock
from app.dispatcher import dispatch_once

EVENT = "30000000-0000-4000-8000-000000000001"
ORGANISER = "10000000-0000-4000-8000-000000000001"
ALICE = "10000000-0000-4000-8000-000000000002"
BOB = "10000000-0000-4000-8000-000000000003"


def make_job(kind="assigned", recipient=BOB):
    return dict(id="40000000-0000-4000-8000-000000000001",
        type="event.coordinator-" + kind, envelope=None, leaseToken="lease",
        createdAt="2030-01-01T00:00:00+00:00", source=dict(eventId=EVENT,
        eventName="Community Workshop", organiserId=ORGANISER, recipientId=recipient,
        startDateTime="2030-03-01T01:00:00+00:00", endDateTime="2030-03-01T09:00:00+00:00"))


# AC3 — Assignment content and frozen publication

def test_assignment_alert_uses_saved_facts_and_frozen_envelope():
    """
    Summary: An assignment alert carries the saved event facts in the owner-frozen envelope.
    AC3: Assignment notifications include the event name, Event Organiser name,
        proposed event date/time, and a link to view the newly assigned event.
    Double: Stub (owner outbox), Mock (publish)
    """
    job = make_job()
    api = Mock()
    api.claim.return_value = [job]
    api.organiser_name.return_value = "Synthetic Organiser"
    frozen = dict(version=1, id=job["id"], type="event.coordinator-assigned", recipientId=BOB,
        createdAt="2030-01-01T00:00:00+00:00", destination=dict(kind="event-details", eventId=EVENT),
        details={**job["source"], "organiserName": "Previously Frozen Organiser"},
        message="You have been assigned to Community Workshop. Event Organiser: Previously Frozen Organiser. "
                "Proposed: 01 Mar 2030, 09:00 SGT – 01 Mar 2030, 17:00 SGT.")
    publish = Mock()
    def freeze_before_publish(job, draft):
        publish.assert_not_called()
        api.published.assert_not_called()
        return frozen
    api.freeze.side_effect = freeze_before_publish
    assert dispatch_once(api, publish) == 1
    api.organiser_name.assert_called_once_with(ORGANISER)
    draft = api.freeze.call_args.args[1]
    assert draft["message"] == ("You have been assigned to Community Workshop. "
        "Event Organiser: Synthetic Organiser. Proposed: 01 Mar 2030, 09:00 SGT – 01 Mar 2030, 17:00 SGT.")
    assert draft["details"] == {**job["source"], "organiserName": "Synthetic Organiser"}
    assert draft["recipientId"] == BOB
    assert draft["destination"] == dict(kind="event-details", eventId=EVENT)
    publish.assert_called_once_with(frozen)
    api.published.assert_called_once_with(job)
    api.retry.assert_not_called()

# AC4 — Removal content

def test_removal_alert_names_event_and_has_no_link():
    """
    Summary: A removal alert names the event, organiser and period, and links nowhere.
    AC4: Removal notifications include the event name, Event Organiser name,
        proposed event date/time, and a clear statement that the recipient is
        no longer assigned to the event.
    Double: Stub (owner outbox), Mock (publish)
    """
    job = make_job("removed", ALICE)
    api = Mock()
    api.claim.return_value = [job]
    api.organiser_name.return_value = "Synthetic Organiser"
    frozen = dict(version=1, id=job["id"], type="event.coordinator-removed", recipientId=ALICE,
        createdAt="2030-01-01T00:00:00+00:00", destination=None,
        details={**job["source"], "organiserName": "Previously Frozen Organiser"},
        message="You are no longer assigned to Community Workshop. Event Organiser: Previously Frozen Organiser. "
                "Proposed: 01 Mar 2030, 09:00 SGT – 01 Mar 2030, 17:00 SGT.")
    def freeze_before_publish(job, draft):
        publish.assert_not_called()
        api.published.assert_not_called()
        return frozen
    api.freeze.side_effect = freeze_before_publish
    publish = Mock()
    assert dispatch_once(api, publish) == 1
    publish.assert_called_once_with(frozen)
    envelope = api.freeze.call_args.args[1]
    assert envelope != frozen
    assert envelope["recipientId"] == ALICE
    assert envelope["message"] == ("You are no longer assigned to Community Workshop. "
        "Event Organiser: Synthetic Organiser. Proposed: 01 Mar 2030, 09:00 SGT – 01 Mar 2030, 17:00 SGT.")
    assert envelope["destination"] is None
    assert envelope["details"] == {**job["source"], "organiserName": "Synthetic Organiser"}
    api.published.assert_called_once_with(job)
    api.retry.assert_not_called()

# Supporting design rule — distinguish repair holds from transient delivery failures

@pytest.mark.parametrize("failure", ["missing-id", "not-found", "invalid-name", "hold-failure"], ids=["missing_id", "not_found", "invalid_name", "hold_failure"])
def test_coordinator_alert_that_cannot_be_prepared_is_held(failure):
    """
    Summary: An alert that cannot be prepared is held rather than sent incomplete.
    AC3: Assignment notifications include the event name, Event Organiser name,
        proposed event date/time, and a link to view the newly assigned event.
    AC4: Removal notifications include the event name, Event Organiser name,
        proposed event date/time, and a clear statement that the recipient is
        no longer assigned to the event.
    Double: Stub (lookup or hold fails), Mock (no publish)
    """
    job = make_job()
    api, publish = Mock(), Mock()
    api.claim.return_value = [job]
    if failure == "missing-id":
        job["source"]["organiserId"] = None
    elif failure == "not-found":
        response = httpx.Response(404, request=httpx.Request("GET", "https://user.test/users/absent"))
        api.organiser_name.side_effect = httpx.HTTPStatusError("absent", request=response.request, response=response)
    else:
        api.organiser_name.side_effect = ValueError("Missing organiser name")
    if failure == "hold-failure":
        api.hold.side_effect = RuntimeError("owner unavailable")
    assert dispatch_once(api, publish) == 1
    api.hold.assert_called_once_with(job, f"OrganiserNameUnavailable organiserId={job['source']['organiserId']}")
    api.freeze.assert_not_called()
    publish.assert_not_called()
    api.published.assert_not_called()
    api.retry.assert_not_called()


def test_coordinator_alert_after_temporary_failure_retries():
    """
    Summary: A temporary organiser lookup failure is retried, not held.
    AC3: Assignment notifications include the event name, Event Organiser name,
        proposed event date/time, and a link to view the newly assigned event.
    Double: Stub (lookup fails once)
    """
    job = make_job()
    api, publish = Mock(), Mock()
    api.claim.return_value = [job]
    response = httpx.Response(503, request=httpx.Request("GET", "https://user.test/users/organiser"))
    api.organiser_name.side_effect = httpx.HTTPStatusError("offline", request=response.request, response=response)
    assert dispatch_once(api, publish) == 1
    api.retry.assert_called_once_with(job, "HTTPStatusError")
    api.hold.assert_not_called()
    api.freeze.assert_not_called()
    publish.assert_not_called()
    api.published.assert_not_called()


