"""
SCRUM-49: Event Change and Modification Notifications

User Story
----------
As an Event Organiser and Event Coordinator, I want to receive notifications
about event changes that affect me, so that I can respond to changes promptly.

Acceptance Criteria
-------------------
AC1: Given an Event Organiser submits a change request, the system sends an
     in-app notification to the Event Coordinator with the event name, proposed
     changes, and a link to review the request.
AC2: Given an approval or rejection of a change request is successfully
     recorded, the Event Organiser receives an in-app notification with the
     event name, decision, and reason if rejected.
AC3: Given an event is cancelled or rejected, the system sends an in-app
     notification to both the Event Coordinator and Event Organiser confirming
     the cancellation or rejection, respectively, with the event name.

Real
----
- The Event Service routes in app/__init__.py and the rules in app/models.py,
  run through a real create_app(): request validation, the caller's role and
  ownership checks from the signed token, the status rules, and the SQL and
  parameters sent to the database (including notification outbox rows).
- Assertions are on the HTTP status, the response body and the queries and
  parameters the cursor received.

Doubled
-------
- psycopg2.connect: Stub (fixture) - a MagicMock connection whose cursor
  returns canned rows; Mock - its execute calls are asserted to prove what was
  (or was not) written.
- Supabase JWKS: Stub (tests/conftest.py) - tokens are signed with a throwaway
  ES256 key.

Not proven
----------
- That the SQL runs against the real Postgres schema, constraints and row locks
  (-> tests/integration/ against a throwaway postgres:17.6).
- That the notification outbox rows are delivered (-> Notification Service
  tests and the E2E journeys).
"""
import json
from datetime import UTC, datetime

import pytest
from tests.unit.factories import (
    COORDINATOR, EVENT, HEADERS, JOB, LEASE, OFFICER, OUTBOX_HEADERS, ROUND,
    pending_safety_notification_row, safety_outbox_row,
)

ORGANISER = OFFICER
ALL_CHANGES = {
    "eventName": "New Workshop", "description": "Revised description",
    "purpose": "Community learning", "registrationNeeds": "Name and email",
    "preferredStartDate": "2030-03-01T15:59:00+00:00",
    "preferredEndDate": "2030-03-01T16:00:00+00:00",
    "expectedAttendance": "40", "venueRequirements": "Step-free room",
    "equipmentRequirements": "Projector", "accessibilityNeeds": "Hearing loop",
}
# Independent UI copy expectation, not obtained from the production formatter.
ALL_MESSAGE = (
    "Change requested for Workshop. Proposed changes: Event Name: New Workshop; "
    "Description: Revised description; Purpose: Community learning; "
    "Registration Needs: Name and email; Start Date/Time: 01 Mar 2030, 23:59 SGT; "
    "End Date/Time: 02 Mar 2030, 00:00 SGT; Expected Attendance: 40; "
    "Venue Requirements: Step-free room; Equipment Requirements: Projector; "
    "Accessibility Needs: Hearing loop."
)


@pytest.mark.parametrize("changes,message", [
    (ALL_CHANGES, ALL_MESSAGE),
    ({"preferredStartDate": "2030-03-01T09:00:00"},
     "Change requested for Workshop. Proposed changes: Start Date/Time: 01 Mar 2030, 09:00 SGT."),
    ({"expectedAttendance": "40"},
     "Change requested for Workshop. Proposed changes: Expected Attendance: 40."),
], ids=["all-ten-fields-utc-crosses-singapore-midnight", "naive-time-is-singapore-not-host-local", "only-attendance-no-phantom-fields"])
def test_freeze_preserves_all_proposed_values_and_review_target(safety_notification_boundary, changes, message):
    """
    Summary: All fields and aware/naive dates freeze as complete Singapore display text.
    AC1: Given an Event Organiser submits a change request, the system sends an
        in-app notification to the Event Coordinator with the event name,
        proposed changes, and a link to review the request.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, _ = safety_notification_boundary
    source = dict(eventId=EVENT, eventName="Workshop", recipientRole="coordinator",
                  changeRequestId=ROUND, proposedChanges=changes)
    row = safety_outbox_row("event.change-request-submitted", source)
    envelope = dict(version=1, id=JOB, type="event.change-request-submitted",
                    recipientId=COORDINATOR, createdAt="2030-01-01T00:00:00+00:00",
                    message=message, details={**source, "recipientId": COORDINATOR},
                    destination=dict(kind="change-request-review", eventId=EVENT, changeRequestId=ROUND))
    cursor.fetchone.side_effect = [row, {**row, "envelope": envelope}]

    # Act (When)
    response = client.post(f"/internal/notification-outbox/{JOB}/freeze", headers=OUTBOX_HEADERS,
                           json=dict(leaseToken=LEASE, envelope=envelope))

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["envelope"] == envelope
    writes = [call.args[1] for call in cursor.execute.call_args_list if "SET envelope=" in call.args[0]]
    assert len(writes) == 1
    assert writes[0][0].adapted == envelope
    assert writes[0][1] == JOB


@pytest.mark.parametrize("kind,extra,message", [
    ("event.change-request-approved", {"decision": "Approved"}, "Change request for Workshop was approved."),
    ("event.change-request-approved", {"decision": "Approved", "previousEventName": "Old Workshop"},
     "Change request for Workshop (formerly Old Workshop) was approved."),
    ("event.change-request-rejected", {"decision": "Rejected", "reason": "Unsafe exits.\n出口需改善。"},
     "Change request for Workshop was rejected: Unsafe exits.\n出口需改善。"),
], ids=["approved-unchanged-name", "approved-new-name-retains-former-name", "rejected-full-multiline-unicode-reason"])
def test_freeze_keeps_decision_name_and_complete_reason(safety_notification_boundary, kind, extra, message):
    """
    Summary: Decision text retains the former name or complete rejection reason.
    AC2: Given an approval or rejection of a change request is successfully
        recorded, the Event Organiser receives an in-app notification with the
        event name, decision, and reason if rejected.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, _ = safety_notification_boundary
    source = dict(eventId=EVENT, eventName="Workshop", recipientRole="organiser",
                  changeRequestId=ROUND, **extra)
    row = safety_outbox_row(kind, source)
    envelope = dict(version=1, id=JOB, type=kind, recipientId=ORGANISER,
                    createdAt="2030-01-01T00:00:00+00:00", message=message,
                    details={**source, "recipientId": ORGANISER},
                    destination=dict(kind="event-details", eventId=EVENT))
    cursor.fetchone.side_effect = [row, {**row, "envelope": envelope}]

    # Act (When)
    response = client.post(f"/internal/notification-outbox/{JOB}/freeze", headers=OUTBOX_HEADERS,
                           json=dict(leaseToken=LEASE, envelope=envelope))

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["envelope"] == envelope
    writes = [call.args[1] for call in cursor.execute.call_args_list if "SET envelope=" in call.args[0]]
    assert len(writes) == 1
    assert writes[0][0].adapted == envelope
    assert writes[0][1] == JOB


def test_rename_approval_captures_both_names_in_organiser_intent(safety_notification_boundary):
    """
    Summary: Approving a renamed event records both names in the decision's notification intent.
    AC2: Given an approval or rejection of a change request is successfully
        recorded, the Event Organiser receives an in-app notification with the
        event name, decision, and reason if rejected.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, row = safety_notification_boundary
    current = {**row, "organiser_id": ORGANISER, "change_id": ROUND,
               "requested_changes": {"eventName": "New Workshop"},
               "change_request_status": "Pending Review"}
    decided = dict(status="Approved", reviewed_by=COORDINATOR,
                   review_date=datetime(2030, 1, 1, tzinfo=UTC), rejection_reason=None)
    cursor.fetchone.side_effect = [current, {**row, "event_name": "New Workshop"}, decided]

    # Act (When)
    response = client.patch(f"/change-requests/{ROUND}/decision", headers=HEADERS,
                            json=dict(coordinatorId=COORDINATOR, decision="Approved"))

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["event"]["eventName"] == "New Workshop"
    inserts = [call.args[1] for call in cursor.execute.call_args_list
               if 'INSERT INTO public."EventNotificationOutbox"' in call.args[0]]
    assert len(inserts) == 1
    assert inserts[0][1] == "event.change-request-approved"
    assert inserts[0][2].adapted == dict(eventId=EVENT, eventName="New Workshop",
        previousEventName="Workshop", recipientRole="organiser", changeRequestId=ROUND, decision="Approved")
    event_update = next(call.args[1] for call in cursor.execute.call_args_list
                        if 'UPDATE public."Event"' in call.args[0])
    assert event_update[0] == "New Workshop"
    request_update = next(call.args[1] for call in cursor.execute.call_args_list
                          if 'UPDATE public."EventChangeReq"' in call.args[0])
    assert request_update == ["Approved", COORDINATOR, None, ROUND]


@pytest.mark.parametrize("entry", ["reject", "progress"])
def test_event_rejection_keeps_one_organiser_intent_and_notifies_actor(safety_notification_boundary, entry):
    """
    Summary: Either event-rejection route notifies the organiser and assigned coordinator, even the actor.
    AC3: Given an event is cancelled or rejected, the system sends an in-app
        notification to both the Event Coordinator and Event Organiser
        confirming the cancellation or rejection, respectively, with the event
        name.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    # Arrange: only PostgreSQL is doubled; exercise the real route and mutation.
    client, cursor, _ = safety_notification_boundary
    row = {**pending_safety_notification_row(), "status": "Under Review", "organiser_id": ORGANISER}
    reason = "Keep accessible transport.\n交通安排需完善。"
    cursor.fetchone.side_effect = [row, {**row, "status": "Rejected"}]
    body = dict(coordinatorId=COORDINATOR, reason=reason)
    if entry == "progress":
        body = dict(coordinatorId=COORDINATOR, status="Rejected", actionDetails=reason)

    # Act (When)
    # Act
    response = client.patch(f"/events/{EVENT}/{entry}", json=body)

    # Assert (Then)
    # Assert: reuse the organiser alert, not a second organiser notification.
    assert response.status_code == 200, response.json
    assert response.json["status"] == "Rejected"
    inserts = [call.args[1] for call in cursor.execute.call_args_list
               if 'INSERT INTO public."EventNotificationOutbox"' in call.args[0]]
    assert len(inserts) == 2
    assert len({values[0] for values in inserts}) == 2
    assert [values[1] for values in inserts] == ["event.rejection", "event.rejection"]
    assert [values[2].adapted for values in inserts] == [
        dict(eventId=EVENT, eventName="Workshop", recipientId=recipient, decision="Rejected", reason=reason)
        for recipient in (ORGANISER, COORDINATOR)]


@pytest.mark.parametrize("role,recipient", [("coordinator", COORDINATOR), ("organiser", ORGANISER)],
                         ids=["coordinator-cancellation", "organiser-cancellation"])
def test_cancellation_freezes_for_each_recipient_role(safety_notification_boundary, role, recipient):
    """
    Summary: Either role receives the same event cancellation confirmation and event link.
    AC3: Given an event is cancelled or rejected, the system sends an in-app
        notification to both the Event Coordinator and Event Organiser
        confirming the cancellation or rejection, respectively, with the event
        name.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, _ = safety_notification_boundary
    source = dict(eventId=EVENT, eventName="Workshop", recipientRole=role)
    row = safety_outbox_row("event.cancelled", source)
    envelope = dict(version=1, id=JOB, type="event.cancelled", recipientId=recipient,
                    createdAt="2030-01-01T00:00:00+00:00", message="Workshop was cancelled.",
                    details={**source, "recipientId": recipient},
                    destination=dict(kind="event-details", eventId=EVENT))
    cursor.fetchone.side_effect = [row, {**row, "envelope": envelope}]

    # Act (When)
    response = client.post(f"/internal/notification-outbox/{JOB}/freeze", headers=OUTBOX_HEADERS,
                           json=dict(leaseToken=LEASE, envelope=envelope))

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["envelope"] == envelope
    writes = [call.args[1] for call in cursor.execute.call_args_list if "SET envelope=" in call.args[0]]
    assert len(writes) == 1
    assert writes[0][0].adapted == envelope


def test_cancellation_keeps_both_intents_beside_safety_decision(safety_notification_boundary):
    """
    Summary: Cancellation queues two distinct role intents without losing the safety decision.
    AC3: Given an event is cancelled or rejected, the system sends an in-app
        notification to both the Event Coordinator and Event Organiser
        confirming the cancellation or rejection, respectively, with the event
        name.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, _ = safety_notification_boundary
    row = {**pending_safety_notification_row(), "organiser_id": ORGANISER}
    cursor.fetchone.side_effect = [row, {**row, "status": "Cancelled"}]

    # Act (When)
    response = client.patch(f"/events/{EVENT}/safety-status", headers=HEADERS,
        json=dict(status="Cancelled", decidedBy=OFFICER, safetyCheckId=ROUND, roundNumber=1, remarks="Unsafe exits"))

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Cancelled"
    inserts = [call.args[1] for call in cursor.execute.call_args_list
               if 'INSERT INTO public."EventNotificationOutbox"' in call.args[0]]
    cancellations = [values for values in inserts if values[1] == "event.cancelled"]
    assert len(cancellations) == 2
    assert cancellations[0][0] != cancellations[1][0]
    assert [values[2].adapted for values in cancellations] == [
        dict(eventId=EVENT, eventName="Workshop", recipientRole="coordinator"),
        dict(eventId=EVENT, eventName="Workshop", recipientRole="organiser")]
    assert [values[1] for values in inserts].count("safety.review-decision") == 1


@pytest.mark.parametrize("field,value", [
    ("recipientId", "not-a-uuid"), ("recipientId", None),
    ("createdAt", "2030-01-02T00:00:00+00:00"),
    ("destination", dict(kind="event-details", eventId=EVENT)),
    ("details", {}), ("message", "Workshop was approved."),
], ids=["invalid-recipient-400", "null-recipient-400", "changed-timestamp-400",
        "wrong-review-page-400", "lost-proposed-facts-400", "changed-message-400"])
def test_invalid_change_envelope_never_writes(safety_notification_boundary, field, value):
    """
    Summary: Malformed recipients or altered historical notification content cannot freeze.
    AC1: Given an Event Organiser submits a change request, the system sends an
        in-app notification to the Event Coordinator with the event name,
        proposed changes, and a link to review the request.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, _ = safety_notification_boundary
    source = dict(eventId=EVENT, eventName="Workshop", recipientRole="coordinator",
                  changeRequestId=ROUND, proposedChanges={"expectedAttendance": "40"})
    row = safety_outbox_row("event.change-request-submitted", source)
    envelope = dict(version=1, id=JOB, type="event.change-request-submitted",
        recipientId=COORDINATOR, createdAt="2030-01-01T00:00:00+00:00",
        message="Change requested for Workshop. Proposed changes: Expected Attendance: 40.",
        details={**source, "recipientId": COORDINATOR},
        destination=dict(kind="change-request-review", eventId=EVENT, changeRequestId=ROUND))
    envelope[field] = value
    cursor.fetchone.return_value = row

    # Act (When)
    response = client.post(f"/internal/notification-outbox/{JOB}/freeze", headers=OUTBOX_HEADERS,
                           json=dict(leaseToken=LEASE, envelope=envelope))

    # Assert (Then)
    assert response.status_code == 400
    assert response.json == dict(message="Invalid outbox input.")
    assert not any(call.args[0].lstrip().startswith(("INSERT", "UPDATE", "DELETE"))
                   for call in cursor.execute.call_args_list)


def test_context_returns_organiser_only_on_explicit_opt_in(safety_notification_boundary):
    """
    Summary: An explicit organiser lookup supplies both recipients without changing legacy context.
    AC1: Given an Event Organiser submits a change request, the system sends an
        in-app notification to the Event Coordinator with the event name,
        proposed changes, and a link to review the request.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, row = safety_notification_boundary
    cursor.fetchone.return_value = {**row, "organiser_id": ORGANISER}

    response = client.get(f"/internal/events/{EVENT}/notification-context?includeOrganiser=true", headers=OUTBOX_HEADERS)

    # Act (When)
    legacy = client.get(f"/internal/events/{EVENT}/notification-context", headers=OUTBOX_HEADERS)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json == dict(id=EVENT, eventName="Workshop", coordinatorId=COORDINATOR, organiserId=ORGANISER)
    assert legacy.status_code == 200
    assert legacy.json == dict(id=EVENT, eventName="Workshop", coordinatorId=COORDINATOR)
