"""
SCRUM-164: Revise Arrangements and Resubmit for Safety Check

User Story
----------
As an Event Coordinator, I want to see the Safety Officer's feedback and revise
the affected arrangements, so that I can resubmit the event for a safety check
without redoing unaffected planning.

Acceptance Criteria
-------------------
AC1: Given my event is 'Safety Changes Requested', when I open it, then I see
     the decision, reason, requested changes and affected areas.
AC2: Given the venue arrangement is flagged, then the affected venue booking
     must be reviewed again by Venue Staff (revised booking or replacement
     request) before the event can be resubmitted.
AC3: Given the technical arrangement is flagged, then the affected equipment
     requests that were previously 'Approved' return to 'Pending' and must be
     approved again by Technical Support Staff before the event can be
     resubmitted. The safety-change action does not reopen existing 'Rejected'
     requests or clear their rejection reasons, and requests already 'Pending'
     remain 'Pending'.
AC4: Given an arrangement was not flagged, then it stays confirmed and does not
     need to be reviewed again.
AC5: Given all flagged arrangements are confirmed again, when I resubmit, then
     the status returns to 'Pending Safety Check' as a new review round, and
     earlier rounds remain in the history.

Real
----
- Resubmitting after changes were requested: only once every flagged
  arrangement is approved again (a rejected equipment request no longer blocks;
  a rejected venue is replaced by its new booking), opening a new round while
  the earlier ones stay in the history; plus the readiness check the page uses
  first.
- We check the result the coordinator sees, and what is recorded.

Doubled
-------
- Event, Safety Check Record, Venue Availability, Venue, Equipment Request and
  User Services: answer as each test needs, fail, or do not answer in time
  [Stub]; we check which were asked, in what order, and what they were sent
  [Mock].
- Sign-in: a test key signs the caller's token (tests/conftest.py) [Stub].

Not proven
----------
- That the flagged bookings and equipment requests really went back for review
  (-> test_scrum151_reject_or_request_changes.py and the other services'
  tests).
"""

import pytest

from app import clients, create_app
from tests.unit.factories import COORDINATOR_ID, EVENT_ID, booking, equipment_request, event, record, signed_in


@pytest.fixture
def downstream(submission_downstream):
    return submission_downstream


@pytest.fixture
def client():
    return signed_in(create_app().test_client())


def resubmit(client, **overrides):
    return client.post("/safety-checks/resubmit", json={
        "eventId": EVENT_ID, "coordinatorId": COORDINATOR_ID, **overrides,
    })


def test_resubmit_with_approved_arrangements_opens_next_round(client, downstream):
    """
    Summary: With every flagged arrangement approved again, resubmitting opens a new round.
    AC5: Given all flagged arrangements are confirmed again, when I resubmit,
        then the status returns to 'Pending Safety Check' as a new review
        round, and earlier rounds remain in the history.
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    downstream.event = event("Safety Changes Requested")
    downstream.rounds = [record(1, "Changes Requested")]
    downstream.created = record(2)
    downstream.requests = [equipment_request("Approved")]

    response = resubmit(client, equipmentPlacementNotes=PLACEMENT, crowdMovementNotes=CROWD)

    assert response.status_code == 201
    assert response.json["safetyCheck"]["roundNumber"] == 2
    assert response.json["event"]["status"] == "Pending Safety Check"
    assert downstream.call("create") == ("create", EVENT_ID, COORDINATOR_ID, PLACEMENT, CROWD)
    assert "bookings" in downstream.names()
    assert "delete" not in downstream.names()
    assert downstream.rounds[0]["status"] == "Changes Requested"


def test_resubmit_with_pending_equipment_is_blocked_before_writes(client, downstream):
    """
    Summary: A pending equipment request blocks resubmission before anything is written.
    AC3: Given the technical arrangement is flagged, then the affected
        equipment requests that were previously 'Approved' return to 'Pending'
        and must be approved again by Technical Support Staff before the event
        can be resubmitted. The safety-change action does not reopen existing
        'Rejected' requests or clear their rejection reasons, and requests
        already 'Pending' remain 'Pending'.
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    downstream.event = event("Safety Changes Requested")
    downstream.requests = [equipment_request("Pending")]

    response = resubmit(client)

    assert response.status_code == 422
    assert response.json["outstanding"][0]["status"] == "Pending"
    assert "create" not in downstream.names()
    assert "bookings" in downstream.names()


@pytest.mark.parametrize("requests", [[], [equipment_request("Approved")]], ids=["empty", "equipment_request_approved"])
def test_resubmit_readiness_with_approved_arrangements_is_ready(client, downstream, requests):
    """
    Summary: Resubmission readiness is true with an approved venue and no or approved equipment.
    AC5: Given all flagged arrangements are confirmed again, when I resubmit,
        then the status returns to 'Pending Safety Check' as a new review
        round, and earlier rounds remain in the history.
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    downstream.event = event("Safety Changes Requested")
    downstream.requests = requests

    response = client.get("/safety-checks/resubmit/readiness", query_string={"eventId": EVENT_ID, "coordinatorId": COORDINATOR_ID})

    assert response.status_code == 200
    assert response.json == {"ready": True, "eventStatus": "Safety Changes Requested", "outstanding": []}
    assert "bookings" in downstream.names()


@pytest.mark.parametrize("venue_status,equipment_status", [("Pending Review", "Approved"), ("Rejected", "Approved")])
def test_resubmit_with_unready_venue_is_blocked(client, downstream, venue_status, equipment_status):
    """
    Summary: A venue booking that is not approved again blocks resubmission.
    AC2: Given the venue arrangement is flagged, then the affected venue
        booking must be reviewed again by Venue Staff (revised booking or
        replacement request) before the event can be resubmitted.
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    downstream.event = event("Safety Changes Requested")
    downstream.bookings = [booking(venue_status)]

    downstream.requests = [equipment_request(equipment_status)]

    assert resubmit(client).status_code == 422
    response = client.get(f"/safety-checks/resubmit/readiness?eventId={EVENT_ID}&coordinatorId={COORDINATOR_ID}")
    assert response.json["ready"] is False
    assert "create" not in downstream.names()


def test_resubmit_ignores_rejected_equipment(client, downstream):
    """
    Summary: A rejected equipment request no longer blocks resubmission.
    AC3: Given the technical arrangement is flagged, then the affected
        equipment requests that were previously 'Approved' return to 'Pending'
        and must be approved again by Technical Support Staff before the event
        can be resubmitted. The safety-change action does not reopen existing
        'Rejected' requests or clear their rejection reasons, and requests
        already 'Pending' remain 'Pending'.
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    downstream.event = event("Safety Changes Requested")
    downstream.rounds = [record(1, "Changes Requested")]
    downstream.created = record(2)
    downstream.requests = [equipment_request("Rejected")]

    response = client.get(f"/safety-checks/resubmit/readiness?eventId={EVENT_ID}&coordinatorId={COORDINATOR_ID}")

    assert response.json == {"ready": True, "eventStatus": "Safety Changes Requested", "outstanding": []}
    assert "create" not in downstream.names()
    response = resubmit(client)
    assert response.status_code == 201
    assert response.json["safetyCheck"]["roundNumber"] == 2
    assert "patch_event" in downstream.names()


def test_resubmit_readiness_with_pending_equipment_or_wrong_stage_is_not_ready(client, downstream):
    """
    Summary: Resubmission readiness is false with pending equipment or outside 'Safety Changes Requested'.
    AC3: Given the technical arrangement is flagged, then the affected
        equipment requests that were previously 'Approved' return to 'Pending'
        and must be approved again by Technical Support Staff before the event
        can be resubmitted. The safety-change action does not reopen existing
        'Rejected' requests or clear their rejection reasons, and requests
        already 'Pending' remain 'Pending'.
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    downstream.event = event("Safety Changes Requested")
    downstream.requests = [equipment_request("Pending")]
    url = f"/safety-checks/resubmit/readiness?eventId={EVENT_ID}&coordinatorId={COORDINATOR_ID}"

    assert client.get(url).json["ready"] is False
    downstream.event = event("Approved")
    downstream.requests = []
    assert client.get(url).json["ready"] is False
    assert resubmit(client).status_code == 409


def test_resubmit_readiness_with_bad_ids_returns_400(client, downstream):
    """
    Summary: Checking resubmission must name a real event.
    AC5: Given all flagged arrangements are confirmed again, when I resubmit,
        then the status returns to 'Pending Safety Check' as a new review
        round, and earlier rounds remain in the history.
    Double: None
    """
    assert client.get("/safety-checks/resubmit/readiness?eventId=bad").status_code == 400
    assert downstream.calls == []


@pytest.mark.parametrize("error,code", [(clients.EventNotAssignedError(), 403), (clients.EventNotFoundError(), 404)], ids=["clients_eventnotassignederror_403", "clients_eventnotfounderror_404"])
def test_resubmit_when_not_assigned_is_refused_before_equipment_read(client, downstream, error, code):
    """
    Summary: A coordinator who is not assigned, or a missing event, stops resubmission before equipment is read.
    AC5: Given all flagged arrangements are confirmed again, when I resubmit,
        then the status returns to 'Pending Safety Check' as a new review
        round, and earlier rounds remain in the history.
    Double: Event Service says the caller is not the event's coordinator, or
        does not know the event [Stub].
    """
    downstream.fail["get_event"] = error

    assert resubmit(client).status_code == code
    assert client.get(f"/safety-checks/resubmit/readiness?eventId={EVENT_ID}&coordinatorId={COORDINATOR_ID}").status_code == code
    assert "requests" not in downstream.names()


@pytest.mark.parametrize("error,code", [(clients.DownstreamError(), 502), (clients.DownstreamTimeout(), 504)], ids=["clients_downstreamerror_502", "clients_downstreamtimeout_504"])
def test_resubmit_when_equipment_unreadable_fails_closed(client, downstream, error, code):
    """
    Summary: If equipment requests cannot be read, resubmission fails closed.
    AC3: Given the technical arrangement is flagged, then the affected
        equipment requests that were previously 'Approved' return to 'Pending'
        and must be approved again by Technical Support Staff before the event
        can be resubmitted. The safety-change action does not reopen existing
        'Rejected' requests or clear their rejection reasons, and requests
        already 'Pending' remain 'Pending'.
    Double: Equipment Request fails or does not answer in time [Stub].
    """
    downstream.event = event("Safety Changes Requested")
    downstream.fail["requests"] = error

    assert resubmit(client).status_code == code
    assert client.get(f"/safety-checks/resubmit/readiness?eventId={EVENT_ID}&coordinatorId={COORDINATOR_ID}").status_code == code
    assert "create" not in downstream.names()


@pytest.mark.parametrize("replacement, ready, status", [
    ("Approved", True, 201), (None, False, 422), ("Pending Review", False, 422),
])
def test_resubmit_after_rejected_venue_uses_replacement_booking(client, downstream, replacement, ready, status):
    """
    Summary: After a rejected venue, readiness follows the replacement booking's live status.
    AC2: Given the venue arrangement is flagged, then the affected venue
        booking must be reviewed again by Venue Staff (revised booking or
        replacement request) before the event can be resubmitted.
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    downstream.bookings = [booking("Rejected")]
    if replacement:
        downstream.bookings.append(booking(replacement, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"))

    result = readiness(client)

    assert result.json["ready"] is ready
    if replacement is None:
        assert result.json["outstanding"][0]["label"] == "No venue booking"
    elif not ready:
        assert [item["status"] for item in result.json["outstanding"]] == [replacement]
    response = submit(client)
    assert response.status_code == status
    if not ready:
        assert response.json["code"] == "ARRANGEMENTS_OUTSTANDING"
        assert "create" not in downstream.names()
        assert "patch_event" not in downstream.names()


PLACEMENT = "Speakers either side of the stage, cables taped along the left wall."


def readiness(client, event_id=EVENT_ID, coordinator_id=COORDINATOR_ID):
    return client.get(
        f"/safety-checks/readiness?eventId={event_id}&coordinatorId={coordinator_id}"
    )


CROWD = "Entry through Door A, exit through Doors B and C; queue in the foyer."


def submit(client, **overrides):
    body = {"eventId": EVENT_ID, "coordinatorId": COORDINATOR_ID, **overrides}
    return client.post("/safety-checks", json=body)
