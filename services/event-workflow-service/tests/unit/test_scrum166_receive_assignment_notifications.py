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
- AC5 (re-saving the same coordinator creates no notifications): this worker
  only delivers jobs the owner queued. Whether an unchanged assignment queues a
  job is Event Service's decision (-> event-service
  test_scrum166_receive_assignment_notifications.py, "AC5 — No-op
  suppression").
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

def test_ac3_assignment_alert_uses_saved_facts_and_frozen_envelope():
    """
    Summary: dispatch_once on one claimed "assigned" job for Bob looks up the
        organiser's name, builds a draft with the message "You have been
        assigned to Community Workshop. Event Organiser: Synthetic Organiser.
        Proposed: 01 Mar 2030, 09:00 SGT – 01 Mar 2030, 17:00 SGT.", an
        event-details link and the saved details, freezes it before anything is
        published, then publishes the owner's frozen envelope (not the draft)
        and marks the job published.
    AC3: Assignment notifications include the event name, Event Organiser name,
        proposed event date/time, and a link to view the newly assigned event.
    Double: Stub (api.claim returns the assigned job; api.organiser_name
        returns "Synthetic Organiser"; api.freeze returns a different frozen
        envelope naming "Previously Frozen Organiser"), Mock (publish called
        once with the frozen envelope and not before freeze; organiser_name
        called with the organiser id; retry not called)
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

def test_ac4_removal_alert_names_event_and_has_no_link():
    """
    Summary: dispatch_once on one claimed "removed" job for Alice builds a draft
        with the message "You are no longer assigned to Community Workshop.
        Event Organiser: Synthetic Organiser. Proposed: 01 Mar 2030, 09:00 SGT
        – 01 Mar 2030, 17:00 SGT." and no destination link, freezes it before
        publishing, then publishes the owner's frozen envelope and marks the job
        published.
    AC4: Removal notifications include the event name, Event Organiser name,
        proposed event date/time, and a clear statement that the recipient is
        no longer assigned to the event.
    Double: Stub (api.claim returns the removed job; api.organiser_name
        returns "Synthetic Organiser"; api.freeze returns a different frozen
        envelope with destination None), Mock (publish called once with the
        frozen envelope and not before freeze; retry not called)
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

# AC1 — Initial assignment reaches the assigned coordinator

def test_ac1_initial_assignment_alert_goes_to_the_assigned_coordinator():
    """
    Summary: dispatch_once on one claimed "assigned" job for Bob publishes one
        event.coordinator-assigned envelope addressed to Bob (recipientId), with
        a message starting "You have been assigned to Community Workshop." and
        an event-details link, and marks the job published.
    AC1: Given the Lead Coordinator successfully assigns an Event Coordinator to
        an event that previously had no assigned coordinator, the assigned
        coordinator receives an in-app assignment notification.
    Double: Stub (api.claim returns the assigned job for Bob;
        api.organiser_name returns "Synthetic Organiser"; api.freeze echoes the
        draft), Mock (publish called once with the envelope; published called
        once; retry not called)
    """
    # Arrange (Given)
    job = make_job("assigned", BOB)
    api, publish = Mock(), Mock()
    api.claim.return_value = [job]
    api.organiser_name.return_value = "Synthetic Organiser"
    api.freeze.side_effect = lambda received, draft: draft

    # Act (When)
    count = dispatch_once(api, publish)

    # Assert (Then)
    assert count == 1
    envelope = publish.call_args.args[0]
    assert publish.call_count == 1
    assert envelope["type"] == "event.coordinator-assigned"
    assert envelope["recipientId"] == BOB
    assert envelope["message"].startswith("You have been assigned to Community Workshop.")
    assert envelope["destination"] == dict(kind="event-details", eventId=EVENT)
    api.published.assert_called_once_with(job)
    api.retry.assert_not_called()

# AC2 — Reassignment notifies both coordinators

def test_ac2_reassignment_notifies_new_coordinator_and_previous_coordinator():
    """
    Summary: dispatch_once on two claimed jobs from one reassignment, an
        "assigned" job for Bob and a "removed" job for Alice, returns 2 and
        publishes an event.coordinator-assigned envelope to Bob ("You have been
        assigned to ...") and an event.coordinator-removed envelope to Alice
        ("You are no longer assigned to ..."), marking both jobs published.
    AC2: Given the Lead Coordinator successfully reassigns an event from one
        coordinator to a different coordinator:
        1. The new coordinator receives an in-app notification that they have
        been assigned.
        2. The previous coordinator receives an in-app notification that they
        have been removed.
    Double: Stub (api.claim returns the assigned job for Bob and the removed job
        for Alice with different ids; api.organiser_name returns "Synthetic
        Organiser"; api.freeze echoes each draft), Mock (publish called twice;
        published called once per job; retry not called)
    """
    # Arrange (Given)
    assigned = {**make_job("assigned", BOB), "id": "40000000-0000-4000-8000-000000000001"}
    removed = {**make_job("removed", ALICE), "id": "40000000-0000-4000-8000-000000000002"}
    api, publish = Mock(), Mock()
    api.claim.return_value = [assigned, removed]
    api.organiser_name.return_value = "Synthetic Organiser"
    api.freeze.side_effect = lambda received, draft: draft

    # Act (When)
    count = dispatch_once(api, publish)

    # Assert (Then)
    assert count == 2
    to_new, to_previous = [call.args[0] for call in publish.call_args_list]
    assert (to_new["type"], to_new["recipientId"]) == ("event.coordinator-assigned", BOB)
    assert to_new["message"].startswith("You have been assigned to Community Workshop.")
    assert (to_previous["type"], to_previous["recipientId"]) == ("event.coordinator-removed", ALICE)
    assert to_previous["message"].startswith("You are no longer assigned to Community Workshop.")
    assert [call.args[0] for call in api.published.call_args_list] == [assigned, removed]
    api.retry.assert_not_called()

# Supporting design rule — distinguish repair holds from transient delivery failures

@pytest.mark.parametrize("failure", ["missing-id", "not-found", "invalid-name", "hold-failure"], ids=["missing_id", "not_found", "invalid_name", "hold_failure"])
def test_coordinator_alert_that_cannot_be_prepared_is_held(failure):
    """
    Summary: For an assigned-coordinator job whose organiser id is missing, or
        whose organiser lookup raises a 404 or a ValueError("Missing organiser
        name"), or whose hold call itself fails, dispatch_once holds the job
        once with "OrganiserNameUnavailable organiserId=<id>"; nothing is
        frozen, published, marked published or retried.
    Supporting design check: an alert that cannot be prepared is held for
        repair rather than sent incomplete or retried forever
    Double: Stub (api.claim returns the job; api.organiser_name raises the
        parametrized 404 / ValueError, or the organiser id is None; for the
        hold_failure case api.hold raises RuntimeError("owner unavailable")),
        Mock (hold called once; freeze, publish, published and retry not
        called)
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
    Summary: When the organiser lookup answers 503, dispatch_once records one
        retry with "HTTPStatusError"; the job is not held, frozen, published
        or marked published.
    Supporting design check: a temporary organiser lookup failure is retried,
        not held
    Double: Stub (api.claim returns the assigned job; api.organiser_name raises
        HTTPStatusError for a 503), Mock (retry called once; hold, freeze,
        publish and published not called)
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


