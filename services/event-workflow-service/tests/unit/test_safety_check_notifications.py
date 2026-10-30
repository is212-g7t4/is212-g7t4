"""
SCRUM-168: Safety Check Notifications

User Story
----------
As an Event Coordinator, I want to be notified of the Safety Officer's decision
on my event, so that I can act on it straight away.

Acceptance Criteria
-------------------
AC1: Given an event is submitted or resubmitted for a safety check, then Safety
     Officers receive an in-app notification with the event name, date and a
     link to the review.
AC2: Given a decision is recorded, then the assigned Event Coordinator receives
     an in-app notification with the event name, the decision and, for
     rejection or requested changes, the reason and affected areas.
AC3: Given notification delivery fails, then the decision remains recorded and
     is not rolled back.
AC4: Given a notification is sent, then it records the event, recipient, type
     and timestamp.

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
import json
from unittest.mock import Mock, patch

import httpx
import pytest
from app.dispatcher import OutboxAPI, dispatch_once

ID = '10000000-0000-0000-0000-000000000001'
OFFICER = '10000000-0000-0000-0000-000000000004'
OTHER = '10000000-0000-0000-0000-000000000005'
SOURCE = dict(eventId=ID, eventName='Workshop', round=1,
              startDateTime='2030-03-01T09:00:00+08:00', endDateTime='2030-03-01T17:00:00+08:00')
JOB = dict(id=ID, type='safety.review-fanout', source=SOURCE, envelope=None,
           createdAt='2026-10-28T00:00:00+00:00', leaseToken=ID, attempts=1)


def test_safety_review_alert_goes_to_every_safety_officer(monkeypatch):
    """
    Summary: A safety review alert goes to every Safety Officer.
    AC1: Given an event is submitted or resubmitted for a safety check, then
        Safety Officers receive an in-app notification with the event name,
        date and a link to the review.
    Double: Stub (user lookup returns officers), Mock (publish)
    """
    # Arrange (Given)
    monkeypatch.setenv('EVENT_SERVICE_URL', 'http://event.test')
    monkeypatch.setenv('USER_SERVICE_URL', 'http://user.test')
    monkeypatch.setenv('INTERNAL_SERVICE_TOKEN', 'synthetic')
    requests = []
    current = [JOB]
    expected = dict(version=1, id=ID, type='safety.review-submitted', recipientId=OFFICER,
                    createdAt=JOB['createdAt'], details={**SOURCE, 'recipientId': OFFICER},
                    destination=dict(kind='event-details', eventId=ID),
                    message='Workshop requires safety review (round 1). Proposed: 01 Mar 2030, 09:00 SGT – 01 Mar 2030, 17:00 SGT.')

    def transport(request):
        # Producers: services/event-service/app/outbox.py::operate / serialize / mutate;
        # services/user-service/app/__init__.py::users and app/models.py::serialize.
        requests.append(request)
        if request.url.path.endswith('/claim'):
            return httpx.Response(200, json={'jobs': current})
        if request.url.path == '/users':
            assert request.url.params['role'] == 'Safety Officer'
            return httpx.Response(200, json={'users': [dict(user_id=value, username='Synthetic officer', email='officer@example.com',
                                                           role='Safety Officer', organization='', contact_details='')
                                                      for value in (OFFICER, OTHER)]})
        if request.url.path.endswith('/freeze'):
            assert json.loads(request.content)['envelope'] == expected
            return httpx.Response(200, json={**current[0], 'envelope': expected})
        if request.url.path.endswith('/expand'):
            return httpx.Response(200, json=dict(id=ID, status='expanded', recipients=2))
        assert request.url.path.endswith('/published')
        return httpx.Response(200, json=dict(id=ID, status='published'))

    broker = Mock()

    # Act (When)
    with httpx.Client(transport=httpx.MockTransport(transport)) as client, patch('httpx.request', side_effect=client.request):
        dispatch_once(OutboxAPI(), broker)
        expansion = next(r for r in requests if r.url.path.endswith('/expand'))
        assert json.loads(expansion.content) == dict(leaseToken=ID, recipientIds=[OFFICER, OTHER])
        broker.assert_not_called()
        current[:] = [{**JOB, 'type': 'safety.review-submitted', 'source': expected['details']}]
        dispatch_once(OutboxAPI(), broker)

    # Assert (Then)
    broker.assert_called_once_with(expected)
    assert requests[-1].url.path.endswith('/published')


@pytest.mark.parametrize('users', [
    {},
    [dict(user_id=OFFICER, username='Synthetic officer', email='officer@example.com',
          role='Safety Officer', organization='', contact_details=''),
     dict(user_id=OTHER, username='Synthetic organiser', email='organiser@example.com',
          role='Event Organiser', organization='', contact_details='')],
], ids=['malformed-user-list', 'wrong-role-after-valid-officer'])
def test_safety_review_alert_with_bad_officer_lookup_retries(safety_outbox_http, caplog, users):
    """
    Summary: A bad Safety Officer lookup is retried rather than alerting only some officers.
    AC1: Given an event is submitted or resubmitted for a safety check, then
        Safety Officers receive an in-app notification with the event name,
        date and a link to the review.
    Double: Stub (user lookup invalid), Mock (no publish)
    """
    # Arrange (Given)
    # Arrange: malformed responses deliberately violate User's /users contract
    # (services/user-service/app/__init__.py::users, app/models.py::serialize).
    api, http = safety_outbox_http
    claim = http.post('http://event.test/internal/notification-outbox/claim').respond(200, json={'jobs': [JOB]})
    lookup = http.get('http://user.test/users', params={'role': 'Safety Officer'}).respond(200, json={'users': users})
    # Owner responses: services/event-service/app/outbox.py::operate / mutate.
    retry = http.post(f'http://event.test/internal/notification-outbox/{ID}/retry').respond(200, json={'id': ID, 'status': 'retry'})
    broker = Mock()

    # Act + Assert (When / Then)
    # Act: the worker uses its real HTTP adapter, not a mocked recipient method.
    assert dispatch_once(api, broker) == 1

    # Assert: no expand, freeze or published request can precede the retry.
    assert [call.request for call in http.calls] == [claim.calls[0].request, lookup.calls[0].request, retry.calls[0].request]
    assert all(route.call_count == 1 for route in (claim, lookup, retry))
    assert json.loads(claim.calls[0].request.content) == {}
    assert json.loads(retry.calls[0].request.content) == {'leaseToken': ID, 'error': 'ValueError'}
    assert retry.calls[0].request.headers['X-Internal-Token'] == 'synthetic'
    broker.assert_not_called()
    assert [record.getMessage() for record in caplog.records if record.name == 'app.dispatcher'] == [
        f'Dispatch retry source={ID} error=ValueError',
    ]


def test_safety_review_alert_with_no_officers_completes_with_warning(safety_outbox_http, caplog):
    """
    Summary: With no Safety Officers, the job completes with a warning and sends nothing.
    AC1: Given an event is submitted or resubmitted for a safety check, then
        Safety Officers receive an in-app notification with the event name,
        date and a link to the review.
    Double: Stub (user lookup returns none)
    """
    # Arrange (Given)
    # Arrange: User's /users returns an empty list when its role filter has no
    # matches (services/user-service/app/__init__.py::users).
    api, http = safety_outbox_http
    claim = http.post('http://event.test/internal/notification-outbox/claim').respond(200, json={'jobs': [JOB]})
    lookup = http.get('http://user.test/users', params={'role': 'Safety Officer'}).respond(200, json={'users': []})
    # Owner contract: services/event-service/app/outbox.py::operate / mutate.
    expansion = http.post(f'http://event.test/internal/notification-outbox/{ID}/expand').respond(
        200, json={'id': ID, 'status': 'expanded', 'recipients': 0},
    )
    broker = Mock()

    # Act + Assert (When / Then)
    # Act / Assert: complete through the owner's public HTTP expansion boundary.
    assert dispatch_once(api, broker) == 1
    assert [call.request for call in http.calls] == [claim.calls[0].request, lookup.calls[0].request, expansion.calls[0].request]
    assert all(route.call_count == 1 for route in (claim, lookup, expansion))
    assert json.loads(claim.calls[0].request.content) == {}
    assert json.loads(expansion.calls[0].request.content) == {'leaseToken': ID, 'recipientIds': []}
    assert expansion.calls[0].request.headers['X-Internal-Token'] == 'synthetic'
    broker.assert_not_called()
    assert [(record.levelname, record.getMessage()) for record in caplog.records if record.name == 'app.dispatcher'] == [
        ('WARNING', f'Safety review skipped: no Safety Officer source={ID}'),
    ]


@pytest.mark.parametrize('decision,reason,areas,message', [
    ('Approved', 'Exit plan agreed.', [], 'Workshop safety review: Approved (round 1). Exit plan agreed.'),
    ('Approved', None, [], 'Workshop safety review: Approved (round 1).'),
    ('Rejected', 'Unsafe exits.', [], 'Workshop safety review: Rejected (round 1). Unsafe exits.'),
    ('Changes Requested', 'Revise the plan.', ['venue arrangement', 'event details'],
     'Workshop safety review: Changes Requested (round 1). Revise the plan. Affected areas: venue arrangement, event details.'),
], ids=['approval-remarks', 'approval-no-remarks', 'rejection-reason', 'changes-reason-areas'])
def test_safety_decision_alert_freezes_then_retries_failed_delivery(decision, reason, areas, message):
    """
    Summary: A decision alert is frozen before sending, and a failed send is retried.
    AC2: Given a decision is recorded, then the assigned Event Coordinator
        receives an in-app notification with the event name, the decision and,
        for rejection or requested changes, the reason and affected areas.
    AC3: Given notification delivery fails, then the decision remains recorded
        and is not rolled back.
    Double: Stub (owner outbox), Mock (publish fails then succeeds)
    """
    # Arrange (Given)
    source = dict(eventId=ID, eventName='Workshop', round=1, recipientId=OTHER,
                  decision=decision, reason=reason, areas=areas)
    job = {**JOB, 'type': 'safety.review-decision', 'source': source}
    expected = dict(version=1, id=ID, type='safety.review-decision', recipientId=OTHER,
                    createdAt=JOB['createdAt'], details=source, message=message,
                    destination=dict(kind='event-details', eventId=ID))
    api = Mock()
    api.claim.return_value = [job]
    effects = []
    frozen = dict(expected)

    def freeze(received, envelope):
        assert received == job
        assert envelope == expected
        assert effects == []
        effects.append('freeze')
        return frozen

    def publish(envelope):
        assert effects[0] == 'freeze'
        assert envelope is frozen
        effects.append('publish')
        if reason == 'Exit plan agreed.' and effects.count('publish') == 1:
            raise RuntimeError('synthetic broker unavailable')

    api.freeze.side_effect = freeze
    dispatch_once(api, publish)

    # Act (When)
    if reason == 'Exit plan agreed.':
        api.retry.assert_called_once_with(job, 'RuntimeError')
        api.published.assert_not_called()
        api.claim.return_value = [{**job, 'envelope': frozen}]
        dispatch_once(api, publish)

    # Assert (Then)
    api.freeze.assert_called_once()
    api.published.assert_called_once()
