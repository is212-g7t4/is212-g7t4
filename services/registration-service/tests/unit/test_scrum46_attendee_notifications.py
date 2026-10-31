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
- app.models create/withdraw mutations with their notification-intent insert,
  and the /internal registration-outbox routes (freeze, claim, published,
  retry): display-snapshot validation, envelope validation, lease checks and
  the frozen-before-publish rule run for real.
- Assertions are on the SQL intents and parameters, the HTTP status and the
  saved envelope.

Doubled
-------
- psycopg2.connect: Stub / Mock (tests/unit/conftest.py `storage`) - a fresh
  MagicMock connection and cursor per test; canned rows; executed SQL inspected
  to prove intent, not committed rows.

Not proven
----------
- That the intent commits with the registration in real PostgreSQL (->
  tests/integration/, throwaway postgres:17.6).
- That the dispatcher publishes and Notification Service shows the inbox item
  (-> attendee-registration-service dispatcher tests and notification-service
  consumer tests).
- AC3 (cancellation and approved-change notices to every registered attendee)
  is produced by Event Service, not here (-> its SCRUM-46 tests).
"""

import psycopg2
import pytest
from app import create_app
from app.models import (
    create_registration,
    withdraw_registration,
    DuplicateRegistrationError,
)
from tests.unit.factories import EVENT, USER, REF, JOB, LEASE, row, outbox_row, envelope, signed_in


def test_ac1_register_when_successful_records_confirmation_intent_with_reference(
    storage,
):
    """
    Summary: A successful registration queues one confirmation carrying the registration reference.
    AC1: Given an Attendee successfully registers for an event, the system
        sends an in-app notification confirming their registration with the
        event name, date, time, venue, and registration reference number.
    Double: Stub (cursor: no existing row, free place, saved row), Mock (intent
        insert inspected)
    """
    # Arrange (Given)
    connection, cursor = storage
    cursor.fetchone.side_effect = [None, {"confirmed": 0}, row()]
    result = create_registration("unused", EVENT, USER, 10)

    inserts = [
        c.args
        for c in cursor.execute.call_args_list
        if "RegistrationNotificationOutbox" in c.args[0]
    ]

    # Act + Assert (When / Then)
    assert len(inserts) == 1
    assert inserts[0][1][1] == "registration.confirmed"
    assert inserts[0][1][2].adapted == dict(
        eventId=EVENT, recipientId=USER, registrationId=REF
    )
    assert result["registration_id"] == REF


def test_ac2_withdraw_when_successful_records_withdrawal_intent(storage):
    """
    Summary: A successful withdrawal queues its own withdrawal confirmation.
    AC2: Given an Attendee successfully withdraws their registration, the
        system sends an in-app notification confirming the withdrawal with the
        event name.
    Double: Stub (cursor returns the row before and after), Mock (intent insert
        inspected)
    """
    # Arrange (Given)
    _, cursor = storage
    cursor.fetchone.side_effect = [row(), row("Withdrawn")]
    withdraw_registration("unused", REF, USER)

    inserts = [
        c.args
        for c in cursor.execute.call_args_list
        if "RegistrationNotificationOutbox" in c.args[0]
    ]

    # Act + Assert (When / Then)
    assert len(inserts) == 1
    assert inserts[0][1][1] == "registration.withdrawn"
    assert inserts[0][1][2].adapted["registrationId"] == REF


@pytest.mark.parametrize(
    "kind,naive",
    [
        ("registration.confirmed", False),
        ("registration.confirmed", True),
        ("registration.withdrawn", False),
    ],
    ids=["confirmed", "confirmed_naive_time", "withdrawn"],
)
def test_ac1_ac2_freeze_alert_saves_content_once_and_returns_saved_version(
    storage, kind, naive
):
    """
    Summary: An alert's content is saved once; a later, different draft gets the saved version back.
    AC1: Given an Attendee successfully registers for an event, the system
        sends an in-app notification confirming their registration with the
        event name, date, time, venue, and registration reference number.
    AC2: Given an Attendee successfully withdraws their registration, the
        system sends an in-app notification confirming the withdrawal with the
        event name.
    Double: Stub (cursor: no envelope, then the saved one)
    """
    # Arrange (Given)
    _, cursor = storage
    client = signed_in(create_app(
        dict(TESTING=True, DATABASE_URL="unused", INTERNAL_SERVICE_TOKEN="synthetic")
    ).test_client())
    saved = envelope(kind, naive)
    record = outbox_row(kind)
    cursor.fetchone.side_effect = [record, {**record, "envelope": saved}]
    path = f"/internal/notification-outbox/{JOB}/freeze"
    headers = {"X-Internal-Token": "synthetic"}

    # Act (When)
    response = client.post(
        path, headers=headers, json=dict(leaseToken=LEASE, envelope=saved)
    )

    # Assert (Then)
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
    ids=["not_object", "bool_version", "wrong_identity", "wrong_destination", "wrong_details", "missing_content", "bad_message"],
)
def test_ac1_ac2_freeze_alert_with_malformed_content_returns_400_without_saving(storage, defect):
    """
    Summary: Malformed alert content is refused and nothing is saved.
    AC1: Given an Attendee successfully registers for an event, the system
        sends an in-app notification confirming their registration with the
        event name, date, time, venue, and registration reference number.
    AC2: Given an Attendee successfully withdraws their registration, the
        system sends an in-app notification confirming the withdrawal with the
        event name.
    Double: Stub (cursor returns a leased action)
    """
    # Arrange (Given)
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
    client = signed_in(create_app(
        dict(TESTING=True, DATABASE_URL="unused", INTERNAL_SERVICE_TOKEN="synthetic")
    ).test_client())

    # Act (When)
    response = client.post(
        f"/internal/notification-outbox/{JOB}/freeze",
        headers={"X-Internal-Token": "synthetic"},
        json=dict(leaseToken=LEASE, envelope=value),
    )

    # Assert (Then)
    assert response.status_code == 400
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize(
    "action,frozen", [("published", True), ("published", False), ("retry", False)],
    ids=["published_frozen", "published_unfrozen", "retry_unfrozen"],
)
def test_ac1_finish_alert_requires_saved_content_and_never_changes_registration(
    storage, action, frozen
):
    """
    Summary: An alert can only be marked sent once its content is saved, and finishing never changes the registration.
    AC1: (delivery: an alert is sent only with its saved content)
    Double: Stub (cursor returns a frozen or unfrozen action)
    """
    # Arrange (Given)
    _, cursor = storage
    cursor.fetchone.return_value = {
        **outbox_row(),
        "envelope": envelope() if frozen else None,
    }
    client = signed_in(create_app(
        dict(TESTING=True, DATABASE_URL="unused", INTERNAL_SERVICE_TOKEN="synthetic")
    ).test_client())

    # Act (When)
    response = client.post(
        f"/internal/notification-outbox/{JOB}/{action}",
        headers={"X-Internal-Token": "synthetic"},
        json=dict(leaseToken=LEASE, error="Synthetic outage"),
    )

    # Assert (Then)
    assert response.status_code == (
        400 if action == "published" and not frozen else 200
    )
    assert not any(
        'UPDATE public."Registration"' in call.args[0]
        for call in cursor.execute.call_args_list
    )


@pytest.mark.parametrize("state", ["missing", "expired"], ids=["missing", "expired"])
def test_ac1_finish_alert_with_missing_or_expired_lease_returns_409(storage, state):
    """
    Summary: A worker whose lease is gone cannot mark an alert sent.
    AC1: (delivery: each alert is sent once)
    Double: Stub (cursor returns no row or an expired lease)
    """
    # Arrange (Given)
    _, cursor = storage
    cursor.fetchone.return_value = (
        None if state == "missing" else {**outbox_row(), "lease_valid": False}
    )
    client = signed_in(create_app(
        dict(TESTING=True, DATABASE_URL="unused", INTERNAL_SERVICE_TOKEN="synthetic")
    ).test_client())

    # Act (When)
    response = client.post(
        f"/internal/notification-outbox/{JOB}/published",
        headers={"X-Internal-Token": "synthetic"},
        json=dict(leaseToken=LEASE),
    )

    # Assert (Then)
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
    ids=["claim", "unauthenticated", "token_unconfigured", "database_unconfigured", "unknown_action", "bad_body", "bad_lease", "retry_without_error", "database_error"],
)
def test_ac1_alert_outbox_api_serves_claims_and_refuses_unsafe_calls(storage, case, status):
    """
    Summary: The delivery API hands out claims, and refuses unauthenticated, unconfigured or malformed calls safely.
    AC1: (delivery: only the trusted worker can send alerts)
    Double: Stub (cursor returns a claimable row or raises)
    """
    # Arrange (Given)
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

    # Act (When)
    response = signed_in(create_app(config).test_client()).post(path, headers=headers, json=data)

    # Assert (Then)
    assert response.status_code == status
    if case == "claim":
        assert response.json["jobs"][0]["id"] == JOB
        assert response.json["jobs"][0]["source"]["registrationId"] == REF


@pytest.mark.parametrize("action", ["register", "withdraw"], ids=["register", "withdraw"])
@pytest.mark.parametrize("valid", [True, False], ids=["valid_details", "missing_details"])
def test_ac1_ac2_register_or_withdraw_saves_display_details_for_real_attendee_or_refuses(
    storage, action, valid
):
    """
    Summary: The event details shown in the alert are captured at registration or withdrawal, for the real attendee only.
    AC1: Given an Attendee successfully registers for an event, the system
        sends an in-app notification confirming their registration with the
        event name, date, time, venue, and registration reference number.
    AC2: Given an Attendee successfully withdraws their registration, the
        system sends an in-app notification confirming the withdrawal with the
        event name.
    Double: Stub (cursor returns rows), Mock (intent insert inspected)
    """
    # Arrange (Given)
    _, cursor = storage
    client = signed_in(create_app(dict(TESTING=True, DATABASE_URL="unused")).test_client())
    context = dict(
        eventName="Workshop",
        startDateTime="2030-03-01T09:00:00",
        endDateTime="2030-03-01T17:00:00",
        venueName="Hall A",
        recipientId=JOB,
    )
    if not valid:
        context.pop("eventName")

    # Act (When)
    if action == "register":
        cursor.fetchone.side_effect = [None, {"confirmed": 0}, row()]
        response = client.post(
            "/registrations",
            json=dict(
                eventId=EVENT, capacity=10, notificationContext=context
            ),
        )
    else:
        cursor.fetchone.side_effect = [row(), row("Withdrawn")]
        response = client.patch(
            f"/registrations/{REF}/withdraw",
            json=dict(notificationContext=context),
        )

    # Assert (Then)
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


@pytest.mark.parametrize("field", ["startDateTime", "endDateTime"], ids=["start", "end"])
@pytest.mark.parametrize("invalid", ["not-a-date", "2030-02-30T09:00:00", "9999-12-31T23:59:59-12:00"], ids=["unparseable", "impossible_date", "overflowing_instant"])
def test_ac1_register_with_unrenderable_event_dates_returns_400_before_saving(storage, field, invalid):
    """
    Summary: Event dates that could not be shown in the confirmation are refused before anything is saved.
    AC1: Given an Attendee successfully registers for an event, the system
        sends an in-app notification confirming their registration with the
        event name, date, time, venue, and registration reference number.
    Double: Stub (cursor), Mock (no insert)
    """
    # Arrange (Given)
    _, cursor = storage
    cursor.fetchone.side_effect = [None, {"confirmed": 0}, row()]
    context = dict(eventName="Workshop", startDateTime="2030-03-01T09:00:00",
                   endDateTime="2030-03-01T17:00:00", venueName="Hall A")
    context[field] = invalid

    # Act (When)
    response = signed_in(create_app(dict(TESTING=True, DATABASE_URL="unused")).test_client()).post(
        "/registrations", json=dict(eventId=EVENT, capacity=10,
                                    notificationContext=context))

    # Assert (Then)
    assert response.status_code == 400
    assert not any(c.args[0].lstrip().startswith(("INSERT", "UPDATE"))
                   for c in cursor.execute.call_args_list)
