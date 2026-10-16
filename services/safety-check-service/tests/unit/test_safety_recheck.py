"""SCRUM-153: POST /safety-checks/recheck.

AC1 Given an event is 'Confirmed', when its date/time, expected attendance,
    venue requirements, equipment requirements or accessibility needs change,
    then its status returns to 'Pending Safety Check' and the coordinator is
    told why.
AC2 Given only a low-impact field changes (name, description, purpose,
    registration needs), then the event stays 'Confirmed' — so this route
    refuses to withdraw anything for such an edit.
AC3 Given a safety approval is withdrawn, then it stays visible in the event's
    safety history — round N is withdrawn, not deleted, and comes back in the
    response next to the new round.

The withdrawal writes two entities owned by two atomics (`Event` and
`SafetyCheck`), and atomics never call each other, so the workflow is a
composite (AGENTS.md). Record first, then event, as in SCRUM-149 to 151: the
record service's row lock is the race guard.

Every downstream call is a monkeypatched `app.clients` wrapper, so these tests
exercise the orchestration and the error mapping, not HTTP (`test_clients.py`
covers that).
"""
import logging

import pytest

from app import clients, create_app
from app.routes import HIGH_IMPACT_FIELDS, LOW_IMPACT_FIELDS
from tests.unit.factories import (
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

    def get_event(self, event_id, viewer_id, viewer_role=None):
        self.calls.append(("get_event", event_id, viewer_id, viewer_role))
        self._maybe_fail("get_event")
        return self.event

    def list_safety_check_records(self, event_id, status=None):
        self.calls.append(("list_records", event_id, status))
        self._maybe_fail("list_records")
        return self.rounds

    def withdraw_safety_approval(self, round_id, withdrawn_by, reason):
        self.calls.append(("withdraw", round_id, withdrawn_by, reason))
        self._maybe_fail("withdraw")
        return self.withdrawn, self.opened

    def restore_safety_approval(self, round_id, opened_round_id):
        self.calls.append(("restore", round_id, opened_round_id))
        self._maybe_fail("restore")
        return self.rounds[0]

    def update_event_details(self, event_id, coordinator_id, changes, safety_recheck):
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
    return create_app().test_client()


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


def test_a_recheck_withdraws_the_approval_and_saves_the_edit(client, downstream):
    """AC1/AC3: round N is withdrawn, round N+1 opens, the event moves back."""
    response = recheck(client)

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


def test_the_event_is_read_as_the_assigned_coordinator(client, downstream):
    """Event Service answers 403 for a stranger, so this needn't check itself."""
    recheck(client)

    assert downstream.call("get_event") == ("get_event", EVENT_ID, COORDINATOR_ID, None)


def test_the_withdrawal_reason_names_the_changed_details(client, downstream):
    """AC1 "told why": the reason is stored on round N and echoed to the caller."""
    response = recheck(
        client,
        {"expectedAttendance": "400", "venueRequirements": "Hall B, with a stage"},
    )

    reason = "Expected attendance and Venue requirements changed after safety approval."
    assert response.json["reason"] == reason
    assert downstream.call("withdraw") == (
        "withdraw",
        RECORD_ID,
        COORDINATOR_ID,
        reason,
    )


def test_both_date_fields_read_as_one_label(client, downstream):
    """Changing start and end is one "Date/time" change, said once."""
    response = recheck(
        client,
        {
            "preferredStartDate": "2026-11-10T08:00:00",
            "preferredEndDate": "2026-11-10T18:00:00",
        },
    )

    assert response.json["reason"] == "Date/time changed after safety approval."


def test_the_edit_is_sent_with_both_round_ids_for_the_gate(client, downstream):
    """Event Service re-checks the withdrawn round under its own lock."""
    changes = {"expectedAttendance": "400", "eventName": "Renamed"}
    recheck(client, changes)

    _name, event_id, coordinator_id, sent_changes, safety_recheck = downstream.call(
        "patch_details"
    )
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
def test_each_high_impact_field_triggers_a_recheck(field, client, downstream):
    """AC1: each of the five AC1 details alone invalidates the review."""
    response = recheck(client, {field: HIGH_IMPACT_CHANGES[field]})

    assert response.status_code == 200
    assert response.json["changedFields"] == [field]
    assert "withdraw" in downstream.names()


def test_bookings_and_equipment_are_never_touched(client, downstream):
    """Round N+1 is reviewed as it stands; the officer requests changes if needed.

    Nothing here calls Venue Availability, Equipment Request or User Service,
    so a re-check can't release an arrangement the event still needs.
    """
    recheck(client)

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
def test_only_a_confirmed_event_can_be_rechecked(status, client, downstream):
    """Only a 'Confirmed' event holds an approval, so there is nothing else to withdraw."""
    downstream.event = event(status)

    response = recheck(client)

    assert response.status_code == 409
    assert response.json["code"] == "RECHECK_NOT_NEEDED"
    assert response.json["currentStatus"] == status
    assert_no_writes(downstream)


@pytest.mark.parametrize("field", list(LOW_IMPACT_FIELDS))
def test_a_low_impact_edit_is_refused(field, client, downstream):
    """AC2: the event stays 'Confirmed', so this route has nothing to do."""
    response = recheck(client, {field: LOW_IMPACT_CHANGES[field]})

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
)
def test_resending_unchanged_values_withdraws_nothing(changes, client, downstream):
    """AC2: "changed" is decided on normalised values, as Event Service decides it.

    Catching this here means a no-op edit never withdraws an approval that
    then has to be compensated back.
    """
    response = recheck(client, changes)

    assert response.status_code == 409
    assert response.json["code"] == "RECHECK_NOT_NEEDED"
    assert_no_writes(downstream)


def test_filling_in_a_date_the_event_never_had_is_a_change(client, downstream):
    """A blank stored date is not "the same as" a real one."""
    downstream.event = event("Confirmed", preferredStartDate="")

    response = recheck(client, {"preferredStartDate": "2026-11-10T08:00:00"})

    assert response.status_code == 200
    assert response.json["changedFields"] == ["preferredStartDate"]


def test_a_malformed_stored_date_is_compared_as_text(client, downstream):
    """Defensive: an unparseable date is still comparable, so this can't 500."""
    downstream.event = event("Confirmed", preferredStartDate="not-a-date")

    response = recheck(client, {"preferredStartDate": "not-a-date"})

    assert response.status_code == 409
    assert response.json["code"] == "RECHECK_NOT_NEEDED"


# --- Access and input ---------------------------------------------------------


def test_a_stranger_is_refused(client, downstream):
    downstream.fail["get_event"] = clients.EventNotAssignedError()

    response = recheck(client)

    assert response.status_code == 403
    assert response.json["code"] == "NOT_ASSIGNED_COORDINATOR"
    assert_no_writes(downstream)


def test_a_missing_event_is_404(client, downstream):
    downstream.fail["get_event"] = clients.EventNotFoundError()

    response = recheck(client)

    assert response.status_code == 404
    assert_no_writes(downstream)


@pytest.mark.parametrize(
    "body",
    [
        {"eventId": "nope", "coordinatorId": COORDINATOR_ID},
        {"eventId": EVENT_ID, "coordinatorId": "nope"},
        {"eventId": EVENT_ID},
        {"coordinatorId": OTHER_COORDINATOR_ID},
        {},
    ],
)
def test_bad_identifiers_are_rejected(body, client, downstream):
    response = client.post(
        "/safety-checks/recheck", json={**body, "changes": {"expectedAttendance": "400"}}
    )

    assert response.status_code == 400
    assert response.json["message"] == "eventId and coordinatorId must be valid UUIDs."
    assert downstream.names() == []


@pytest.mark.parametrize("changes", [{}, None, [], "eventName", 7])
def test_changes_must_be_a_non_empty_object(changes, client, downstream):
    response = recheck(client, changes)

    assert response.status_code == 400
    assert response.json["message"] == (
        "changes must be a non-empty object of fields to update."
    )
    assert downstream.names() == []


@pytest.mark.parametrize("field", ["status", "coordinatorId", "id"])
def test_fields_that_are_not_editable_are_rejected(field, client, downstream):
    response = recheck(client, {field: "whatever"})

    assert response.status_code == 400
    assert field in response.json["message"]
    assert downstream.names() == []


def test_every_change_value_must_be_text(client, downstream):
    response = recheck(client, {"expectedAttendance": 400})

    assert response.status_code == 400
    assert response.json["message"] == "Every value in changes must be text."
    assert downstream.names() == []


def test_a_non_object_body_is_rejected(client, downstream):
    response = client.post("/safety-checks/recheck", json=["not", "an", "object"])

    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    assert downstream.names() == []


# --- Races and data drift -----------------------------------------------------


@pytest.mark.parametrize(
    "status", ["Pending", "Changes Requested", "Safety Rejected", "Approval Withdrawn"]
)
def test_a_latest_round_that_is_not_approved_is_refused(status, client, downstream):
    """Data drift: the event says 'Confirmed' but no round is in force."""
    downstream.rounds = [record(round_number=2, status=status)]

    response = recheck(client)

    assert response.status_code == 409
    assert response.json["code"] == "NO_APPROVED_SAFETY_CHECK"
    assert_no_writes(downstream)


def test_an_event_with_no_rounds_at_all_is_refused(client, downstream):
    downstream.rounds = []

    response = recheck(client)

    assert response.status_code == 409
    assert response.json["code"] == "NO_APPROVED_SAFETY_CHECK"
    assert response.json["safetyCheck"] is None
    assert_no_writes(downstream)


def test_a_concurrent_recheck_wins_the_race(client, downstream):
    """The record service's lock decides. The loser never touches the event."""
    downstream.fail["withdraw"] = clients.RoundNotApprovedError(
        "ROUND_NOT_APPROVED",
        {
            "code": "ROUND_NOT_APPROVED",
            "message": "Only an approved safety check can have its approval withdrawn.",
            "safetyCheck": record(round_number=2, status="Approval Withdrawn"),
        },
    )

    response = recheck(client)

    assert response.status_code == 409
    assert response.json["code"] == "ROUND_NOT_APPROVED"
    assert response.json["safetyCheck"]["status"] == "Approval Withdrawn"
    assert "patch_details" not in downstream.names()
    assert "restore" not in downstream.names()


def test_a_withdraw_conflict_with_no_body_still_reports_the_race(client, downstream):
    downstream.fail["withdraw"] = clients.RoundNotApprovedError(None, {})

    response = recheck(client)

    assert response.status_code == 409
    assert response.json["code"] == "ROUND_NOT_APPROVED"
    assert "already been withdrawn" in response.json["message"]


def test_a_round_that_vanished_is_reported_as_no_approval(client, downstream):
    downstream.fail["withdraw"] = clients.RecordNotFoundError()

    response = recheck(client)

    assert response.status_code == 409
    assert response.json["code"] == "NO_APPROVED_SAFETY_CHECK"
    assert "patch_details" not in downstream.names()


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamTimeout(), 504), (clients.DownstreamError(), 502)],
)
def test_a_failed_withdrawal_touches_nothing_else(error, status, client, downstream):
    downstream.fail["withdraw"] = error

    response = recheck(client)

    assert response.status_code == status
    assert "patch_details" not in downstream.names()
    assert "restore" not in downstream.names()


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamTimeout(), 504), (clients.DownstreamError(), 502)],
)
def test_an_unreadable_round_list_blocks_the_recheck(error, status, client, downstream):
    """Fail closed: an unreadable round is never treated as "nothing approved"."""
    downstream.fail["list_records"] = error

    response = recheck(client)

    assert response.status_code == status
    assert_no_writes(downstream)


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamTimeout(), 504), (clients.DownstreamError(), 502)],
)
def test_an_unreadable_event_blocks_the_recheck(error, status, client, downstream):
    downstream.fail["get_event"] = error

    response = recheck(client)

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
def test_a_failed_edit_restores_the_approval(
    error, expected_status, client, downstream
):
    """The withdrawal is undone, so the event never reads 'Confirmed' with no approval."""
    downstream.fail["patch_details"] = error

    response = recheck(client)

    assert response.status_code == expected_status
    assert downstream.call("restore") == ("restore", RECORD_ID, NEXT_RECORD_ID)


def test_event_services_refusal_is_passed_through_verbatim(client, downstream):
    """Event Service is the authority on the fields, the gate and the status."""
    downstream.fail["patch_details"] = clients.EventDetailsRejectedError(
        "EVENT_UNDER_SAFETY_REVIEW",
        {"code": "EVENT_UNDER_SAFETY_REVIEW", "message": "Wait for the decision."},
        409,
    )

    response = recheck(client)

    assert response.status_code == 409
    assert response.json == {
        "code": "EVENT_UNDER_SAFETY_REVIEW",
        "message": "Wait for the decision.",
    }


def test_a_failed_restore_is_logged_with_both_ids(client, downstream, caplog):
    """Nothing left to try: both ids go to the log and the original error is returned."""
    downstream.fail["patch_details"] = clients.DownstreamError()
    downstream.fail["restore"] = clients.DownstreamError()

    with caplog.at_level(logging.ERROR):
        response = recheck(client)

    assert response.status_code == 502
    assert RECORD_ID in caplog.text
    assert NEXT_RECORD_ID in caplog.text
    assert "must be fixed by hand" in caplog.text


def test_the_two_field_sets_match_event_services():
    """They are copied, not shared (AGENTS.md), so pin that they still agree."""
    from app.routes import EDITABLE_FIELDS, FIELD_LABELS

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
