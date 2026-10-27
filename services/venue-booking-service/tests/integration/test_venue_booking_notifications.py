"""SCRUM-47 Venue booking notification and decision alerts: dispatcher integration tests.

Story: As an Event Coordinator and Venue Staff, I want to receive notifications
about venue booking requests and decisions, so that I can coordinate venue
arrangements efficiently.
AC1 Given an Event Coordinator submits a venue booking request, system sends
an in-app notification to Venue Staff with event name, requested venue,
date/time and link to review.
AC2 Given booking approved/rejected, sends an in-app notification to Event
Coordinator with event name, venue, decision.

AC = acceptance criterion; DR = supporting design rule, not another AC.
Real: dispatch_once, OutboxAPI/httpx, staff selection and submission formatting.
Doubled: all owner/User/Event/Venue HTTP with strict respx; recording publisher.
AC1 covers fanout orchestration, frozen-returned content and delivery retry.
AC2 enriched decision content remains in the three existing dispatcher unit
cases; existing route integration modules cover decision forwarding/refusal.
Not proven: atomic DB fanout/leases, inbox delivery, real HTTP/broker, UI, JWT
or upgrades. This DB-less composite starts no database or sibling service.
"""
from copy import deepcopy
import json

import httpx
import pytest
import respx

from app.dispatcher import OutboxAPI, dispatch_once

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
EVENT = "10000000-0000-4000-8000-000000000001"
BOOKING = "10000000-0000-4000-8000-000000000002"
VENUE = "10000000-0000-4000-8000-000000000003"
PARENT = "10000000-0000-4000-8000-000000000004"
SUBMITTER = "10000000-0000-4000-8000-000000000005"
STAFF = "20000000-0000-4000-8000-000000000001"
OTHER_STAFF = "20000000-0000-4000-8000-000000000002"
CHILDREN = ["30000000-0000-4000-8000-000000000001", "30000000-0000-4000-8000-000000000002"]
STAMP = "2026-10-27T00:00:00+00:00"


# AC1 — one readable fanout → two recipients → retry sequence (DR frozen history).
def test_ac1_http_fanout_and_delivery_retry_publish_exact_owner_history(monkeypatch):
    """Failure: a broker outage retries one child without refetching names or losing either staff alert."""
    for key, value in dict(VENUE_AVAILABILITY_SERVICE_URL="http://owner.invalid",
                           EVENT_SERVICE_URL="http://event.invalid", VENUE_SERVICE_URL="http://venue.invalid",
                           USER_SERVICE_URL="http://user.invalid", INTERNAL_SERVICE_TOKEN="synthetic").items():
        monkeypatch.setenv(key, value)
    source = dict(eventId=EVENT, bookingId=BOOKING, venueId=VENUE, requestedBy=SUBMITTER,
                  startDateTime="2030-03-01T05:00:00+00:00", endDateTime="2030-03-01T07:00:00+00:00")
    # Owner app/outbox.py serialize and expand; these are HTTP fixtures, not owner SQL proof.
    parent: dict = dict(id=PARENT, type="venue.booking-submission-fanout", source=source,
                  envelope=None, leaseToken=PARENT, attempts=1, createdAt=STAMP)
    children = [dict(parent, id=child, type="venue.booking-submission", leaseToken=child,
                     source={**source, "recipientId": staff, "eventName": "Spring Fair", "venueName": "Hall A"})
                for child, staff in zip(CHILDREN, (STAFF, OTHER_STAFF), strict=True)]
    expected: list[dict] = [dict(version=1, id=child["id"], type="venue.booking-submission",
                     recipientId=staff, createdAt=STAMP, details=deepcopy(child["source"]),
                     destination={"kind": "venue-requests"},
                     message="Spring Fair: venue booking requested for Hall A. 01 Mar 2030, 13:00 SGT to 01 Mar 2030, 15:00 SGT. Review required.")
                for child, staff in zip(children, (STAFF, OTHER_STAFF), strict=True)]
    saved = [{**deepcopy(value), "message": "Saved: " + value["message"]} for value in expected]
    retried = dict(children[0], envelope=saved[0], attempts=2,
                   leaseToken="40000000-0000-4000-8000-000000000001")
    claims = iter([parent, children[0], children[1], retried])
    events, attempts, completed = [], [], []

    def check(request, body=None):
        assert request.headers["X-Internal-Token"] == "synthetic"
        if body is not None:
            assert json.loads(request.content) == body

    def claim(request):
        check(request, {})
        job = next(claims)
        events.append("claim:" + job["id"])
        return httpx.Response(200, json={"jobs": [job]})

    def lookup(request, body):
        check(request)
        assert request.method == "GET" and request.content == b""
        assert str(request.url) == {
            "user.invalid": "http://user.invalid/users?role=Venue+Staff",
            "event.invalid": f"http://event.invalid/internal/events/{EVENT}/notification-context",
            "venue.invalid": f"http://venue.invalid/venues/{VENUE}",
        }[request.url.host]
        events.append("lookup:" + request.url.host)
        return httpx.Response(200, json=body)

    def expand(request):
        check(request, dict(leaseToken=PARENT, recipientIds=[STAFF, OTHER_STAFF],
                            eventName="Spring Fair", venueName="Hall A"))
        assert attempts == []
        events.append("expand")
        return httpx.Response(200, json=dict(id=PARENT, status="expanded", recipients=2))

    def freeze(index):
        def respond(request):
            check(request, dict(leaseToken=children[index]["leaseToken"], envelope=expected[index]))
            events.append("freeze:" + CHILDREN[index])
            return httpx.Response(200, json={**children[index], "envelope": saved[index]})
        return respond

    def published(index):
        def respond(request):
            token = retried["leaseToken"] if index == 0 else children[index]["leaseToken"]
            check(request, {"leaseToken": token})
            assert attempts[-1] == saved[index]
            events.append("published:" + CHILDREN[index])
            completed.append(CHILDREN[index])
            return httpx.Response(200, json=dict(id=CHILDREN[index], status="published"))
        return respond

    def retry(request):
        check(request, dict(leaseToken=children[0]["leaseToken"], error="OSError"))
        assert completed == []
        events.append("retry:" + CHILDREN[0])
        return httpx.Response(200, json=dict(id=CHILDREN[0], status="retry"))

    def publish(value):
        index = CHILDREN.index(value["id"])
        assert value == saved[index] and value != expected[index]
        attempts.append(deepcopy(value))
        events.append("publish:" + value["id"])
        if len(attempts) == 1:
            raise OSError("Synthetic broker outage")

    with respx.mock(assert_all_called=True, assert_all_mocked=True) as router:
        base = "http://owner.invalid/internal/notification-outbox"
        claim_route = router.post(base + "/claim").mock(side_effect=claim)
        # User GET /users: app/__init__.py list route and app/models.py serialize.
        user_route = router.get("http://user.invalid/users", params={"role": "Venue Staff"}).mock(
            side_effect=lambda req: lookup(req, dict(users=[dict(user_id=staff, role="Venue Staff",
                username="Synthetic staff", email=staff + "@example.com", organization="Community", contact_details="")
                for staff in (OTHER_STAFF, STAFF, OTHER_STAFF)])))
        # Event internal context route: app/__init__.py get_notification_context.
        event_route = router.get(f"http://event.invalid/internal/events/{EVENT}/notification-context").mock(
            side_effect=lambda req: lookup(req, dict(id=EVENT, eventName="Spring Fair", coordinatorId=SUBMITTER)))
        # Venue GET /venues/<id>: app/models.py serialize, wrapped as {venue: ...}.
        venue_route = router.get(f"http://venue.invalid/venues/{VENUE}").mock(side_effect=lambda req: lookup(req,
            dict(venue=dict(id=VENUE, name="Hall A", location="Level 1", capacity=100, facilities=[],
                accessibility="", supportedLayouts=[], status="Available", setupTimeMinutes=0,
                turnaroundTimeMinutes=0, emergencyAccessDetails=None, knownRestrictions=None,
                safetyInfoUpdatedBy=None, safetyInfoUpdatedAt=None))))
        router.post(base + f"/{PARENT}/expand").mock(side_effect=expand)
        freeze_routes, published_routes = [], []
        for index, child in enumerate(CHILDREN):
            freeze_routes.append(router.post(base + f"/{child}/freeze").mock(side_effect=freeze(index)))
            published_routes.append(router.post(base + f"/{child}/published").mock(side_effect=published(index)))
        retry_route = router.post(base + f"/{CHILDREN[0]}/retry").mock(side_effect=retry)
        api = OutboxAPI()
        for _ in range(4):
            assert dispatch_once(api, publish) == 1
        assert claim_route.call_count == 4
        assert [route.call_count for route in (user_route, event_route, venue_route)] == [1, 1, 1]
        assert [route.call_count for route in freeze_routes + published_routes] == [1, 1, 1, 1]
        assert retry_route.call_count == 1

    assert attempts == [saved[0], saved[1], saved[0]]
    assert completed == [CHILDREN[1], CHILDREN[0]]
    assert events == ["claim:" + PARENT, "lookup:user.invalid", "lookup:event.invalid", "lookup:venue.invalid", "expand",
                      "claim:" + CHILDREN[0], "freeze:" + CHILDREN[0], "publish:" + CHILDREN[0], "retry:" + CHILDREN[0],
                      "claim:" + CHILDREN[1], "freeze:" + CHILDREN[1], "publish:" + CHILDREN[1], "published:" + CHILDREN[1],
                      "claim:" + CHILDREN[0], "publish:" + CHILDREN[0], "published:" + CHILDREN[0]]
