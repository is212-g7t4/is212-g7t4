"""SCRUM-45 user story: As an Event Organiser, I want to receive an in-app
notification when the Lead Coordinator approves or rejects my event request,
so that I know the outcome and who is responsible for coordinating my event.
AC1/AC3 approval delivery and details; DR2 atomic intent; DR4 saved facts.
"""
from unittest.mock import Mock
from app.dispatcher import dispatch_once

SOURCE = dict(eventId="30000000-0000-0000-0000-000000000001",
              recipientId="10000000-0000-0000-0000-000000000001",
              eventName="Community Workshop", decision="Approved")
JOB = dict(id="20000000-0000-0000-0000-000000000001", source=SOURCE,
           envelope=None, createdAt="2026-10-21T00:00:00+00:00", leaseToken="lease")

def test_approval_worker_freezes_saved_facts_before_publish():
    """AC1/AC3/DR4: real dispatch boundary with external API/broker mocked;
    saved approval facts produce frozen message before confirmed publication.
    """
    api, publish = Mock(), Mock()
    api.claim.return_value = [JOB]
    api.freeze.side_effect = lambda job, envelope: envelope
    assert dispatch_once(api, publish) == 1
    expected = dict(version=1, id=JOB["id"], type="event.approval",
        recipientId=SOURCE["recipientId"], createdAt=JOB["createdAt"],
        message="Community Workshop was approved",
        destination=dict(kind="event-details", eventId=SOURCE["eventId"]), details=SOURCE)
    publish.assert_called_once_with(expected)
    api.freeze.assert_called_once_with(JOB, expected)
    api.published.assert_called_once_with(JOB)
    api.retry.assert_not_called()


def test_failed_approval_publication_reuses_frozen_envelope_after_source_changes():
    """DR3/DR4: fail broker boundary then reclaim; publish exact frozen approval,
    never reconstruct from later name/recipient changes or call freeze twice.
    """
    api, publish = Mock(), Mock(side_effect=RuntimeError("broker unavailable"))
    api.claim.return_value = [JOB]
    api.freeze.side_effect = lambda job, envelope: envelope
    dispatch_once(api, publish)
    frozen = publish.call_args.args[0]
    api.published.assert_not_called()
    api.retry.assert_called_once_with(JOB, "RuntimeError")
    api.reset_mock()
    retry = {**JOB, "envelope": frozen,
             "source": {**SOURCE, "eventName": "Renamed", "recipientId": "changed"}}
    api.claim.return_value = [retry]
    publish = Mock()
    dispatch_once(api, publish)
    publish.assert_called_once_with(frozen)
    api.freeze.assert_not_called()
    api.published.assert_called_once_with(retry)
