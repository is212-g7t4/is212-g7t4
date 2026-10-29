"""SCRUM-46 Attendee Registration and Update Notifications: Event unit tests.

Story: As an Attendee, I want to receive notifications about my registration status, so that I can confirm my place and stay updated on event changes.

Real: Event mutation routes and owner SQL construction. Doubled: PostgreSQL cursor.
Not proven: SQL persistence, external recipient APIs, broker or browser delivery.
AC1 Given an Attendee successfully registers for an event, the system sends an in-app notification confirming their registration with the event name, date, time, venue, and registration reference number.
AC2 Given an Attendee successfully withdraws their registration, the system sends an in-app notification confirming the withdrawal with the event name.
AC3 Given an event cancellation takes effect, or a change to its date, time or venue is approved and applied, all currently registered Attendees receive an in-app notification with the event name and cancellation status or updated details, as applicable.
AC1/2 are owned by Registration and Workflow; AC3 durable triggers are covered here.
AC = acceptance criterion; DR = supporting design rule.
"""

import json
import pytest
from tests.unit.factories import EVENT, COORDINATOR, ROUND, HEADERS


# AC3 ----
def test_ac3_cancellation_saves_attendee_fanout_without_registration_mutation(
    safety_notification_boundary,
):
    """Normal: cancel a pending safety review through the actual Event mutation route.
    With SQL rows doubled, require one attendee cancellation intent carrying the
    saved event name and no Registration UPDATE. Cancellation reports event state;
    it must not rewrite attendance history. This records SQL intent, not a commit
    or delivery to the eventual audience.
    """
    client, cursor, row = safety_notification_boundary
    from tests.unit.factories import pending_safety_notification_row

    row = pending_safety_notification_row()
    cursor.fetchone.side_effect = [row, {**row, "status": "Cancelled"}]
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


def test_ac3_fanout_freezes_two_registration_targets_with_stable_child_identities(
    safety_notification_boundary,
):
    """Normal: expand one claimed cancellation parent for two distinct attendee/reference pairs.
    The real owner route must issue exactly two child inserts, each pairing its
    UUID5 identity with the correct recipient and registration, rather than merely
    preserving two unrelated sets. SQL is recorded by a cursor double; PostgreSQL
    integration separately proves the audience is committed atomically.
    """
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
    response = client.post(
        f"/internal/notification-outbox/{JOB}/expand",
        headers=OUTBOX_HEADERS,
        json=dict(leaseToken=LEASE, recipients=recipients),
    )
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
def test_ac3_safety_approval_notifies_only_final_schedule_changes(
    safety_notification_boundary, baseline, final, expected
):
    """Normal/boundary: confirm a safety review with a captured baseline and final facts.
    Date moves the start to the next day, time extends the end, venue-a-to-c changes
    the hall, and venue-a-to-a-silent is a net-zero edit. Expect one exact delta or
    no attendee intent, avoiding intermediate/stale updates. Event HTTP and comparison
    logic run; the baseline and final database rows are synthetic cursor results.
    """
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
)
def test_ac3_event_owner_freezes_exact_saved_change_content(
    safety_notification_boundary, kind, changes, message
):
    """Normal: freeze a child job using the event facts already captured in its source.
    Cases are cancellation, combined start/end/venue change, and venue-only change;
    expect the exact complete envelope and attendee-registration destination back.
    This checks the owner's accepted wire contract, not reconstruction from current
    Event state. SQL persistence is doubled, so durable freeze is covered elsewhere.
    """
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
    response = client.post(
        f"/internal/notification-outbox/{JOB}/freeze",
        headers=OUTBOX_HEADERS,
        json=dict(leaseToken=LEASE, envelope=value),
    )
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
)
def test_dr_invalid_fanout_is_refused_or_empty_snapshot_completes(
    safety_notification_boundary, recipients
):
    """Boundary: expand a claimed parent with absent, invalid-UUID, conflicting, or empty recipients.
    None is not a list; the invalid UUID cannot identify an attendee; conflicting
    rows assign two references to one attendee. Those return 400, while [] is a valid
    empty audience and returns 200. No case inserts children. The actual validation
    runs over a SQL double, guarding against treating malformed lookups as success.
    """
    from tests.unit.factories import safety_outbox_row, JOB, LEASE, OUTBOX_HEADERS

    client, cursor, _ = safety_notification_boundary
    cursor.fetchone.return_value = safety_outbox_row(
        "attendee.updated-fanout", dict(eventId=EVENT, eventName="Workshop")
    )
    response = client.post(
        f"/internal/notification-outbox/{JOB}/expand",
        headers=OUTBOX_HEADERS,
        json=dict(leaseToken=LEASE, recipients=recipients),
    )
    assert response.status_code == (200 if recipients == [] else 400)
    assert not any(
        c.args[0].lstrip().startswith("INSERT") for c in cursor.execute.call_args_list
    )


@pytest.mark.parametrize("entry", ["venue", "date"])
def test_ac3_first_effective_schedule_is_saved_before_review_without_attendee_alert(
    safety_notification_boundary, entry
):
    """Normal: reopen a Confirmed event for a venue withdrawal or a date-driven recheck.
    Both entry points receive Hall A and must save original start/end/venue in action
    history without creating an attendee alert yet. That baseline makes later final
    approval compare against the last effective facts. HTTP and serialization run;
    SQL calls are inspected, not committed to PostgreSQL.
    """
    client, cursor, row = safety_notification_boundary
    metadata = json.loads(row["description"])
    metadata["actionHistory"] = [dict(status="Confirmed", safetyCheckId=ROUND)]
    row.update(status="Confirmed", description=json.dumps(metadata))
    cursor.fetchone.side_effect = [
        row,
        {**row, "status": "Approved" if entry == "venue" else "Pending Safety Check"},
    ]
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


@pytest.mark.parametrize("venue", [None, "", "   ", 42, {"name": "Hall C"}])
def test_dr_incomplete_final_venue_cannot_commit_an_effective_update(
    safety_notification_boundary, venue,
):
    """Failure: final approval has a Hall A baseline but an unusable final attendeeVenue.
    Null, empty text, whitespace, a number, and an object must each return 400 without
    an attendee intent. Immutable updates cannot safely guess a final venue later.
    The real validation and Event route run against doubled SQL rows; this is not a
    claim that external venue lookup or durable rollback was exercised.
    """
    from tests.unit.factories import pending_safety_notification_row

    client, cursor, _ = safety_notification_boundary
    row = pending_safety_notification_row()
    metadata = json.loads(row["description"])
    metadata["actionHistory"][0]["attendeeBaseline"] = {"venueName": "Hall A"}
    row["description"] = json.dumps(metadata)
    cursor.fetchone.side_effect = [row, {**row, "status": "Confirmed"}]
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
    assert response.status_code == 400
    assert not any(
        "attendee." in str(c.args[1])
        for c in cursor.execute.call_args_list
        if c.args[0].lstrip().startswith("INSERT")
    )


def test_ac1_registration_enrichment_context_exposes_only_opted_in_schedule(
    safety_notification_boundary,
):
    """Normal: an internal-token caller explicitly requests schedule enrichment for an event.
    The real context route must serialize both saved times for a registration alert,
    so a legacy action can acquire required display facts. The event row is mocked;
    this case does not itself test denial without the token or downstream delivery.
    """
    from tests.unit.factories import OUTBOX_HEADERS

    client, cursor, row = safety_notification_boundary
    cursor.fetchone.return_value = row
    response = client.get(
        f"/internal/events/{EVENT}/notification-context?includeSchedule=true",
        headers=OUTBOX_HEADERS,
    )
    assert response.status_code == 200
    assert response.json["startDateTime"] == "2030-03-01T09:00:00"
    assert response.json["endDateTime"] == "2030-03-01T17:00:00"


def test_dr_legacy_event_without_schedule_can_withdraw_safety_without_crashing(
    safety_notification_boundary,
):
    """Boundary: withdraw safety from a Confirmed legacy event with both dates null.
    The actual Event route must succeed and capture only its known Hall A venue,
    without trying to serialize absent dates. This preserves earlier valid workflows
    while supporting notification baselines; the SQL cursor and stored row are doubled.
    """
    client, cursor, row = safety_notification_boundary
    row.update(preferred_start_date=None, preferred_end_date=None, status="Confirmed")
    metadata = json.loads(row["description"])
    metadata["actionHistory"] = [dict(status="Confirmed", safetyCheckId=ROUND)]
    row["description"] = json.dumps(metadata)
    cursor.fetchone.side_effect = [row, {**row, "status": "Approved"}]
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
    assert response.status_code == 200, response.json
    saved = json.loads(cursor.execute.call_args_list[1].args[1][1])
    assert saved["actionHistory"][-1]["attendeeBaseline"] == {"venueName": "Hall A"}


@pytest.mark.parametrize("entry", ["venue", "date"])
@pytest.mark.parametrize("invalid", [None, "", "   ", 42, {"name": "Hall A"}])
def test_ac3_direct_recheck_requires_original_venue_before_mutating_event(
    safety_notification_boundary, entry, invalid
):
    """Failure: reopen a Confirmed event through either direct venue or date-recheck HTTP.
    For each entry point, venueBefore is omitted, empty, whitespace, numeric, or an
    object. Expect 400 before any UPDATE/INSERT, so an incomplete original snapshot
    cannot poison later comparisons. Real route validation runs with a SQL double;
    this does not depend on a cooperative composite supplying the right facts.
    """
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
    response = client.patch(path, headers=HEADERS, json=body)
    assert response.status_code == 400, response.json
    assert not any(c.args[0].lstrip().startswith(("UPDATE", "INSERT"))
                   for c in cursor.execute.call_args_list)


@pytest.mark.parametrize("legacy_dates", [False, True])
def test_ac3_edit_cycle_keeps_original_a_through_b_and_emits_one_combined_c_update(
    safety_notification_boundary, legacy_dates
):
    """Normal: reopen venue A, accumulate date edits while B is under review, then approve final C.
    The actual Event endpoints must emit one A-to-C combined update; a later cancelled
    cycle must retain that historical alert and add one cancellation, not delete it.
    legacy_dates=False also compares original start/end; True starts with unknown
    dates and compares only the known venue. A stateful cursor double applies SQL
    assignments, not transition rules; B/C are supplied external facts, not a real
    Venue Booking/Safety composite journey or PostgreSQL concurrency test.
    """
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
    # Act: withdraw the original safety decision before accumulating edits.
    response = client.patch(f"/events/{EVENT}/safety-status", headers=HEADERS, json=dict(
        status="Approved", coordinatorId=COORDINATOR, safetyCheckId=ROUND,
        roundNumber=1, withdrawnSafetyCheckId=ROUND, reason="Venue edit", venueBefore="Hall A"))
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
