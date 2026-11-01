"""
SCRUM-44: Event Coordinator Notification and Alert Workflow

User Story
----------
As a Lead Coordinator, I want to receive an in-app notification when an Event
Organiser submits an event request, so that I can review it and make a
decision.

Acceptance Criteria
-------------------
AC1: Given an Event Organiser submits a new event request, the Lead Coordinator
     receives an in-app notification that a new request requires review.
AC2: The notification includes the event name, Event Organiser name, proposed
     event date/time, and a link to review the event request.
AC3: Saving or editing a draft event request does not trigger a submission
     notification.

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
- AC3 (saving a draft sends no submission notification): this worker only
  delivers jobs the owner queued, and has no notion of drafts. Whether a draft
  save queues a job is Event Service's decision (-> event-service drafts tests).
- That Notification Service stores and shows the inbox item (->
  notification-service consumer tests and frontend NotificationCenter tests).
"""
import json
from unittest.mock import Mock, patch

import httpx
import pytest
from app.dispatcher import OutboxAPI, dispatch_once

ID = '10000000-0000-0000-0000-000000000001'
SECOND_LEAD = '10000000-0000-0000-0000-000000000002'
SOURCE = dict(eventId=ID, eventName='Workshop', organiserId=ID,
              startDateTime='2030-06-02T23:15:00+08:00', endDateTime='2030-06-03T01:45:00+08:00')
JOB = dict(id=ID, type='event.submission-fanout', source=SOURCE, envelope=None,
           createdAt='2026-10-25T00:00:00+00:00', leaseToken=ID)


# AC1 — Look up Leads or request another attempt.

@pytest.mark.parametrize('users,name,failed', [
    ([{'user_id': ID, 'role': 'Event Coordinator Lead'},
      {'user_id': SECOND_LEAD, 'role': 'Event Coordinator Lead'}], 'Synthetic Organiser', False),
    ([], None, False),
    ({}, None, True),
    ([{'user_id': ID, 'role': 'Event Organiser'}], None, True),
    ([{'user_id': ID, 'role': 'Event Coordinator Lead'}], '', True),
    ([{'user_id': ID, 'role': 'Event Coordinator Lead'}], [], True),
    (503, None, True),
], ids=['two-valid-leads', 'no-leads', 'malformed-user-list', 'wrong-role',
        'blank-organiser-name', 'malformed-organiser', 'user-service-unavailable'])
def test_ac1_submission_alert_expands_to_leads_or_retries(monkeypatch, caplog, users, name, failed):
    """
    Summary: dispatch_once on one claimed submission fan-out job asks User
        Service for the Event Coordinator Leads and the organiser's name; with
        two valid Leads it posts an expand call listing both Lead ids and the
        organiser name "Synthetic Organiser"; with no Leads it expands to an
        empty list, organiser name "No recipients" and logs "no Event
        Coordinator Lead"; with a malformed list, a non-Lead user, a blank or
        malformed organiser name, or a 503 it posts a retry instead. Nothing is
        published to the broker in any case.
    AC1: Given an Event Organiser submits a new event request, the Lead
        Coordinator receives an in-app notification that a new request requires
        review.
    Double: Stub (httpx.request routed to an in-memory transport: claim
        returns the fan-out job; GET /users?role=Event Coordinator Lead returns
        the parametrized users or 503; GET /users/<id> returns the
        parametrized organiser name), Mock (broker not called; the last
        recorded request is /expand or /retry)
    """
    # Arrange (Given)
    monkeypatch.setenv('EVENT_SERVICE_URL', 'http://event.test')
    monkeypatch.setenv('USER_SERVICE_URL', 'http://user.test')
    monkeypatch.setenv('INTERNAL_SERVICE_TOKEN', 'synthetic-token')
    requests = []
    def transport(request):
        """Record the HTTP request and return synthetic claim or User data.
        No network request is sent."""
        requests.append(request)
        path = request.url.path
        if path.endswith('/claim'):
            return httpx.Response(200, json={'jobs': [JOB]})
        if path == '/users':
            assert request.url.params['role'] == 'Event Coordinator Lead'
            return httpx.Response(503 if users == 503 else 200, json={'users': users})
        if path.startswith('/users/'):
            return httpx.Response(200, json={'username': name} if not isinstance(name, list) else name)
        return httpx.Response(200, json={})
    broker = Mock()

    # Act (When)
    with httpx.Client(transport=httpx.MockTransport(transport)) as client, patch('httpx.request', side_effect=client.request):
        assert dispatch_once(OutboxAPI(), broker) == 1

    # Assert (Then)
    broker.assert_not_called()
    final = requests[-1]
    if failed:
        assert final.url.path.endswith('/retry')
    else:
        assert final.url.path.endswith('/expand')
        body = json.loads(final.content)
        assert body['recipientIds'] == ([ID, SECOND_LEAD] if users else [])
        assert body['organiserName'] == (name if users else 'No recipients')
        if not users:
            assert 'no Event Coordinator Lead' in caplog.text


# AC2 — Save the message before sending.

@pytest.mark.parametrize('freeze_fails', [False, True], ids=['freeze-succeeds', 'freeze-fails'])
def test_ac1_ac2_submission_alert_freezes_before_publish(freeze_fails):
    """
    Summary: dispatch_once on one claimed submission job for a Lead builds the
        envelope with the message "Synthetic Organiser submitted Workshop.
        Review required.", an event-details link and the event name, organiser
        name and start/end times, and asks the owner to freeze it first; when
        freeze succeeds only the owner's returned envelope is published and the
        job is marked published; when freeze raises, nothing is published and
        a retry is recorded with "RuntimeError".
    AC1: Given an Event Organiser submits a new event request, the Lead
        Coordinator receives an in-app notification that a new request requires
        review.
    AC2: The notification includes the event name, Event Organiser name,
        proposed event date/time, and a link to review the event request.
    Double: Stub (api.claim returns the submission job; api.freeze asserts the
        exact draft envelope, then returns an owner envelope or raises
        RuntimeError("temporary failure")), Mock (publish asserts freeze came
        first and receives the owner envelope; published and retry calls
        asserted)
    """
    api = Mock()
    job = {**JOB, 'type': 'event.submission', 'source': {**SOURCE, 'recipientId': SECOND_LEAD, 'organiserName': 'Synthetic Organiser'}}
    api.claim.return_value = [job]
    effects = []
    frozen = {'saved': 'owner-returned-envelope'}
    def freeze(received, envelope):
        """Check the candidate message and record the save attempt.
        Return a fake owner result or raise; nothing is persisted."""
        assert effects == []
        assert envelope == {
            'version': 1,
            'id': '10000000-0000-0000-0000-000000000001',
            'type': 'event.submission',
            'recipientId': '10000000-0000-0000-0000-000000000002',
            'createdAt': '2026-10-25T00:00:00+00:00',
            'message': 'Synthetic Organiser submitted Workshop. Review required.',
            'destination': {
                'kind': 'event-details',
                'eventId': '10000000-0000-0000-0000-000000000001',
            },
            'details': {
                'eventId': '10000000-0000-0000-0000-000000000001',
                'eventName': 'Workshop',
                'organiserId': '10000000-0000-0000-0000-000000000001',
                'organiserName': 'Synthetic Organiser',
                'recipientId': '10000000-0000-0000-0000-000000000002',
                'startDateTime': '2030-06-02T23:15:00+08:00',
                'endDateTime': '2030-06-03T01:45:00+08:00',
            },
        }
        effects.append('freeze')
        if freeze_fails:
            raise RuntimeError('temporary failure')
        return frozen
    api.freeze.side_effect = freeze
    def publish(envelope):
        """Check the saved message follows the save step and record publishing.
        Nothing is sent to a broker."""
        assert effects == ['freeze']
        assert envelope is frozen
        effects.append('publish')
    dispatch_once(api, publish)
    if freeze_fails:
        assert effects == ['freeze']
        api.retry.assert_called_once_with(job, 'RuntimeError')
        api.published.assert_not_called()
    else:
        assert effects == ['freeze', 'publish']
        api.published.assert_called_once_with(job)
