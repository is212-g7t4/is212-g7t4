"""SCRUM-46 Attendee Registration and Update Notifications: Registration unit tests.

Story: As an Attendee, I want to receive notifications about my registration status, so that I can confirm my place and stay updated on event changes.

Real: mutation logic and SQL construction. Doubled: PostgreSQL connection/cursor.
Not proven: transactional persistence, broker delivery or authentication.
AC1 Given an Attendee successfully registers for an event, the system sends an in-app notification confirming their registration with the event name, date, time, venue, and registration reference number.
AC2 Given an Attendee successfully withdraws their registration, the system sends an in-app notification confirming the withdrawal with the event name.
AC3 Given an event cancellation takes effect, or a change to its date, time or venue is approved and applied, all currently registered Attendees receive an in-app notification with the event name and cancellation status or updated details, as applicable.
AC1/2 action and owner-delivery contracts are covered here; AC3 runs in Event/Workflow.
AC = acceptance criterion; DR = supporting design rule.
"""

import psycopg2
import pytest
from app import create_app
from app.models import (
    create_registration,
    withdraw_registration,
    DuplicateRegistrationError,
)
from tests.unit.factories import EVENT, USER, REF, JOB, LEASE, row, outbox_row, envelope


# AC1 ----
def test_ac1_successful_registration_records_durable_action_with_full_reference(
    storage,
):
    """Normal: a new attendee has capacity and no existing registration in the SQL double.
    Call the real mutation and require one confirmation-intent insert on its cursor,
    with the returned full registration reference and owner-derived recipient IDs.
    This checks action/intent wiring; mocked libpq calls do not prove a database commit.
    """
    connection, cursor = storage
    cursor.fetchone.side_effect = [None, {"confirmed": 0}, row()]
    result = create_registration("unused", EVENT, USER, 10)
    inserts = [
        c.args
        for c in cursor.execute.call_args_list
        if "RegistrationNotificationOutbox" in c.args[0]
    ]
    assert len(inserts) == 1
    assert inserts[0][1][1] == "registration.confirmed"
    assert inserts[0][1][2].adapted == dict(
        eventId=EVENT, recipientId=USER, registrationId=REF
    )
    assert result["registration_id"] == REF


# AC2 ----
def test_ac2_withdrawal_records_its_own_new_action(storage):
    """Normal: an existing Confirmed row is returned by the mocked database.
    Withdraw it through the real mutation and require one withdrawal-specific intent
    that retains the registration reference. A withdrawal must be distinguishable
    from confirmation; transaction durability is checked in PostgreSQL integrations.
    """
    _, cursor = storage
    cursor.fetchone.side_effect = [row(), row("Withdrawn")]
    withdraw_registration("unused", REF, USER)
    inserts = [
        c.args
        for c in cursor.execute.call_args_list
        if "RegistrationNotificationOutbox" in c.args[0]
    ]
    assert len(inserts) == 1
    assert inserts[0][1][1] == "registration.withdrawn"
    assert inserts[0][1][2].adapted["registrationId"] == REF


# DR ---- owner HTTP fencing, immutable freeze and bounded technical retry
@pytest.mark.parametrize(
    "kind,naive",
    [
        ("registration.confirmed", False),
        ("registration.confirmed", True),
        ("registration.withdrawn", False),
    ],
)
def test_dr_owner_freezes_required_content_once_and_returns_saved_payload(
    storage, kind, naive
):
    """Normal: freeze a claimed action through the owner HTTP route, then offer a changed draft.
    The SQL double first has no envelope, then returns the saved one; expect an exact
    first write and reuse without rewriting it. Cases cover confirmation with UTC
    or naive Singapore times, and withdrawal. This protects immutable retry content,
    not actual persistence: the route/validation run, but libpq is mocked.
    """
    _, cursor = storage
    client = create_app(
        dict(TESTING=True, DATABASE_URL="unused", INTERNAL_SERVICE_TOKEN="synthetic")
    ).test_client()
    saved = envelope(kind, naive)
    record = outbox_row(kind)
    cursor.fetchone.side_effect = [record, {**record, "envelope": saved}]
    path = f"/internal/notification-outbox/{JOB}/freeze"
    headers = {"X-Internal-Token": "synthetic"}
    response = client.post(
        path, headers=headers, json=dict(leaseToken=LEASE, envelope=saved)
    )
    assert response.status_code == 200
    assert response.json == dict(envelope=saved)
    assert cursor.execute.call_args.args[1][0].adapted == saved
    cursor.fetchone.side_effect = None
    cursor.fetchone.return_value = {**record, "envelope": saved}
    cursor.execute.reset_mock()
    again = client.post(
        path,
        headers=headers,
        json=dict(leaseToken=LEASE, envelope={"changed": "draft"}),
    )
    assert again.json == dict(envelope=saved)
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize(
    "defect",
    [
        "not-object",
        "version-bool",
        "identity",
        "destination",
        "details",
        "missing-content",
        "message",
    ],
)
def test_dr_invalid_registration_envelope_cannot_be_frozen(storage, defect):
    """Failure: offer one malformed envelope to the real freeze endpoint under a valid lease.
    Expect 400 and only the initial SQL read, so invalid content cannot be saved.
    Defects mean: a non-object body, boolean version, wrong recipient, internal-event
    destination, wrong details reference, missing venue, or incorrect message text.
    The database row is doubled; this checks validation before the durable-write seam.
    """
    _, cursor = storage
    value = envelope()
    if defect == "not-object":
        value = []
    elif defect == "version-bool":
        value["version"] = True
    elif defect == "identity":
        value["recipientId"] = JOB
    elif defect == "destination":
        value["destination"] = {"kind": "event-details", "eventId": EVENT}
    elif defect == "details":
        value["details"]["registrationId"] = JOB
    elif defect == "missing-content":
        value["details"].pop("venueName")
    elif defect == "message":
        value["message"] = "Wrong workshop"
    cursor.fetchone.return_value = outbox_row()
    client = create_app(
        dict(TESTING=True, DATABASE_URL="unused", INTERNAL_SERVICE_TOKEN="synthetic")
    ).test_client()
    response = client.post(
        f"/internal/notification-outbox/{JOB}/freeze",
        headers={"X-Internal-Token": "synthetic"},
        json=dict(leaseToken=LEASE, envelope=value),
    )
    assert response.status_code == 400
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize(
    "action,frozen", [("published", True), ("published", False), ("retry", False)]
)
def test_dr_completion_requires_freeze_and_retry_retains_business_state(
    storage, action, frozen
):
    """Boundary: attempt completion with a frozen or unfrozen action, or retry unfrozen work.
    The real owner route accepts frozen completion and retry, refuses unfrozen
    completion, and never updates Registration. This separates delivery bookkeeping
    from the attendee's successful action; SQL results and storage are doubled here.
    """
    _, cursor = storage
    cursor.fetchone.return_value = {
        **outbox_row(),
        "envelope": envelope() if frozen else None,
    }
    client = create_app(
        dict(TESTING=True, DATABASE_URL="unused", INTERNAL_SERVICE_TOKEN="synthetic")
    ).test_client()
    response = client.post(
        f"/internal/notification-outbox/{JOB}/{action}",
        headers={"X-Internal-Token": "synthetic"},
        json=dict(leaseToken=LEASE, error="Synthetic outage"),
    )
    assert response.status_code == (
        400 if action == "published" and not frozen else 200
    )
    assert not any(
        'UPDATE public."Registration"' in call.args[0]
        for call in cursor.execute.call_args_list
    )


@pytest.mark.parametrize("state", ["missing", "expired"])
def test_dr_expired_or_missing_lease_cannot_publish(storage, state):
    """Conflict: complete work whose row is missing or whose mocked lease is expired.
    The real endpoint must return 409 after its lookup and perform no later write,
    preventing a stale worker from acknowledging someone else's attempt. This tests
    the lost-lease branch, not elapsed-time expiry in a running PostgreSQL server.
    """
    _, cursor = storage
    cursor.fetchone.return_value = (
        None if state == "missing" else {**outbox_row(), "lease_valid": False}
    )
    client = create_app(
        dict(TESTING=True, DATABASE_URL="unused", INTERNAL_SERVICE_TOKEN="synthetic")
    ).test_client()
    response = client.post(
        f"/internal/notification-outbox/{JOB}/published",
        headers={"X-Internal-Token": "synthetic"},
        json=dict(leaseToken=LEASE),
    )
    assert response.status_code == 409
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize(
    "case,status",
    [
        ("claim", 200),
        ("unauthenticated", 401),
        ("unconfigured-token", 401),
        ("unconfigured-db", 503),
        ("unknown", 404),
        ("bad-body", 400),
        ("bad-token", 400),
        ("retry-no-error", 400),
        ("database-error", 503),
    ],
)
def test_dr_owner_api_refuses_unsafe_work_and_serializes_claims(storage, case, status):
    """Boundary: exercise the real internal route with one configuration or input condition.
    Claim serializes a valid mocked row; missing auth/token, absent database config,
    unknown operation, non-object body, malformed lease, retry without error text,
    and simulated SQL outage produce the listed HTTP status instead of unsafe work.
    These cases protect the delivery entry point; neither authentication of end users
    nor successful SQL execution is established by the mocked connection.
    """
    _, cursor = storage
    config = dict(
        TESTING=True, DATABASE_URL="unused", INTERNAL_SERVICE_TOKEN="synthetic"
    )
    headers = {"X-Internal-Token": "synthetic"}
    path = f"/internal/notification-outbox/{JOB}/retry"
    data = dict(leaseToken=LEASE)
    cursor.fetchone.return_value = outbox_row()
    cursor.fetchall.return_value = [outbox_row()]
    if case == "claim":
        path = "/internal/notification-outbox/claim"
    elif case == "unauthenticated":
        headers = {}
    elif case == "unconfigured-token":
        config["INTERNAL_SERVICE_TOKEN"] = ""
    elif case == "unconfigured-db":
        config["DATABASE_URL"] = None
    elif case == "unknown":
        path = f"/internal/notification-outbox/{JOB}/other"
    elif case == "bad-body":
        data = []
    elif case == "bad-token":
        data["leaseToken"] = "invalid"
    elif case == "database-error":
        cursor.execute.side_effect = psycopg2.OperationalError()
    response = create_app(config).test_client().post(path, headers=headers, json=data)
    assert response.status_code == status
    if case == "claim":
        assert response.json["jobs"][0]["id"] == JOB
        assert response.json["jobs"][0]["source"]["registrationId"] == REF


@pytest.mark.parametrize("action", ["register", "withdraw"])
@pytest.mark.parametrize("valid", [True, False])
def test_ac1_ac2_action_time_display_snapshot_is_persisted_or_refused(
    storage, action, valid
):
    """Boundary: register or withdraw using a supplied display snapshot and a spoofed recipient.
    For valid=True, expect one intent using the owner's actual attendee ID and saved
    name; valid=False removes the required name and must refuse without an intent.
    All four action/validity combinations guard historical content and identity
    integrity. HTTP validation/mutations run; the database cursor is a unit double.
    """
    _, cursor = storage
    client = create_app(dict(TESTING=True, DATABASE_URL="unused")).test_client()
    context = dict(
        eventName="Workshop",
        startDateTime="2030-03-01T09:00:00",
        endDateTime="2030-03-01T17:00:00",
        venueName="Hall A",
        recipientId=JOB,
    )
    if not valid:
        context.pop("eventName")
    if action == "register":
        cursor.fetchone.side_effect = [None, {"confirmed": 0}, row()]
        response = client.post(
            "/registrations",
            json=dict(
                eventId=EVENT, attendeeId=USER, capacity=10, notificationContext=context
            ),
        )
    else:
        cursor.fetchone.side_effect = [row(), row("Withdrawn")]
        response = client.patch(
            f"/registrations/{REF}/withdraw",
            json=dict(attendeeId=USER, notificationContext=context),
        )
    assert response.status_code == (
        (201 if action == "register" else 200) if valid else 400
    )
    writes = [
        c.args[1]
        for c in cursor.execute.call_args_list
        if "RegistrationNotificationOutbox" in c.args[0]
    ]
    assert len(writes) == int(valid)
    if valid:
        assert writes[0][2].adapted["eventName"] == "Workshop"
        assert writes[0][2].adapted["recipientId"] == USER


@pytest.mark.parametrize("field", ["startDateTime", "endDateTime"])
@pytest.mark.parametrize("invalid", ["not-a-date", "2030-02-30T09:00:00", "9999-12-31T23:59:59-12:00"])
def test_ac1_nonrenderable_snapshot_dates_are_refused_before_registration_writes(storage, field, invalid):
    """Failure: corrupt either captured start or end time before calling registration HTTP.
    The three values mean unparseable text, an impossible calendar date, and a valid
    ISO instant that overflows when rendered in Singapore. All six combinations
    must return 400 before INSERT/UPDATE, preventing permanently undeliverable frozen
    intent. Routes and date validation run; SQL and its returned rows are doubled.
    """
    _, cursor = storage
    cursor.fetchone.side_effect = [None, {"confirmed": 0}, row()]
    context = dict(eventName="Workshop", startDateTime="2030-03-01T09:00:00",
                   endDateTime="2030-03-01T17:00:00", venueName="Hall A")
    context[field] = invalid
    response = create_app(dict(TESTING=True, DATABASE_URL="unused")).test_client().post(
        "/registrations", json=dict(eventId=EVENT, attendeeId=USER, capacity=10,
                                    notificationContext=context))
    assert response.status_code == 400
    assert not any(c.args[0].lstrip().startswith(("INSERT", "UPDATE"))
                   for c in cursor.execute.call_args_list)
