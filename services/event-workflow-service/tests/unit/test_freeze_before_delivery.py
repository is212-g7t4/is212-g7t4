"""SCRUM-45: As an Event Organiser, I want to receive an in-app notification
when the Lead Coordinator approves or rejects my event request, so that I know
the outcome and who is responsible for coordinating my event.
AC1–AC4/DR4: publication must follow successful durable preparation at Event's API.
"""
from unittest.mock import Mock

import pytest

from app.dispatcher import dispatch_once


@pytest.mark.parametrize("kind", ["event.approval", "event.rejection", "event.coordinator-assignment"])
@pytest.mark.parametrize("freeze_fails", [False, True], ids=["frozen-owner-result", "freeze-outage"])
def test_dispatch_waits_for_freeze_and_publishes_only_owner_returned_envelope(kind, freeze_fails):
    """AC1–AC4/DR4: observe ordered API/broker effects, fail freeze and require
    zero publication; successful freeze returns a distinct owner-authoritative
    envelope, proving the worker does not send its locally constructed draft.
    """
    source = dict(eventId="event", recipientId="organiser", eventName="Community Workshop",
                  decision="Approved" if kind == "event.approval" else "Rejected",
                  reason="Missing plan", coordinatorId="alice")
    job = dict(id="change", type=kind, source=source, envelope=None,
               createdAt="2026-10-21T00:00:00+00:00", leaseToken="lease")
    api = Mock()
    api.claim.return_value = [job]
    api.coordinator_name.return_value = "Alice Tan"
    effects = []
    owner_result = {"owner": "authoritative frozen result"}

    def freeze(received_job, draft):
        assert received_job == job
        assert effects == [], "Nothing may publish before Event confirms freeze"
        assert draft["type"] == kind
        effects.append("freeze")
        if freeze_fails:
            raise RuntimeError("Event unavailable")
        return owner_result

    def publish(envelope):
        assert effects == ["freeze"], "Freeze must finish before broker I/O"
        assert envelope == owner_result, "Publish owner result, not mutable local draft"
        effects.append("publish")

    def completed(received_job):
        assert received_job == job
        assert effects == ["freeze", "publish"]
        effects.append("published")

    api.published.side_effect = completed
    api.freeze.side_effect = freeze
    broker = Mock(side_effect=publish)
    assert dispatch_once(api, broker) == 1
    api.freeze.assert_called_once()
    if freeze_fails:
        broker.assert_not_called()
        api.published.assert_not_called()
        api.retry.assert_called_once_with(job, "RuntimeError")
    else:
        assert effects == ["freeze", "publish", "published"]
        broker.assert_called_once_with(owner_result)
        api.published.assert_called_once_with(job)
        api.retry.assert_not_called()
