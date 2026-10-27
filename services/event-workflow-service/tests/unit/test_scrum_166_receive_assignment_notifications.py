"""SCRUM-166 — Receive assignment notifications.

As an Event Coordinator, I want to receive in-app notifications when I am assigned to or removed from an event, so that I know which events I am responsible for.

- **AC1:** Given the Lead Coordinator successfully assigns an Event Coordinator to an event that previously had no assigned coordinator, the assigned coordinator receives an in-app assignment notification.
- **AC2:** Given the Lead Coordinator successfully reassigns an event from one coordinator to a different coordinator:
  - The new coordinator receives an in-app notification that they have been assigned.
  - The previous coordinator receives an in-app notification that they have been removed.
- **AC3:** Assignment notifications include the event name, Event Organiser name, proposed event date/time, and a link to view the newly assigned event.
- **AC4:** Removal notifications include the event name, Event Organiser name, proposed event date/time, and a clear statement that the recipient is no longer assigned to the event.
- **AC5:** Saving an assignment without changing the assigned coordinator does not create new assignment or removal notifications.

AC = acceptance criterion; DR = supporting design rule.
AC1/AC2: not covered here as trigger/persistence; Event/Notification integration
story modules verify those boundaries. AC3/AC4: covered here as preparation and
frozen publication, with HTTP serialization in Workflow adapter integrations.
AC5: not covered here because Event suppresses unchanged saves; its unit and
integration story modules verify that guard.

Real: dispatcher orchestration. Doubled: owner/User APIs and publisher.
Not proven: HTTP serialization, database persistence or actual broker delivery.
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

def test_ac3_assignment_uses_saved_facts_and_owner_frozen_envelope():
    """Prepare assignment for the captured recipient, then publish the owner's frozen value.
    The message includes organiser and full proposed Singapore period and a safe event link.
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

def test_ac4_removal_names_event_organiser_period_and_has_no_link():
    """Prepare removal for the captured old recipient, not the current coordinator.
    The full proposed period remains visible without a destination that now denies access.
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

@pytest.mark.parametrize("failure", ["missing-id", "not-found", "invalid-name", "hold-failure"])
def test_dr_unpreparable_coordinator_delivery_is_held_without_publication(failure):
    """Unnameable organiser holds the intent; even failed hold cannot publish unsafe content."""
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


def test_dr_temporary_organiser_http_failure_retries_instead_of_holding():
    """A User 503 retries the captured job without freezing or publishing partial content."""
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


