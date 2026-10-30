"""
SCRUM-46: Attendee Registration and Update Notifications

User Story
----------
As an Attendee, I want to receive notifications about my registration status,
so that I can confirm my place and stay updated on event changes.

Acceptance Criteria
-------------------
AC1: Given an Attendee successfully registers for an event, the system sends an
     in-app notification confirming their registration with the event name,
     date, time, venue, and registration reference number.
AC2: Given an Attendee successfully withdraws their registration, the system
     sends an in-app notification confirming the withdrawal with the event
     name.
AC3: Given an event cancellation takes effect, or a change to its date, time or
     venue is approved and applied, all currently registered Attendees receive
     an in-app notification with the event name and cancellation status or
     updated details, as applicable.

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
import pytest
from tests.unit.factories import EVENT, COORDINATOR, ROUND, HEADERS


def test_cancellation_saves_attendee_fanout_without_registration_mutation(
    safety_notification_boundary,
):
    """
    Summary: Cancel a pending safety review through the actual Event mutation route.
    AC3: Given an event cancellation takes effect, or a change to its date,
        time or venue is approved and applied, all currently registered
        Attendees receive an in-app notification with the event name and
        cancellation status or updated details, as applicable.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, row = safety_notification_boundary
    from tests.unit.factories import pending_safety_notification_row

    row = pending_safety_notification_row()
    cursor.fetchone.side_effect = [row, {**row, "status": "Cancelled"}]

    # Act (When)
    response = client.patch(
        f"/events/{EVENT}/safety-status",
        headers=HEADERS,
        json=dict(
            status="Cancelled",
            safetyCheckId=ROUND,
            roundNumber=1,
            decidedBy=COORDINATOR,
            remarks="Unsafe",
        ),
    )

    # Assert (Then)
    assert response.status_code == 200
    inserts = [
        c.args[1]
        for c in cursor.execute.call_args_list
        if 'INSERT INTO public."EventNotificationOutbox"' in c.args[0]
    ]
    attendee = [
        values for values in inserts if values[1] == "attendee.cancelled-fanout"
    ]
    assert len(attendee) == 1
    assert attendee[0][2].adapted == dict(eventId=EVENT, eventName="Workshop")
    assert not any(
        'UPDATE public."Registration"' in c.args[0]
        for c in cursor.execute.call_args_list
    )


def test_fanout_freezes_two_registration_targets_with_stable_child_identities(
    safety_notification_boundary,
):
    """
    Summary: Expand one claimed cancellation parent for two distinct attendee/reference pairs.
    AC3: Given an event cancellation takes effect, or a change to its date,
        time or venue is approved and applied, all currently registered
        Attendees receive an in-app notification with the event name and
        cancellation status or updated details, as applicable.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    from tests.unit.factories import (
        safety_outbox_row,
        JOB,
        LEASE,
        OUTBOX_HEADERS,
        OFFICER,
        OTHER_OFFICER,
    )
    from uuid import UUID, uuid5

    client, cursor, _ = safety_notification_boundary
    source = dict(eventId=EVENT, eventName="Workshop")
    cursor.fetchone.return_value = safety_outbox_row(
        "attendee.cancelled-fanout", source
    )
    recipients = [
        dict(recipientId=OFFICER, registrationId=ROUND),
        dict(recipientId=OTHER_OFFICER, registrationId=EVENT),
    ]

    # Act (When)
    response = client.post(
        f"/internal/notification-outbox/{JOB}/expand",
        headers=OUTBOX_HEADERS,
        json=dict(leaseToken=LEASE, recipients=recipients),
    )

    # Assert (Then)
    assert response.status_code == 200
    inserts = [
        c.args[1]
        for c in cursor.execute.call_args_list
        if c.args[0].lstrip().startswith("INSERT")
    ]
    assert len(inserts) == 2
    assert {v[0] for v in inserts} == {
        str(uuid5(UUID(JOB), r["recipientId"])) for r in recipients
    }
    assert {v[1] for v in inserts} == {"attendee.event-cancelled"}
    assert {v[2].adapted["registrationId"] for v in inserts} == {ROUND, EVENT}
    assert {
        (v[0], v[2].adapted["recipientId"], v[2].adapted["registrationId"])
        for v in inserts
    } == {
        (str(uuid5(UUID(JOB), OFFICER)), OFFICER, ROUND),
        (str(uuid5(UUID(JOB), OTHER_OFFICER)), OTHER_OFFICER, EVENT),
    }


@pytest.mark.parametrize(
    "baseline,final,expected",
    [
        (
            {"startDateTime": "2030-03-01T09:00:00+08:00"},
            {"preferred_start_date": "2030-03-02T01:00:00+00:00"},
            {
                "startDateTime": [
                    "2030-03-01T09:00:00+08:00",
                    "2030-03-02T09:00:00+08:00",
                ]
            },
        ),
        (
            {"endDateTime": "2030-03-01T17:00:00+08:00"},
            {"preferred_end_date": "2030-03-01T10:00:00+00:00"},
            {"endDateTime": ["2030-03-01T17:00:00+08:00", "2030-03-01T18:00:00+08:00"]},
        ),
        (
            {"venueName": "Hall A"},
            {"venueName": "Hall C"},
            {"venueName": ["Hall A", "Hall C"]},
        ),
        ({"venueName": "Hall A"}, {"venueName": "Hall A"}, {}),
    ],
    ids=["date", "time", "venue-a-to-c", "venue-a-to-a-silent"],
)
def test_safety_approval_notifies_only_final_schedule_changes(
    safety_notification_boundary, baseline, final, expected
):
    """
    Summary: Confirm a safety review with a captured baseline and final facts.
    AC3: Given an event cancellation takes effect, or a change to its date,
        time or venue is approved and applied, all currently registered
        Attendees receive an in-app notification with the event name and
        cancellation status or updated details, as applicable.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    from datetime import datetime
    from tests.unit.factories import pending_safety_notification_row

    client, cursor, _ = safety_notification_boundary
    row = pending_safety_notification_row()
    metadata = json.loads(row["description"])
    metadata["actionHistory"][0]["attendeeBaseline"] = baseline
    row["description"] = json.dumps(metadata)
    for key, value in final.items():
        if key != "venueName":
            row[key] = datetime.fromisoformat(value)
    cursor.fetchone.side_effect = [row, {**row, "status": "Confirmed"}]

    # Act (When)
    response = client.patch(
        f"/events/{EVENT}/safety-status",
        headers=HEADERS,
        json=dict(
            status="Confirmed",
            safetyCheckId=ROUND,
            roundNumber=2,
            decidedBy=COORDINATOR,
            attendeeVenue=final.get("venueName"),
        ),
    )

    # Assert (Then)
    assert response.status_code == 200, response.json
    jobs = [
        c.args[1]
        for c in cursor.execute.call_args_list
        if 'INSERT INTO public."EventNotificationOutbox"' in c.args[0]
    ]
    jobs = [v for v in jobs if v[1] == "attendee.updated-fanout"]
    assert len(jobs) == bool(expected)
    if expected:
        assert jobs[0][2].adapted == dict(
            eventId=EVENT, eventName="Workshop", changes=expected
        )


@pytest.mark.parametrize(
    "kind,changes,message",
    [
        ("attendee.event-cancelled", None, "Workshop was cancelled."),
        (
            "attendee.event-updated",
            {
                "startDateTime": ["2030-03-01T09:00:00", "2030-03-02T09:00:00+08:00"],
                "endDateTime": [
                    "2030-03-01T17:00:00+08:00",
                    "2030-03-02T17:00:00+08:00",
                ],
                "venueName": ["Hall A", "Hall C"],
            },
            "Workshop was updated. Start date/time: 01 Mar 2030, 09:00 SGT → 02 Mar 2030, 09:00 SGT; End date/time: 01 Mar 2030, 17:00 SGT → 02 Mar 2030, 17:00 SGT; Venue: Hall A → Hall C.",
        ),
        (
            "attendee.event-updated",
            {"venueName": ["Hall A", "Hall C"]},
            "Workshop was updated. Venue: Hall A → Hall C.",
        ),
    ],
    ids=["attendee_event_cancelled_none_workshop_was_cance", "attendee_event_updated_startdatetime_2030_03_01t", "attendee_event_updated_venuename_hall_a_hall_c_w"],
)
def test_event_owner_freezes_exact_saved_change_content(
    safety_notification_boundary, kind, changes, message
):
    """
    Summary: Freeze a child job using the event facts already captured in its source.
    AC3: Given an event cancellation takes effect, or a change to its date,
        time or venue is approved and applied, all currently registered
        Attendees receive an in-app notification with the event name and
        cancellation status or updated details, as applicable.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    from tests.unit.factories import (
        safety_outbox_row,
        JOB,
        LEASE,
        OUTBOX_HEADERS,
        OFFICER,
    )

    client, cursor, _ = safety_notification_boundary
    source = dict(
        eventId=EVENT, eventName="Workshop", recipientId=OFFICER, registrationId=ROUND
    )
    if changes is not None:
        source["changes"] = changes
    record = safety_outbox_row(kind, source)
    value = dict(
        version=1,
        id=JOB,
        type=kind,
        recipientId=OFFICER,
        createdAt=record["created_at"].isoformat(),
        details=source,
        message=message,
        destination=dict(kind="attendee-registration", registrationId=ROUND),
    )
    cursor.fetchone.side_effect = [record, {**record, "envelope": value}]

    # Act (When)
    response = client.post(
        f"/internal/notification-outbox/{JOB}/freeze",
        headers=OUTBOX_HEADERS,
        json=dict(leaseToken=LEASE, envelope=value),
    )

    # Assert (Then)
    assert response.status_code == 200, response.json
    assert response.json["envelope"] == value


@pytest.mark.parametrize(
    "recipients",
    [
        None,
        [{"recipientId": "bad", "registrationId": ROUND}],
        [
            {"recipientId": COORDINATOR, "registrationId": ROUND},
            {"recipientId": COORDINATOR, "registrationId": EVENT},
        ],
        [],
    ],
    ids=["none", "recipientid_bad_registrationid_round", "recipientid_coordinator_registrationid_round_rec", "empty"],
)
def test_invalid_fanout_is_refused_or_empty_snapshot_completes(
    safety_notification_boundary, recipients
):
    """
    Summary: Expand a claimed parent with absent, invalid-UUID, conflicting, or empty recipients.
    AC1: Given an Attendee successfully registers for an event, the system
        sends an in-app notification confirming their registration with the
        event name, date, time, venue, and registration reference number.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    from tests.unit.factories import safety_outbox_row, JOB, LEASE, OUTBOX_HEADERS

    client, cursor, _ = safety_notification_boundary
    cursor.fetchone.return_value = safety_outbox_row(
        "attendee.updated-fanout", dict(eventId=EVENT, eventName="Workshop")
    )

    # Act (When)
    response = client.post(
        f"/internal/notification-outbox/{JOB}/expand",
        headers=OUTBOX_HEADERS,
        json=dict(leaseToken=LEASE, recipients=recipients),
    )

    # Assert (Then)
    assert response.status_code == (200 if recipients == [] else 400)
    assert not any(
        c.args[0].lstrip().startswith("INSERT") for c in cursor.execute.call_args_list
    )


@pytest.mark.parametrize("entry", ["venue", "date"])
def test_first_effective_schedule_is_saved_before_review_without_attendee_alert(
    safety_notification_boundary, entry
):
    """
    Summary: Reopen a Confirmed event for a venue withdrawal or a date-driven recheck.
    AC3: Given an event cancellation takes effect, or a change to its date,
        time or venue is approved and applied, all currently registered
        Attendees receive an in-app notification with the event name and
        cancellation status or updated details, as applicable.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, row = safety_notification_boundary
    metadata = json.loads(row["description"])
    metadata["actionHistory"] = [dict(status="Confirmed", safetyCheckId=ROUND)]
    row.update(status="Confirmed", description=json.dumps(metadata))
    cursor.fetchone.side_effect = [
        row,
        {**row, "status": "Approved" if entry == "venue" else "Pending Safety Check"},
    ]

    # Act (When)
    if entry == "venue":
        response = client.patch(
            f"/events/{EVENT}/safety-status",
            headers=HEADERS,
            json=dict(
                status="Approved",
                coordinatorId=COORDINATOR,
                safetyCheckId=ROUND,
                roundNumber=1,
                withdrawnSafetyCheckId=ROUND,
                reason="Venue edit",
                venueBefore="Hall A",
            ),
        )
        params = cursor.execute.call_args_list[1].args[1]
        saved = json.loads(params[1])
    else:
        response = client.patch(
            f"/events/{EVENT}/details",
            headers=HEADERS,
            json=dict(
                coordinatorId=COORDINATOR,
                changes={"preferredEndDate": "2030-03-01T18:00:00"},
                safetyRecheck=dict(
                    withdrawnSafetyCheckId=ROUND,
                    safetyCheckId=EVENT,
                    roundNumber=2,
                    venueBefore="Hall A",
                ),
            ),
        )
        params = cursor.execute.call_args_list[1].args[1]
        saved = json.loads(params[-3])

    # Assert (Then)
    assert response.status_code == 200, response.json
    assert saved["actionHistory"][-1]["attendeeBaseline"] == dict(
        startDateTime="2030-03-01T09:00:00+08:00",
        endDateTime="2030-03-01T17:00:00+08:00",
        venueName="Hall A",
    )
    assert not any(
        "attendee." in str(c.args[1])
        for c in cursor.execute.call_args_list
        if c.args[0].lstrip().startswith("INSERT")
    )


@pytest.mark.parametrize("venue", [None, "", "   ", 42, {"name": "Hall C"}], ids=["none", "empty", "empty_2", "42", "name_hall_c"])
def test_incomplete_final_venue_cannot_commit_an_effective_update(
    safety_notification_boundary, venue,
):
    """
    Summary: Final approval has a Hall A baseline but an unusable final attendeeVenue.
    AC1: Given an Attendee successfully registers for an event, the system
        sends an in-app notification confirming their registration with the
        event name, date, time, venue, and registration reference number.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    from tests.unit.factories import pending_safety_notification_row

    client, cursor, _ = safety_notification_boundary
    row = pending_safety_notification_row()
    metadata = json.loads(row["description"])
    metadata["actionHistory"][0]["attendeeBaseline"] = {"venueName": "Hall A"}
    row["description"] = json.dumps(metadata)
    cursor.fetchone.side_effect = [row, {**row, "status": "Confirmed"}]

    # Act (When)
    response = client.patch(
        f"/events/{EVENT}/safety-status",
        headers=HEADERS,
        json=dict(
            status="Confirmed",
            safetyCheckId=ROUND,
            roundNumber=1,
            decidedBy=COORDINATOR,
            attendeeVenue=venue,
        ),
    )

    # Assert (Then)
    assert response.status_code == 400
    assert not any(
        "attendee." in str(c.args[1])
        for c in cursor.execute.call_args_list
        if c.args[0].lstrip().startswith("INSERT")
    )


def test_registration_enrichment_context_exposes_only_opted_in_schedule(
    safety_notification_boundary,
):
    """
    Summary: An internal-token caller explicitly requests schedule enrichment for an event.
    AC1: Given an Attendee successfully registers for an event, the system
        sends an in-app notification confirming their registration with the
        event name, date, time, venue, and registration reference number.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    from tests.unit.factories import OUTBOX_HEADERS

    client, cursor, row = safety_notification_boundary
    cursor.fetchone.return_value = row

    # Act (When)
    response = client.get(
        f"/internal/events/{EVENT}/notification-context?includeSchedule=true",
        headers=OUTBOX_HEADERS,
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["startDateTime"] == "2030-03-01T09:00:00"
    assert response.json["endDateTime"] == "2030-03-01T17:00:00"


def test_legacy_event_without_schedule_can_withdraw_safety_without_crashing(
    safety_notification_boundary,
):
    """
    Summary: Withdraw safety from a Confirmed legacy event with both dates null.
    AC1: Given an Attendee successfully registers for an event, the system
        sends an in-app notification confirming their registration with the
        event name, date, time, venue, and registration reference number.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, row = safety_notification_boundary
    row.update(preferred_start_date=None, preferred_end_date=None, status="Confirmed")
    metadata = json.loads(row["description"])
    metadata["actionHistory"] = [dict(status="Confirmed", safetyCheckId=ROUND)]
    row["description"] = json.dumps(metadata)
    cursor.fetchone.side_effect = [row, {**row, "status": "Approved"}]

    # Act (When)
    response = client.patch(
        f"/events/{EVENT}/safety-status",
        headers=HEADERS,
        json=dict(
            status="Approved",
            coordinatorId=COORDINATOR,
            safetyCheckId=ROUND,
            roundNumber=1,
            withdrawnSafetyCheckId=ROUND,
            reason="Venue edit",
            venueBefore="Hall A",
        ),
    )

    # Assert (Then)
    assert response.status_code == 200, response.json
    saved = json.loads(cursor.execute.call_args_list[1].args[1][1])
    assert saved["actionHistory"][-1]["attendeeBaseline"] == {"venueName": "Hall A"}


@pytest.mark.parametrize("entry", ["venue", "date"])
@pytest.mark.parametrize("invalid", [None, "", "   ", 42, {"name": "Hall A"}], ids=["none", "empty", "empty_2", "42", "name_hall_a"])
def test_direct_recheck_requires_original_venue_before_mutating_event(
    safety_notification_boundary, entry, invalid
):
    """
    Summary: Reopen a Confirmed event through either direct venue or date-recheck HTTP.
    AC3: Given an event cancellation takes effect, or a change to its date,
        time or venue is approved and applied, all currently registered
        Attendees receive an in-app notification with the event name and
        cancellation status or updated details, as applicable.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, row = safety_notification_boundary
    metadata = json.loads(row["description"])
    metadata["actionHistory"] = [dict(status="Confirmed", safetyCheckId=ROUND)]
    row.update(status="Confirmed", description=json.dumps(metadata))
    cursor.fetchone.side_effect = [row, {**row, "status": "Approved"}]
    if entry == "venue":
        body = dict(status="Approved", coordinatorId=COORDINATOR, safetyCheckId=ROUND,
                    roundNumber=1, withdrawnSafetyCheckId=ROUND, reason="Venue edit")
        path = f"/events/{EVENT}/safety-status"
        target = body
    else:
        body = dict(coordinatorId=COORDINATOR,
                    changes={"preferredEndDate": "2030-03-01T18:00:00"},
                    safetyRecheck=dict(withdrawnSafetyCheckId=ROUND,
                                       safetyCheckId=EVENT, roundNumber=2))
        path = f"/events/{EVENT}/details"
        target = body["safetyRecheck"]
    if invalid is not None:
        target["venueBefore"] = invalid

    # Act (When)
    response = client.patch(path, headers=HEADERS, json=body)

    # Assert (Then)
    assert response.status_code == 400, response.json
    assert not any(c.args[0].lstrip().startswith(("UPDATE", "INSERT"))
                   for c in cursor.execute.call_args_list)


@pytest.mark.parametrize("legacy_dates", [False, True])
def test_edit_cycle_keeps_original_a_through_b_and_emits_one_combined_c_update(
    safety_notification_boundary, legacy_dates
):
    """
    Summary: Reopen venue A, accumulate date edits while B is under review, then approve final C.
    AC3: Given an event cancellation takes effect, or a change to its date,
        time or venue is approved and applied, all currently registered
        Attendees receive an in-app notification with the event name and
        cancellation status or updated details, as applicable.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    # Arrange: let real route rules evolve one synthetic row across repeated requests.
    import re
    from copy import deepcopy

    client, cursor, initial = safety_notification_boundary
    state = deepcopy(initial)
    metadata = json.loads(state["description"])
    metadata["actionHistory"] = [dict(status="Confirmed", safetyCheckId=ROUND)]
    state.update(status="Confirmed", description=json.dumps(metadata))
    if legacy_dates:
        state.update(preferred_start_date=None, preferred_end_date=None)
    jobs = []

    def execute(sql, params):
        """Apply recorded SQL assignments to the synthetic Event row and capture intent inserts.
        Never implement Event transition/notification rules here; those run in the real routes.
        """
        if sql.lstrip().startswith("UPDATE"):
            # Storage double applies SQL assignments, never implements transition rules.
            columns = re.findall(r"(\w+) = %s", sql.split("WHERE")[0])
            state.update(zip(columns, params))
            cursor.fetchone.return_value = deepcopy(state)
        elif sql.lstrip().startswith("SELECT"):
            cursor.fetchone.return_value = deepcopy(state)
        elif 'INSERT INTO public."EventNotificationOutbox"' in sql:
            jobs.append((params[1], params[2].adapted))

    cursor.fetchone.side_effect = None
    cursor.execute.side_effect = execute

    # Act (When)
    # Act: withdraw the original safety decision before accumulating edits.
    response = client.patch(f"/events/{EVENT}/safety-status", headers=HEADERS, json=dict(
        status="Approved", coordinatorId=COORDINATOR, safetyCheckId=ROUND,
        roundNumber=1, withdrawnSafetyCheckId=ROUND, reason="Venue edit", venueBefore="Hall A"))

    # Assert (Then)
    assert response.status_code == 200, response.json
    # Booking A -> B is under review. No attendee notification before effective approval.
    response = client.patch(f"/events/{EVENT}/details", headers=HEADERS, json=dict(
        coordinatorId=COORDINATOR,
        changes=dict(preferredStartDate="2030-03-02T10:00:00", preferredEndDate="2030-03-02T18:00:00")))
    assert response.status_code == 200, response.json
    # B -> C is applied and approved by Venue Staff while Event remains Approved.
    response = client.patch(f"/events/{EVENT}/safety-status", headers=HEADERS, json=dict(
        status="Pending Safety Check", coordinatorId=COORDINATOR, safetyCheckId=EVENT, roundNumber=2))
    assert response.status_code == 200, response.json
    assert not [job for job in jobs if job[0].startswith("attendee.")]
    response = client.patch(f"/events/{EVENT}/safety-status", headers=HEADERS, json=dict(
        status="Confirmed", decidedBy=COORDINATOR, safetyCheckId=EVENT,
        roundNumber=2, attendeeVenue="Hall C"))
    assert response.status_code == 200, response.json
    # Assert: only final effective changes enter one combined attendee intent.
    updates = [source for kind, source in jobs if kind == "attendee.updated-fanout"]
    expected = {"venueName": ["Hall A", "Hall C"]}
    if not legacy_dates:
        expected.update(startDateTime=["2030-03-01T09:00:00+08:00", "2030-03-02T10:00:00+08:00"],
                        endDateTime=["2030-03-01T17:00:00+08:00", "2030-03-02T18:00:00+08:00"])
    assert updates == [dict(eventId=EVENT, eventName="Workshop", changes=expected)]

    # A later cancelled cycle suppresses only its unapproved delta, not this
    # already-legitimate historical update waiting for delivery.
    response = client.patch(f"/events/{EVENT}/safety-status", headers=HEADERS, json=dict(
        status="Approved", coordinatorId=COORDINATOR, safetyCheckId=EVENT,
        roundNumber=2, withdrawnSafetyCheckId=EVENT, reason="Another venue edit", venueBefore="Hall C"))
    assert response.status_code == 200, response.json
    response = client.patch(f"/events/{EVENT}/safety-status", headers=HEADERS, json=dict(
        status="Pending Safety Check", coordinatorId=COORDINATOR, safetyCheckId=ROUND, roundNumber=3))
    assert response.status_code == 200, response.json
    cursor.execute.reset_mock()
    response = client.patch(f"/events/{EVENT}/safety-status", headers=HEADERS, json=dict(
        status="Cancelled", decidedBy=COORDINATOR, safetyCheckId=ROUND,
        roundNumber=3, remarks="Unsafe"))
    assert response.status_code == 200, response.json
    assert [source for kind, source in jobs if kind == "attendee.updated-fanout"] == updates
    assert len([job for job in jobs if job[0] == "attendee.cancelled-fanout"]) == 1
    assert not any(
        'EventNotificationOutbox' in call.args[0]
        and call.args[0].lstrip().startswith(("DELETE", "UPDATE"))
        for call in cursor.execute.call_args_list
    )
