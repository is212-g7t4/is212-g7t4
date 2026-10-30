"""
SCRUM-20: Event Information Management & Impact Validation

User Story
----------
As the Event Coordinator assigned to an event, I want to update event
information during the planning process, so that event details remain up to
date without introducing conflicts with arrangements already made for the
event.

Acceptance Criteria
-------------------
AC1: Given a field being updated is one of the low-impact fields (Event Name,
     Description, Purpose, Registration Needs), when the assigned Event
     Coordinator saves the change, then the update is applied and the system
     records the new information.
AC2: Given a field being updated is one of the high-impact fields (Date/Time,
     Expected Attendance, Venue Requirements, Equipment Requirements,
     Accessibility Needs), when the assigned Event Coordinator attempts to save
     the change, then the system checks the update against other arrangements
     already made for the event (e.g. confirmed venue bookings, equipment
     reservations) for contradictions before the change is applied.
AC3: Given a high-impact update contradicts an existing arrangement, the update
     is blocked and the Coordinator is shown the reason.
AC4: Given a high-impact update passes validation with no contradiction found,
     then the update is applied and saved.

Real
----
- PATCH /events/<id>/details: the dry-run preview through Event Service, the
  high-impact arrangement checks, the 409 with reasons on a contradiction, the
  actor-role forwarding and the save run for real.
- Assertions are on the status, reasons and which downstream calls are made.

Doubled
-------
- Event, User, Venue Availability, Venue, Equipment Request and Equipment
  Services: Stub (`downstream` / `world` fixtures) - canned answers set per
  test; calls recorded so tests can assert what was (or was not) read or saved.

Not proven
----------
- Which fields are low or high impact: Event Service decides that (->
  event-service unit tests for SCRUM-20).
- That the coordinator sees the reason in the UI (-> frontend
  EventEditDialog.test.tsx).
"""
import pytest

from app import clients, create_app
from tests.unit.factories import signed_in

EVENT_ID = "00000000-0000-0000-0000-000000000001"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
EVENT = {"id": EVENT_ID, "expectedAttendance": "100"}


@pytest.fixture
def client():
    return signed_in(create_app().test_client(), COORDINATOR_ID)


def patch(client, changes=None, **overrides):
    body = {"changes": changes or {"eventName": "New"}}
    body.update(overrides)
    return client.patch(f"/events/{EVENT_ID}/details", json=body)


def preview(high=(), changed=("eventName",)):
    return {
        "event": EVENT,
        "changedFields": list(changed),
        "highImpactFields": list(high),
        "labels": [],
    }


@pytest.fixture
def downstream(monkeypatch):
    calls = {"previewed": [], "saved": [], "checked": []}
    state = {"role": "Event Coordinator", "preview": preview(), "conflicts": []}

    monkeypatch.setattr(clients, "get_user", lambda user_id: {"role": state["role"]})

    def fake_preview(event_id, changes, actor_role=None):
        calls["previewed"].append(actor_role)
        return state["preview"]

    def fake_save(event_id, changes, actor_role=None):
        calls["saved"].append(changes)
        return {"id": event_id, "status": "Approved"}

    def fake_conflicts(event, changes, high):
        calls["checked"].append(high)
        return state["conflicts"]

    monkeypatch.setattr(clients, "preview_event_details", fake_preview)
    monkeypatch.setattr(clients, "save_event_details", fake_save)
    monkeypatch.setattr("app.checks.find_conflicts", fake_conflicts)
    return calls, state


def test_update_details_with_low_impact_change_saves_without_arrangement_checks(client, downstream):
    """
    Summary: A low-impact edit is saved straight away with no arrangement checks.
    AC1: Given a field being updated is one of the low-impact fields (Event
        Name, Description, Purpose, Registration Needs), when the assigned
        Event Coordinator saves the change, then the update is applied and the
        system records the new information.
    Double: Stub (preview says low impact), Mock (save called)
    """
    # Arrange (Given)
    calls, _ = downstream

    # Act (When)
    response = patch(client)

    # Assert (Then)
    assert response.status_code == 200
    assert calls["saved"] == [{"eventName": "New"}]
    assert calls["checked"] == []


def test_update_details_with_high_impact_change_and_no_conflict_saves(client, downstream):
    """
    Summary: A high-impact edit that contradicts nothing is checked and then saved.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    AC4: Given a high-impact update passes validation with no contradiction
        found, then the update is applied and saved.
    Double: Stub (preview high impact; arrangements fit), Mock (save called)
    """
    # Arrange (Given)
    calls, state = downstream
    state["preview"] = preview(high=["expectedAttendance"], changed=["expectedAttendance"])

    # Act (When)
    response = patch(client, {"expectedAttendance": "80"})

    # Assert (Then)
    assert response.status_code == 200
    assert calls["checked"] == [["expectedAttendance"]]
    assert len(calls["saved"]) == 1


def test_update_details_with_contradiction_returns_409_with_reasons(client, downstream):
    """
    Summary: A high-impact edit that contradicts an arrangement is blocked and the reason shown.
    AC3: Given a high-impact update contradicts an existing arrangement, the
        update is blocked and the Coordinator is shown the reason.
    Double: Stub (arrangements conflict), Mock (save not called)
    """
    # Arrange (Given)
    calls, state = downstream
    state["preview"] = preview(high=["expectedAttendance"], changed=["expectedAttendance"])
    state["conflicts"] = [{"field": "expectedAttendance", "area": "venue", "message": "Too many."}]

    # Act (When)
    response = patch(client, {"expectedAttendance": "900"})

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "CHANGE_CONTRADICTS_ARRANGEMENTS"
    assert response.json["conflicts"] == state["conflicts"]
    assert calls["saved"] == []


def test_update_details_by_lead_sends_lead_role_to_event_service(client, downstream):
    """
    Summary: The Lead's edits reach Event Service as the Lead.
    AC1: Given a field being updated is one of the low-impact fields (Event
        Name, Description, Purpose, Registration Needs), when the assigned
        Event Coordinator saves the change, then the update is applied and the
        system records the new information.
    Double: Mock (preview and save record the actor role)
    """
    # Arrange (Given)
    calls, state = downstream
    state["role"] = "Event Coordinator Lead"

    # Act (When)
    patch(client)

    # Assert (Then)
    assert calls["previewed"] == ["Event Coordinator Lead"]


def test_update_details_by_coordinator_leaves_assignment_check_to_event_service(client, downstream):
    """
    Summary: For a coordinator, Event Service decides whether they are the assigned one.
    AC1: Given a field being updated is one of the low-impact fields (Event
        Name, Description, Purpose, Registration Needs), when the assigned
        Event Coordinator saves the change, then the update is applied and the
        system records the new information.
    Double: Mock (preview records no actor role)
    """
    # Arrange (Given)
    calls, _ = downstream

    # Act (When)
    patch(client)

    # Assert (Then)
    assert calls["previewed"] == [None]


def test_update_details_by_unknown_user_returns_403(client, monkeypatch):
    """
    Summary: A signed-in user with no profile cannot edit.
    AC1: Given a field being updated is one of the low-impact fields (Event
        Name, Description, Purpose, Registration Needs), when the assigned
        Event Coordinator saves the change, then the update is applied and the
        system records the new information.
    Double: Stub (User Service has no profile)
    """
    # Arrange (Given)
    def missing(user_id):
        raise clients.UserNotFoundError

    monkeypatch.setattr(clients, "get_user", missing)

    # Act (When)
    response = patch(client)

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["code"] == "NOT_ASSIGNED_COORDINATOR"


@pytest.mark.parametrize("status", [400, 403, 404, 409], ids=["bad_request", "forbidden", "not_found", "conflict"])
def test_update_details_when_event_service_refuses_returns_its_status(client, downstream, monkeypatch, status):
    """
    Summary: Event Service's own refusals reach the coordinator unchanged.
    AC1: Given a field being updated is one of the low-impact fields (Event
        Name, Description, Purpose, Registration Needs), when the assigned
        Event Coordinator saves the change, then the update is applied and the
        system records the new information.
    Double: Stub (preview raises the refusal)
    """
    # Arrange (Given)
    def refuse(*args, **kwargs):
        raise clients.EventRejectedError(status, {"code": "X", "message": "No."})

    monkeypatch.setattr(clients, "preview_event_details", refuse)

    # Act (When)
    response = patch(client)

    # Assert (Then)
    assert response.status_code == status
    assert response.json == {"code": "X", "message": "No."}


def test_update_details_when_save_needs_safety_recheck_returns_409(client, downstream, monkeypatch):
    """
    Summary: An edit that needs a safety re-check is refused with Event Service's reason.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (save raises SAFETY_RECHECK_REQUIRED)
    """
    # Arrange (Given)
    def gate(*args, **kwargs):
        raise clients.EventRejectedError(409, {"code": "SAFETY_RECHECK_REQUIRED"})

    monkeypatch.setattr(clients, "save_event_details", gate)

    # Act (When)
    response = patch(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_RECHECK_REQUIRED"


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamTimeout, 504), (clients.DownstreamError, 502)],
    ids=["timeout", "downstream_error"],
)
def test_update_details_when_arrangements_unreadable_refuses_change(client, downstream, monkeypatch, error, status):
    """
    Summary: If arrangements cannot be read, the high-impact edit is not saved.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (an arrangement read times out or fails), Mock (save not
        called)
    """
    # Arrange (Given)
    _, state = downstream
    state["preview"] = preview(high=["preferredStartDate"])

    def unreadable(*args, **kwargs):
        raise error

    monkeypatch.setattr("app.checks.find_conflicts", unreadable)

    # Act (When)
    response = patch(client)

    # Assert (Then)
    assert response.status_code == status
    assert "Nothing was changed" in response.json["message"]


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"changes": {}},
        {"changes": {"expectedAttendance": 5}},
    ],
    ids=["no_body", "empty_object", "empty_changes", "bad_change"],
)
def test_update_details_with_malformed_body_returns_400(client, downstream, body):
    """
    Summary: An edit without a proper set of changes is refused.
    AC1: Given a field being updated is one of the low-impact fields (Event
        Name, Description, Purpose, Registration Needs), when the assigned
        Event Coordinator saves the change, then the update is applied and the
        system records the new information.
    Double: None
    """
    # Arrange (Given): client, downstream, body, from fixtures

    # Act (When)
    response = client.patch(f"/events/{EVENT_ID}/details", json=body)

    # Assert (Then)
    assert response.status_code == 400


def test_update_details_with_non_json_body_returns_400(client):
    """
    Summary: A request body that is not JSON is refused.
    AC1: Given a field being updated is one of the low-impact fields (Event
        Name, Description, Purpose, Registration Needs), when the assigned
        Event Coordinator saves the change, then the update is applied and the
        system records the new information.
    Double: None
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.patch(f"/events/{EVENT_ID}/details", data="x")

    # Assert (Then)
    assert response.status_code == 400


def test_update_details_with_bad_event_id_returns_404(client):
    """
    Summary: An edit must name a valid event.
    AC1: Given a field being updated is one of the low-impact fields (Event
        Name, Description, Purpose, Registration Needs), when the assigned
        Event Coordinator saves the change, then the update is applied and the
        system records the new information.
    Double: None
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.patch(
        "/events/not-a-uuid/details",
        json={"changes": {"eventName": "x"}},
    )

    # Assert (Then)
    assert response.status_code == 400


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_health_when_called_returns_ok(client):
    """
    Summary: Anyone can check the service is up.
    Supporting design check: /health answers without a token
    Double: None
    """
    assert client.get("/health").json == {"status": "ok"}


def test_preflight_from_frontend_only_is_allowed(client):
    """
    Summary: Only the frontend gets browser access.
    Supporting design check: CORS for the configured frontend origin
    Double: None
    """
    allowed = client.options("/health", headers={"Origin": "http://localhost:5174"})
    denied = client.options("/health", headers={"Origin": "http://evil.example"})

    assert allowed.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert "Access-Control-Allow-Origin" not in denied.headers


def test_preflight_with_no_frontend_origin_allows_nothing(monkeypatch):
    """
    Summary: With no frontend origin configured, no website gets browser access.
    Supporting design check: CORS for the configured frontend origin
    Double: None
    """
    monkeypatch.setenv("FRONTEND_ORIGIN", "")

    response = signed_in(create_app().test_client()).options("/health", headers={"Origin": "http://localhost:5174"})

    assert "Access-Control-Allow-Origin" not in response.headers
