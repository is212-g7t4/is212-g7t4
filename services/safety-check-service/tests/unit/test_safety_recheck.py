"""
SCRUM-153: Re-check Safety After High-Impact Changes

User Story
----------
As an Event Coordinator, I want a safety approval to be withdrawn when a
high-impact detail changes afterwards, so that the event is never prepared on
the basis of an outdated safety review.

Acceptance Criteria
-------------------
AC1: Given an event is 'Confirmed', when its date/time, expected attendance,
     venue requirements, equipment requirements or accessibility needs change,
     then its status returns to 'Pending Safety Check' and the coordinator is
     told why.
AC2: Given only a low-impact field changes (name, description, purpose,
     registration needs), then the event stays 'Confirmed'.
AC3: Given a safety approval is withdrawn, then it stays visible in the event's
     safety history.
AC4: Given a high-impact change to a 'Confirmed' event is waiting for its new
     safety check, when a registered Attendee views the event, then they still
     see the previously approved details, and the changed details are shown to
     them only after the Safety Officer approves the new safety check.
AC5: Given the new safety check ends without approval (changes requested or the
     event is cancelled), then registered Attendees are never shown the
     unapproved change, and they continue to see the last approved details or
     the cancellation.

Real
----
- POST /safety-checks/recheck: the assigned-coordinator read, the Confirmed
  gate, deciding whether a high-impact field really changes, withdrawing round
  N and opening N+1, saving the edit with both round ids, and restoring on
  failure.
- Assertions are on the status, reason and order of downstream calls.

Doubled
-------
- Event, Safety Check Record, Venue Availability, Venue, Equipment Request,
  Equipment and User Services: Stub (monkeypatched app.clients functions) -
  canned answers or raised client errors; calls recorded so tests assert the
  order and what was (or was not) called.

Not proven
----------
- That the atomic services behave as stubbed, and that a compensation really
  restores state in the database (-> each atomic service's unit and integration
  tests, and tests/integration/ here with respx).
- That attendees keep seeing the approved details meanwhile (AC4, AC5) (->
  event-service and attendee-registration-service tests).
"""
import logging

import pytest
from flask import g

from app import clients, create_app
from app.routes import HIGH_IMPACT_FIELDS, LOW_IMPACT_FIELDS
from tests.unit.factories import (
    signed_in,
    COORDINATOR_ID,
    EVENT_ID,
    OFFICER_ID,
    OTHER_COORDINATOR_ID,
    RECORD_ID,
    event,
    record,
)

NEXT_RECORD_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

# A changed value per field. The start moves earlier and the end later, so any
# one of them alone leaves the event's window valid.
HIGH_IMPACT_CHANGES = {
    "preferredStartDate": "2026-11-10T08:00:00",
    "preferredEndDate": "2026-11-10T18:00:00",
    "expectedAttendance": "400",
    "venueRequirements": "Hall B, with a stage",
    "equipmentRequirements": "Four microphones and a projector",
    "accessibilityNeeds": "Step-free access and a hearing loop",
}
LOW_IMPACT_CHANGES = {
    "eventName": "Community Workshop (Autumn)",
    "description": "A rewritten description of the same workshop.",
    "purpose": "Skills sharing and networking.",
    "registrationNeeds": "Name, email and dietary requirements",
}


class Downstream:
    """Recorded stand-ins for every atomic this composite calls."""

    def __init__(self):
        self.event = event("Confirmed")
        self.rounds = [record(round_number=2, status="Safety Approved", decidedBy=OFFICER_ID)]
        self.withdrawn = record(
            round_number=2,
            status="Approval Withdrawn",
            decidedBy=OFFICER_ID,
            decidedAt="2026-11-02T03:00:00+00:00",
            remarks="Looks safe.",
            withdrawnAt="2026-11-03T04:00:00+00:00",
            withdrawnBy=COORDINATOR_ID,
        )
        self.opened = record(
            round_number=3, status="Pending", id=NEXT_RECORD_ID
        )
        self.updated = event("Pending Safety Check")
        self.calls = []
        self.fail = {}

    def _maybe_fail(self, name):
        if name in self.fail:
            raise self.fail[name]

    def get_event(self, event_id, viewer_role=None):
        viewer_id = g.user_id  # The downstream service reads this from the forwarded token.
        self.calls.append(("get_event", event_id, viewer_id, viewer_role))
        self._maybe_fail("get_event")
        return self.event

    def list_safety_check_records(self, event_id, status=None):
        self.calls.append(("list_records", event_id, status))
        self._maybe_fail("list_records")
        return self.rounds

    def withdraw_safety_approval(self, round_id, reason):
        withdrawn_by = g.user_id  # The downstream service reads this from the forwarded token.
        self.calls.append(("withdraw", round_id, withdrawn_by, reason))
        self._maybe_fail("withdraw")
        return self.withdrawn, self.opened

    def restore_safety_approval(self, round_id, opened_round_id):
        self.calls.append(("restore", round_id, opened_round_id))
        self._maybe_fail("restore")
        return self.rounds[0]

    def update_event_details(self, event_id, changes, safety_recheck):
        coordinator_id = g.user_id  # The downstream service reads this from the forwarded token.
        self.calls.append(
            ("patch_details", event_id, coordinator_id, changes, safety_recheck)
        )
        self._maybe_fail("patch_details")
        return self.updated

    def names(self):
        return [call[0] for call in self.calls]

    def call(self, name):
        return next(call for call in self.calls if call[0] == name)


@pytest.fixture
def downstream(monkeypatch):
    stub = Downstream()
    for name in (
        "get_event",
        "list_safety_check_records",
        "withdraw_safety_approval",
        "restore_safety_approval",
        "update_event_details",
    ):
        monkeypatch.setattr(f"app.clients.{name}", getattr(stub, name))
    return stub


@pytest.fixture
def client():
    return signed_in(create_app().test_client())


DEFAULT_CHANGES = {"expectedAttendance": "400"}
_UNSET = object()


def recheck(client, changes=_UNSET, **overrides):
    body = {
        "eventId": EVENT_ID,
        "coordinatorId": COORDINATOR_ID,
        "changes": DEFAULT_CHANGES if changes is _UNSET else changes,
        **overrides,
    }
    return client.post("/safety-checks/recheck", json=body)


WRITES = ("withdraw", "patch_details", "restore")


def assert_no_writes(downstream):
    assert not set(downstream.names()) & set(WRITES)


# --- AC1, AC3: the happy path -------------------------------------------------


def test_recheck_withdraws_approval_and_saves_edit(client, downstream):
    """
    Summary: A high-impact change withdraws the approval, opens a new round and saves the edit.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    AC3: Given a safety approval is withdrawn, then it stays visible in the
        event's safety history.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given): client, downstream, from fixtures

    # Act (When)
    response = recheck(client)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["event"]["status"] == "Pending Safety Check"
    assert response.json["safetyCheck"]["roundNumber"] == 3
    assert response.json["safetyCheck"]["status"] == "Pending"
    assert response.json["changedFields"] == ["expectedAttendance"]
    # AC3: the withdrawn round comes back too, with its original decision.
    assert response.json["withdrawnSafetyCheck"]["status"] == "Approval Withdrawn"
    assert response.json["withdrawnSafetyCheck"]["decidedBy"] == OFFICER_ID
    assert response.json["withdrawnSafetyCheck"]["remarks"] == "Looks safe."
    # Record first, then event: the record service's lock is the race guard.
    assert downstream.names() == [
        "get_event",
        "list_records",
        "withdraw",
        "patch_details",
    ]


def test_recheck_reads_event_as_assigned_coordinator(client, downstream):
    """
    Summary: The event is read as the coordinator, so a stranger is refused.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given): client, downstream, from fixtures

    # Act (When)
    recheck(client)

    # Assert (Then)
    assert downstream.call("get_event") == ("get_event", EVENT_ID, COORDINATOR_ID, None)


def test_recheck_reason_names_changed_details(client, downstream):
    """
    Summary: The coordinator is told which details caused the re-check.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    response = recheck(
        client,
        {"expectedAttendance": "400", "venueRequirements": "Hall B, with a stage"},
    )

    reason = "Expected attendance and Venue requirements changed after safety approval."

    # Act + Assert (When / Then)
    assert response.json["reason"] == reason
    assert downstream.call("withdraw") == (
        "withdraw",
        RECORD_ID,
        COORDINATOR_ID,
        reason,
    )


def test_recheck_reason_counts_start_and_end_as_one_change(client, downstream):
    """
    Summary: Changing start and end is one date/time change.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given): client, downstream, from fixtures

    # Act (When)
    response = recheck(
        client,
        {
            "preferredStartDate": "2026-11-10T08:00:00",
            "preferredEndDate": "2026-11-10T18:00:00",
        },
    )

    # Assert (Then)
    assert response.json["reason"] == "Date/time changed after safety approval."


def test_recheck_sends_edit_with_both_round_ids(client, downstream):
    """
    Summary: The edit carries both round ids so Event Service can verify it.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    changes = {"expectedAttendance": "400", "eventName": "Renamed"}
    recheck(client, changes)

    # Act (When)
    _name, event_id, coordinator_id, sent_changes, safety_recheck = downstream.call(
        "patch_details"
    )

    # Assert (Then)
    assert event_id == EVENT_ID
    assert coordinator_id == COORDINATOR_ID
    # The whole edit goes through, low-impact fields included: it is one change.
    assert sent_changes == changes
    assert safety_recheck == {
        "withdrawnSafetyCheckId": RECORD_ID,
        "safetyCheckId": NEXT_RECORD_ID,
        "roundNumber": 3,
    }


@pytest.mark.parametrize("field", list(HIGH_IMPACT_FIELDS))
def test_recheck_for_each_high_impact_field_withdraws_approval(field, client, downstream):
    """
    Summary: Each high-impact detail on its own triggers a re-check.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given): field, client, downstream, from fixtures

    # Act (When)
    response = recheck(client, {field: HIGH_IMPACT_CHANGES[field]})

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["changedFields"] == [field]
    assert "withdraw" in downstream.names()


def test_recheck_never_touches_bookings_or_equipment(client, downstream):
    """
    Summary: A re-check leaves bookings and equipment alone.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    recheck(client)

    # Act + Assert (When / Then)
    assert set(downstream.names()) <= {
        "get_event",
        "list_records",
        "withdraw",
        "patch_details",
    }


# --- AC2: nothing to withdraw -------------------------------------------------


@pytest.mark.parametrize(
    "status",
    ["Submitted", "Under Review", "Approved", "Pending Safety Check",
     "Safety Changes Requested", "Rejected", "Cancelled"],
)
def test_recheck_for_unconfirmed_event_returns_409(status, client, downstream):
    """
    Summary: Only a Confirmed event can be re-checked.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.event = event(status)

    # Act (When)
    response = recheck(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "RECHECK_NOT_NEEDED"
    assert response.json["currentStatus"] == status
    assert_no_writes(downstream)


@pytest.mark.parametrize("field", list(LOW_IMPACT_FIELDS))
def test_recheck_with_only_low_impact_change_returns_409(field, client, downstream):
    """
    Summary: A low-impact change does not need a re-check; the event stays Confirmed.
    AC2: Given only a low-impact field changes (name, description, purpose,
        registration needs), then the event stays 'Confirmed'.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given): field, client, downstream, from fixtures

    # Act (When)
    response = recheck(client, {field: LOW_IMPACT_CHANGES[field]})

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "RECHECK_NOT_NEEDED"
    assert "approval stands" in response.json["message"]
    assert_no_writes(downstream)


@pytest.mark.parametrize(
    "changes",
    [
        {"expectedAttendance": "120"},
        {"expectedAttendance": " 120 "},
        {"venueRequirements": " Hall A "},
        {"preferredStartDate": "2026-11-10T09:00"},
        {"preferredStartDate": "2026-11-10T09:00:00.000"},
        {"preferredStartDate": "2026-11-10T01:00:00+00:00"},
    ],
    ids=["expectedattendance_120", "expectedattendance_120_2", "venuerequirements_hall_a", "preferredstartdate_2026_11_10t09_00", "preferredstartdate_2026_11_10t09_00_00_000", "preferredstartdate_2026_11_10t01_00_00_00_00"],
)
def test_recheck_with_unchanged_values_withdraws_nothing(changes, client, downstream):
    """
    Summary: Sending the same values again changes nothing.
    AC2: Given only a low-impact field changes (name, description, purpose,
        registration needs), then the event stays 'Confirmed'.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given): changes, client, downstream, from fixtures

    # Act (When)
    response = recheck(client, changes)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "RECHECK_NOT_NEEDED"
    assert_no_writes(downstream)


def test_recheck_setting_a_missing_date_counts_as_change(client, downstream):
    """
    Summary: Filling in a date the event never had is a change.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.event = event("Confirmed", preferredStartDate="")

    # Act (When)
    response = recheck(client, {"preferredStartDate": "2026-11-10T08:00:00"})

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["changedFields"] == ["preferredStartDate"]


def test_recheck_compares_malformed_stored_date_as_text(client, downstream):
    """
    Summary: An unreadable stored date is still compared.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.event = event("Confirmed", preferredStartDate="not-a-date")

    # Act (When)
    response = recheck(client, {"preferredStartDate": "not-a-date"})

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "RECHECK_NOT_NEEDED"


# --- Access and input ---------------------------------------------------------


def test_recheck_by_other_coordinator_returns_403(client, downstream):
    """
    Summary: Another coordinator cannot re-check the event.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.fail["get_event"] = clients.EventNotAssignedError()

    # Act (When)
    response = recheck(client)

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["code"] == "NOT_ASSIGNED_COORDINATOR"
    assert_no_writes(downstream)


def test_recheck_unknown_event_returns_404(client, downstream):
    """
    Summary: Re-checking an unknown event is refused.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.fail["get_event"] = clients.EventNotFoundError()

    # Act (When)
    response = recheck(client)

    # Assert (Then)
    assert response.status_code == 404
    assert_no_writes(downstream)


@pytest.mark.parametrize(
    "body",
    [
        {"eventId": "nope", "coordinatorId": COORDINATOR_ID},
        {"coordinatorId": OTHER_COORDINATOR_ID},
        {},
    ],
    ids=["eventid_nope_coordinatorid_coordinator_id", "coordinatorid_other_coordinator_id", "empty"],
)
def test_recheck_with_bad_ids_returns_400(body, client, downstream):
    """
    Summary: A re-check needs valid ids.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: None
    """
    # Arrange (Given): body, client, downstream, from fixtures

    # Act (When)
    response = client.post(
        "/safety-checks/recheck", json={**body, "changes": {"expectedAttendance": "400"}}
    )

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "eventId must be a valid UUID."
    assert downstream.names() == []


@pytest.mark.parametrize("changes", [{}, None, [], "eventName", 7], ids=["empty", "none", "empty_2", "eventname", "7"])
def test_recheck_without_changes_returns_400(changes, client, downstream):
    """
    Summary: A re-check needs a set of changes.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: None
    """
    # Arrange (Given): changes, client, downstream, from fixtures

    # Act (When)
    response = recheck(client, changes)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == (
        "changes must be a non-empty object of fields to update."
    )
    assert downstream.names() == []


@pytest.mark.parametrize("field", ["status", "coordinatorId", "id"])
def test_recheck_with_uneditable_field_returns_400(field, client, downstream):
    """
    Summary: Fields that cannot be edited are refused.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: None
    """
    # Arrange (Given): field, client, downstream, from fixtures

    # Act (When)
    response = recheck(client, {field: "whatever"})

    # Assert (Then)
    assert response.status_code == 400
    assert field in response.json["message"]
    assert downstream.names() == []


def test_recheck_with_non_text_value_returns_400(client, downstream):
    """
    Summary: Every changed value must be text.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: None
    """
    # Arrange (Given): client, downstream, from fixtures

    # Act (When)
    response = recheck(client, {"expectedAttendance": 400})

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "Every value in changes must be text."
    assert downstream.names() == []


def test_recheck_with_non_object_body_returns_400(client, downstream):
    """
    Summary: A request that is not a re-check is refused.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: None
    """
    # Arrange (Given): client, downstream, from fixtures

    # Act (When)
    response = client.post("/safety-checks/recheck", json=["not", "an", "object"])

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    assert downstream.names() == []


# --- Races and data drift -----------------------------------------------------


@pytest.mark.parametrize(
    "status", ["Pending", "Changes Requested", "Safety Rejected", "Approval Withdrawn"]
)
def test_recheck_when_latest_round_not_approved_returns_409(status, client, downstream):
    """
    Summary: With no approval in force, there is nothing to withdraw.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.rounds = [record(round_number=2, status=status)]

    # Act (When)
    response = recheck(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "NO_APPROVED_SAFETY_CHECK"
    assert_no_writes(downstream)


def test_recheck_without_rounds_returns_409(client, downstream):
    """
    Summary: An event with no rounds cannot be re-checked.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.rounds = []

    # Act (When)
    response = recheck(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "NO_APPROVED_SAFETY_CHECK"
    assert response.json["safetyCheck"] is None
    assert_no_writes(downstream)


def test_recheck_losing_race_changes_nothing(client, downstream):
    """
    Summary: When two re-checks race, the loser changes nothing.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.fail["withdraw"] = clients.RoundNotApprovedError(
        "ROUND_NOT_APPROVED",
        {
            "code": "ROUND_NOT_APPROVED",
            "message": "Only an approved safety check can have its approval withdrawn.",
            "safetyCheck": record(round_number=2, status="Approval Withdrawn"),
        },
    )

    # Act (When)
    response = recheck(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "ROUND_NOT_APPROVED"
    assert response.json["safetyCheck"]["status"] == "Approval Withdrawn"
    assert "patch_details" not in downstream.names()
    assert "restore" not in downstream.names()


def test_recheck_conflict_without_body_still_reports_race(client, downstream):
    """
    Summary: A conflict without details is still reported as the race.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.fail["withdraw"] = clients.RoundNotApprovedError(None, {})

    # Act (When)
    response = recheck(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "ROUND_NOT_APPROVED"
    assert "already been withdrawn" in response.json["message"]


def test_recheck_when_round_vanishes_reports_no_approval(client, downstream):
    """
    Summary: A round that vanished is reported as no approval.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.fail["withdraw"] = clients.RecordNotFoundError()

    # Act (When)
    response = recheck(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "NO_APPROVED_SAFETY_CHECK"
    assert "patch_details" not in downstream.names()


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamTimeout(), 504), (clients.DownstreamError(), 502)],
    ids=["clients_downstreamtimeout_504", "clients_downstreamerror_502"],
)
def test_recheck_when_withdrawal_fails_changes_nothing_else(error, status, client, downstream):
    """
    Summary: A failed withdrawal leaves the event as it was.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.fail["withdraw"] = error

    # Act (When)
    response = recheck(client)

    # Assert (Then)
    assert response.status_code == status
    assert "patch_details" not in downstream.names()
    assert "restore" not in downstream.names()


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamTimeout(), 504), (clients.DownstreamError(), 502)],
    ids=["clients_downstreamtimeout_504", "clients_downstreamerror_502"],
)
def test_recheck_when_rounds_unreadable_is_refused(error, status, client, downstream):
    """
    Summary: Unreadable rounds are never treated as no approval.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.fail["list_records"] = error

    # Act (When)
    response = recheck(client)

    # Assert (Then)
    assert response.status_code == status
    assert_no_writes(downstream)


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamTimeout(), 504), (clients.DownstreamError(), 502)],
    ids=["clients_downstreamtimeout_504", "clients_downstreamerror_502"],
)
def test_recheck_when_event_unreadable_is_refused(error, status, client, downstream):
    """
    Summary: An unreadable event blocks the re-check.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.fail["get_event"] = error

    # Act (When)
    response = recheck(client)

    # Assert (Then)
    assert response.status_code == status
    assert_no_writes(downstream)


# --- Compensation -------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (
            clients.EventDetailsRejectedError(
                "STALE_SAFETY_CHECK",
                {
                    "code": "STALE_SAFETY_CHECK",
                    "message": "This safety check round is not the approval this event holds.",
                },
                409,
            ),
            409,
        ),
        (
            clients.EventDetailsRejectedError(
                None,
                {
                    "message": "Please correct the event details.",
                    "missingFields": [],
                    "errors": ["Preferred End Date & Time must be after the start."],
                },
                400,
            ),
            400,
        ),
        (clients.EventNotFoundError(), 404),
        (clients.EventNotAssignedError(), 403),
        (clients.ServiceCredentialsError(), 502),
        (clients.DownstreamTimeout(), 504),
        (clients.DownstreamError(), 502),
    ],
    ids=[
        "stale-round",
        "validation",
        "not-found",
        "reassigned",
        "bad-credentials",
        "timeout",
        "transport",
    ],
)
def test_recheck_when_edit_fails_restores_approval(
    error, expected_status, client, downstream
):
    """
    Summary: If the edit fails, the approval is restored.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.fail["patch_details"] = error

    # Act (When)
    response = recheck(client)

    # Assert (Then)
    assert response.status_code == expected_status
    assert downstream.call("restore") == ("restore", RECORD_ID, NEXT_RECORD_ID)


def test_recheck_passes_event_service_refusal_through(client, downstream):
    """
    Summary: Event Service's refusal reaches the coordinator unchanged.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.fail["patch_details"] = clients.EventDetailsRejectedError(
        "EVENT_UNDER_SAFETY_REVIEW",
        {"code": "EVENT_UNDER_SAFETY_REVIEW", "message": "Wait for the decision."},
        409,
    )

    # Act (When)
    response = recheck(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json == {
        "code": "EVENT_UNDER_SAFETY_REVIEW",
        "message": "Wait for the decision.",
    }


def test_recheck_when_restore_fails_logs_both_ids(client, downstream, caplog):
    """
    Summary: When the restore fails too, both round ids are logged for repair.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.fail["patch_details"] = clients.DownstreamError()
    downstream.fail["restore"] = clients.DownstreamError()

    # Act (When)
    with caplog.at_level(logging.ERROR):
        response = recheck(client)

    # Assert (Then)
    assert response.status_code == 502
    assert RECORD_ID in caplog.text
    assert NEXT_RECORD_ID in caplog.text
    assert "must be fixed by hand" in caplog.text


def test_recheck_field_sets_match_event_service():
    """
    Summary: The low and high-impact field lists match Event Service's.
    AC2: Given only a low-impact field changes (name, description, purpose,
        registration needs), then the event stays 'Confirmed'.
    Double: None
    """
    # Act (When)
    from app.routes import EDITABLE_FIELDS, FIELD_LABELS

    # Assert (Then)
    assert set(LOW_IMPACT_FIELDS) | set(HIGH_IMPACT_FIELDS) == set(EDITABLE_FIELDS)
    assert not set(LOW_IMPACT_FIELDS) & set(HIGH_IMPACT_FIELDS)
    assert set(FIELD_LABELS) == set(EDITABLE_FIELDS)
    # Exactly the five details SCRUM-153 AC1 lists (date/time is two fields).
    assert set(HIGH_IMPACT_FIELDS) == {
        "preferredStartDate",
        "preferredEndDate",
        "expectedAttendance",
        "venueRequirements",
        "equipmentRequirements",
        "accessibilityNeeds",
    }
