"""
SCRUM-47: Venue Booking Notification and Decision Alerts

User Story
----------
As an Event Coordinator and Venue Staff, I want to receive notifications about
venue booking requests and decisions, so that I can coordinate venue
arrangements efficiently.

Acceptance Criteria
-------------------
AC1: Given an Event Coordinator submits a venue booking request, the system
     sends an in-app notification to Venue Staff with the event name, requested
     venue, date/time, and a link to review the request.
AC2: Given a venue booking request is approved or rejected, the system sends an
     in-app notification to the Event Coordinator with the event name, venue,
     and decision.

Real
----
- app.dispatcher for booking alerts: Venue Staff fan-out from User Service, the
  requested period and review link, freezing before publish, and the original
  submitter as decision recipient.
- Assertions are on the frozen and published envelopes and retries.

Doubled
-------
- Venue Availability outbox and User/Event/Venue lookups: Stub (patched httpx)
  - canned replies; requests inspected.
- pika (RabbitMQ): Mock - publish inspected.

Not proven
----------
- That Notification Service shows the alert with a working link (->
  notification-service consumer tests and frontend NotificationCenter tests).
"""
from copy import deepcopy
from unittest.mock import patch

import httpx
import pytest

from app.dispatcher import OutboxAPI, dispatch_once

EVENT = "10000000-0000-0000-0000-000000000001"
BOOKING = "10000000-0000-0000-0000-000000000002"
VENUE = "10000000-0000-0000-0000-000000000003"
JOB = "10000000-0000-0000-0000-000000000004"
STAFF = "20000000-0000-0000-0000-000000000001"
OTHER_STAFF = "20000000-0000-0000-0000-000000000002"
SUBMITTER = "30000000-0000-0000-0000-000000000001"
CURRENT_COORDINATOR = "30000000-0000-0000-0000-000000000002"
SOURCE = dict(eventId=EVENT, bookingId=BOOKING, venueId=VENUE, requestedBy=SUBMITTER,
              startDateTime="2099-01-01T01:00:00+00:00",
              endDateTime="2099-01-01T03:00:00+00:00")
CREATED_AT = "2026-10-27T00:00:00+00:00"
CHILD_IDS = {STAFF: "40000000-0000-0000-0000-000000000001",
             OTHER_STAFF: "40000000-0000-0000-0000-000000000002"}


@pytest.fixture
def dispatch(monkeypatch):
    for key, value in dict(VENUE_AVAILABILITY_SERVICE_URL="http://owner.invalid",
                           EVENT_SERVICE_URL="http://event.invalid",
                           VENUE_SERVICE_URL="http://venue.invalid",
                           USER_SERVICE_URL="http://user.invalid",
                           INTERNAL_SERVICE_TOKEN="synthetic").items():
        monkeypatch.setenv(key, value)

    def run(kind, source):
        job: dict = dict(id=JOB, type=kind, source=deepcopy(source), envelope=None,
                         leaseToken=JOB, createdAt=CREATED_AT, attempts=1)
        jobs = [job]
        drafts, frozen, recorded, operations = [], [], [], []

        def http(method, url, **kwargs):
            assert kwargs["headers"] == {"X-Internal-Token": "synthetic"}
            if url.endswith("/claim"):
                assert method == "POST" and kwargs["json"] == {}
                body = dict(jobs=deepcopy(jobs))
            elif url == "http://user.invalid/users":
                # User Service app/__init__.py /users + app/models.py serialize.
                assert method == "GET" and kwargs["params"] == {"role": "Venue Staff"}
                body = dict(users=[dict(user_id=uid, role="Venue Staff", username="Staff",
                                        email="staff@example.invalid", organization="Community",
                                        contact_details="")
                                   for uid in (OTHER_STAFF, STAFF, OTHER_STAFF)])
            elif url == f"http://event.invalid/internal/events/{EVENT}/notification-context":
                # Event Service internal notification-context serializer.
                body = dict(id=EVENT, eventName="Community Fair",
                            coordinatorId=CURRENT_COORDINATOR)
            elif url == f"http://venue.invalid/venues/{VENUE}":
                # Venue Service GET /venues/<id>, app/models.py serialize.
                body = dict(venue=dict(id=VENUE, name="Grand Hall", location="Level 1",
                                       capacity=100, facilities=[], accessibility="",
                                       supportedLayouts=[], status="Available", setupTimeMinutes=0,
                                       turnaroundTimeMinutes=0, emergencyAccessDetails=None,
                                       knownRestrictions=None, safetyInfoUpdatedBy=None,
                                       safetyInfoUpdatedAt=None))
            elif url.endswith("/expand"):
                operations.append("expand")
                assert method == "POST"
                assert kwargs["json"] == dict(leaseToken=JOB, recipientIds=[STAFF, OTHER_STAFF],
                                               eventName="Community Fair", venueName="Grand Hall")
                assert recorded == []
                # Simulate the owner's two independently claimable children, not expansion SQL.
                jobs[:] = [dict(job, id=CHILD_IDS[uid], type="venue.booking-submission", source={
                    **source, "recipientId": uid, "eventName": "Community Fair",
                    "venueName": "Grand Hall"}) for uid in (STAFF, OTHER_STAFF)]
                body = dict(status="expanded", recipients=2)
            elif url.endswith("/freeze"):
                operations.append("freeze")
                draft = deepcopy(kwargs["json"]["envelope"])
                assert method == "POST"
                assert url == f"http://owner.invalid/internal/notification-outbox/{draft['id']}/freeze"
                assert kwargs["json"]["leaseToken"] == JOB
                drafts.append(draft)
                # Valid earlier owner history: identity/details unchanged, message distinguishable.
                saved = {**deepcopy(draft), "message": "Saved: " + draft["message"]}
                frozen.append(saved)
                body = dict(envelope=saved)
            elif url.endswith("/published"):
                operations.append("published")
                assert method == "POST"
                assert url == f"http://owner.invalid/internal/notification-outbox/{recorded[-1]['id']}/published"
                assert kwargs["json"] == {"leaseToken": JOB}
                assert len(recorded) == len(frozen)
                body = dict(status="published")
            else:
                raise AssertionError("Unexpected request " + url)
            return httpx.Response(200, json=body, request=httpx.Request(method, url))

        def publish(envelope):
            assert operations[-1] == "freeze"
            assert envelope == frozen[-1] and envelope != drafts[-1]
            operations.append("publish")
            recorded.append(deepcopy(envelope))

        with patch("httpx.request", side_effect=http):
            dispatch_once(OutboxAPI(), publish)
            if kind == "venue.booking-submission-fanout":
                dispatch_once(OutboxAPI(), publish)
        expected = ["freeze", "publish", "published"]
        assert operations == (["expand"] + expected * 2 if kind.endswith("fanout") else expected)
        assert recorded == frozen
        assert len(recorded) == (2 if kind.endswith("fanout") else 1)
        return drafts  # Business content below; publication of exact owner readback checked above.
    return run


@pytest.fixture
def failed_dispatch(monkeypatch):
    """Control only outbound HTTP; run the actual adapter and dispatcher recovery."""
    for key, value in dict(VENUE_AVAILABILITY_SERVICE_URL="http://owner.invalid",
                           EVENT_SERVICE_URL="http://event.invalid",
                           VENUE_SERVICE_URL="http://venue.invalid",
                           USER_SERVICE_URL="http://user.invalid",
                           INTERNAL_SERVICE_TOKEN="synthetic").items():
        monkeypatch.setenv(key, value)

    def run(scenario):
        kind = ("venue.booking-decision" if scenario == "invalid-decision" else
                "unsupported.venue-type" if scenario == "unknown-type" else
                "venue.booking-submission" if scenario == "freeze-refused" else
                "venue.booking-submission-fanout")
        source = {**SOURCE, "decision": "Pending Review"} if scenario == "invalid-decision" else {
            **SOURCE, "recipientId": STAFF, "eventName": "Community Fair", "venueName": "Grand Hall"}
        job = dict(id=JOB, type=kind, source=source, envelope=None,
                   leaseToken=JOB, createdAt=CREATED_AT, attempts=1)
        requests, publications = [], []

        def http(method, url, **kwargs):
            requests.append((method, url, kwargs))
            assert kwargs["headers"] == {"X-Internal-Token": "synthetic"}
            if url.endswith("/claim"):
                assert method == "POST" and kwargs["json"] == {}
                body = {"jobs": [deepcopy(job)]}
            elif url == "http://user.invalid/users":
                # User Service GET /users returns {users: [app.models.serialize(...)]}.
                assert method == "GET" and kwargs["params"] == {"role": "Venue Staff"}
                if scenario == "user-outage":
                    raise httpx.ConnectError("synthetic user outage", request=httpx.Request(method, url))
                users = ({"unexpected": "object"} if scenario == "invalid-users" else
                         [] if scenario == "empty-staff" else
                         [{"user_id": STAFF, "role": "Event Coordinator"}])
                body = {"users": users}
            elif url.endswith("/freeze") and scenario == "freeze-refused":
                # Owner app/outbox.py operate: lost lease refuses freeze with 409.
                assert method == "POST" and kwargs["json"]["leaseToken"] == JOB
                return httpx.Response(409, json={"message": "Lease lost."},
                                      request=httpx.Request(method, url))
            elif url.endswith("/retry"):
                assert method == "POST"
                body = {"id": JOB, "status": "retry"}
            else:
                raise AssertionError("Unexpected request " + url)
            return httpx.Response(200, json=body, request=httpx.Request(method, url))

        with patch("httpx.request", side_effect=http):
            count = dispatch_once(OutboxAPI(), publications.append)
        return count, requests, publications
    return run


def test_submission_alert_reaches_each_staff_member_with_period_and_link(dispatch):
    """
    Summary: Each Venue Staff member gets one alert with the event, venue, period and review link.
    AC1: Given an Event Coordinator submits a venue booking request, the system
        sends an in-app notification to Venue Staff with the event name,
        requested venue, date/time, and a link to review the request.
    Double: Stub (staff lookup with duplicates), Mock (publish)
    """
    # Arrange (Given): dispatch, from fixtures

    # Act (When)
    alerts = dispatch("venue.booking-submission-fanout", SOURCE)

    # Assert (Then)
    assert {alert["recipientId"] for alert in alerts} == {STAFF, OTHER_STAFF}
    for alert in alerts:
        recipient = alert["recipientId"]
        assert alert == dict(
            version=1, id=CHILD_IDS[recipient], type="venue.booking-submission", recipientId=recipient,
            createdAt=CREATED_AT,
            message=("Community Fair: venue booking requested for Grand Hall. "
                     "01 Jan 2099, 09:00 SGT to 01 Jan 2099, 11:00 SGT. Review required."),
            destination={"kind": "venue-requests"},
            details={**SOURCE, "recipientId": recipient, "eventName": "Community Fair",
                     "venueName": "Grand Hall"},
        )


@pytest.mark.parametrize("scenario,steps", [
    pytest.param("invalid-users", ["claim", "users", "retry"], id="staff-collection-not-list"),
    pytest.param("wrong-role", ["claim", "users", "retry"], id="lookup-returned-non-staff"),
    pytest.param("empty-staff", ["claim", "users", "retry"], id="no-staff-to-notify"),
    pytest.param("unknown-type", ["claim", "retry"], id="unsupported-job-type"),
    pytest.param("invalid-decision", ["claim", "retry"], id="unsupported-decision"),
])
def test_alert_with_bad_recipients_or_type_retries_without_publishing(failed_dispatch, scenario, steps):
    """
    Summary: Unusable recipients, type or decision lead to a retry, not a publish.
    AC1: Given an Event Coordinator submits a venue booking request, the system
        sends an in-app notification to Venue Staff with the event name,
        requested venue, date/time, and a link to review the request.
    AC2: Given a venue booking request is approved or rejected, the system
        sends an in-app notification to the Event Coordinator with the event
        name, venue, and decision.
    Double: Stub (bad lookups), Mock (no publish)
    """
    # Arrange (Given): failed_dispatch, scenario, steps, from fixtures

    # Act (When)
    count, requests, publications = failed_dispatch(scenario)

    # Assert (Then)
    assert count == 1
    assert [url.rsplit("/", 1)[-1] for _, url, _ in requests] == steps
    assert requests[-1] == ("POST", f"http://owner.invalid/internal/notification-outbox/{JOB}/retry", {
        "headers": {"X-Internal-Token": "synthetic"}, "timeout": 5,
        "json": {"leaseToken": JOB, "error": "ValueError"}})
    assert publications == []


def test_submission_alert_when_user_service_down_retries(failed_dispatch):
    """
    Summary: A User Service outage keeps the submission alert waiting.
    AC1: Given an Event Coordinator submits a venue booking request, the system
        sends an in-app notification to Venue Staff with the event name,
        requested venue, date/time, and a link to review the request.
    Double: Stub (User Service unreachable), Mock (no publish)
    """
    # Arrange (Given): failed_dispatch, from fixtures

    # Act (When)
    count, requests, publications = failed_dispatch("user-outage")

    # Assert (Then)
    assert count == 1
    assert [url.rsplit("/", 1)[-1] for _, url, _ in requests] == ["claim", "users", "retry"]
    assert requests[-1][2]["json"] == {"leaseToken": JOB, "error": "ConnectError"}
    assert requests[-1][:2] == ("POST", f"http://owner.invalid/internal/notification-outbox/{JOB}/retry")
    assert publications == []


def test_submission_alert_when_freeze_refused_publishes_nothing(failed_dispatch):
    """
    Summary: If the owner refuses to freeze an alert, nothing is published.
    AC1: Given an Event Coordinator submits a venue booking request, the system
        sends an in-app notification to Venue Staff with the event name,
        requested venue, date/time, and a link to review the request.
    Double: Stub (freeze refused), Mock (no publish)
    """
    # Arrange (Given): failed_dispatch, from fixtures

    # Act (When)
    count, requests, publications = failed_dispatch("freeze-refused")

    # Assert (Then)
    assert count == 1
    assert [url.rsplit("/", 1)[-1] for _, url, _ in requests] == ["claim", "freeze", "retry"]
    assert requests[-1][2]["json"] == {"leaseToken": JOB, "error": "HTTPStatusError"}
    assert requests[-1][:2] == ("POST", f"http://owner.invalid/internal/notification-outbox/{JOB}/retry")
    assert publications == []


def test_approval_alert_reaches_original_submitter_with_decision_and_link(dispatch):
    """
    Summary: An approval alert goes to the coordinator who asked, with the decision and link.
    AC2: Given a venue booking request is approved or rejected, the system
        sends an in-app notification to the Event Coordinator with the event
        name, venue, and decision.
    Double: Stub (owner outbox), Mock (publish)
    """
    # Arrange (Given): dispatch, from fixtures

    # Act (When)
    [alert] = dispatch("venue.booking-decision", {**SOURCE, "decision": "Approved"})

    # Assert (Then)
    assert alert == dict(
        version=1, id=JOB, type="venue.booking-decision", recipientId=SUBMITTER,
        createdAt=CREATED_AT, message="Community Fair: venue booking for Grand Hall approved.",
        destination={"kind": "event-venue-request", "eventId": EVENT, "bookingId": BOOKING},
        details={**SOURCE, "decision": "Approved", "eventName": "Community Fair", "venueName": "Grand Hall"},
    )


def test_rejection_alert_reaches_original_submitter_with_decision(dispatch):
    """
    Summary: A rejection alert goes to the coordinator who asked, with the decision.
    AC2: Given a venue booking request is approved or rejected, the system
        sends an in-app notification to the Event Coordinator with the event
        name, venue, and decision.
    Double: Stub (owner outbox), Mock (publish)
    """
    # Arrange (Given): dispatch, from fixtures

    # Act (When)
    [alert] = dispatch("venue.booking-decision", {**SOURCE, "decision": "Rejected"})

    # Assert (Then)
    assert alert == dict(
        version=1, id=JOB, type="venue.booking-decision", recipientId=SUBMITTER,
        createdAt=CREATED_AT, message="Community Fair: venue booking for Grand Hall rejected.",
        destination={"kind": "event-venue-request", "eventId": EVENT, "bookingId": BOOKING},
        details={**SOURCE, "decision": "Rejected", "eventName": "Community Fair", "venueName": "Grand Hall"},
    )
