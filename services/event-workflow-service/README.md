# event-workflow-service

Composite service (port **5014**) for SCRUM-20, *update event information
during planning*. It sits between the UI and Event Service on
`PATCH /events/<id>/details`:

1. The caller must be the event's assigned coordinator, or the Event
   Coordinator Lead when the event has no assigned coordinator (role looked
   up in User Service).
2. Event Service classifies the edit as low- or high-impact with nothing
   written (`dryRun`). It stays the single authority on that split.
3. A high-impact edit is checked against the event's other arrangements. Any
   contradiction refuses it with `409 CHANGE_CONTRADICTS_ARRANGEMENTS` and a
   list of reasons; nothing is saved.
4. Otherwise Event Service saves it. A high-impact edit of a `Confirmed` event
   still comes back `409 SAFETY_RECHECK_REQUIRED`, so the safety re-check
   (SCRUM-153) is only offered after this validation has passed.

## Contradiction rules

| Change | Contradiction |
|---|---|
| Start/end date | The event has live (not Cancelled/Expired/Rejected) venue bookings and none overlaps the new window |
| Start/end date | A Pending/Approved equipment line exceeds stock available in the new window (total less Approved lines of other overlapping events) |
| Attendance increased | New attendance exceeds the catalogue capacity of a venue with a live booking |

Venue requirements, accessibility needs and the free-text equipment
requirements have no rule. If a downstream service can't be read, the edit is
refused (fail closed).

## Run

```
uv sync
uv run flask --app app run --debug
uv run pytest
```

Calls: Event, User, Venue Availability, Venue, Equipment Request, Equipment.

## SCRUM-45 event notification dispatcher

Run a separate `uv run python -m app.dispatcher` process; Flask requests never
publish notifications. Compose starts `event-notification-dispatcher` from this
same image. Configure `EVENT_SERVICE_URL`, `INTERNAL_SERVICE_TOKEN` (must match
Event Service), `USER_SERVICE_URL` and `RABBITMQ_URL`. Missing/mismatched tokens fail closed.

Install `20261021000000_event_notification_outbox.sql` on the **Event-owned**
database before enabling new rejections. The existing Notification inbox
migration belongs on its own database. Also apply
`20261021000100_event_approval_notifications.sql` and
`20261021020000_event_notification_assignments.sql` on the Event-owned database
before enabling approval, initial assignment and reassignment notifications. Both forward
migrations extend the installed type constraint rather than replacing other
supported types. Reassignment reuses the assignment type and requires no additional
migration. There is no historical backfill.
Both approval/rejection entry paths and initial assignment/reassignment save historical
source facts in the same transaction as the event mutation. Ownerless legacy changes
remain actionable but log a missing-organiser diagnostic without broadcast.

Event's internal claim/freeze/published/retry HTTP APIs use a fenced 60-second
lease, one job per claim, immutable source/envelope and retry scheduling. A
50-second subprocess budget includes claim, preparation and publication.
Unknown outcomes recover with the same identity after lease expiry. Inbox
source-ID deduplication preserves read state. A publisher confirmation is not
an inbox receipt. Diagnose worker logs and Event-owned pending rows/last_error.
No atomic calls other services or RabbitMQ.

### SCRUM-45 service tests

From this service directory, with dotenv disabled and no shared database credentials:

```sh
env -i HOME="$HOME" PATH="$PATH" TMPDIR="$TMPDIR" PYTHON_DOTENV_DISABLED=1 FLASK_SKIP_DOTENV=1 \
  uv run python -m pytest
env -i HOME="$HOME" PATH="$PATH" TMPDIR="$TMPDIR" PYTHON_DOTENV_DISABLED=1 FLASK_SKIP_DOTENV=1 \
  uv run python -m pytest tests/integration/test_scrum45_organiser_decision_notifications.py -m integration --no-cov
```

The story unit module is `tests/unit/test_scrum45_notifications.py` in Event and
Notification, and `tests/unit/test_scrum45_organiser_decision_notifications.py` in
Event Workflow; the integration module is
`tests/integration/test_scrum45_organiser_decision_notifications.py` in Event and Event
Workflow (Notification's is `test_scrum45_event_organiser_notifications.py`). Event/Notification use their own disposable PostgreSQL 17.6 with
full migrations (Docker required); Workflow uses strict HTTP stubs and a recording
publisher, without a database or broker. Event's separate
`tests/integration/test_infra_migrations.py` preserves full-chain install/upgrade
checks. See the [team integration guide](../../docs/testing/integration-testing.md).
These service tests do not prove cross-service delivery or browser navigation.
`scripts/test_support/process_lifecycle.py` supplies explicit command, polling,
port-discovery and owned-resource cleanup helpers for retained root E2E setup and
lifecycle safety tests. Importing the package or module starts nothing; cleanup
requires caller-owned process groups, log handles and exact container names and
returns failure diagnostics. These helpers are not an acceptance suite or service
integration fixtures.
Existing teammate E2E is unchanged.
See `docs/scrum-45-manual-testing.md` for the separate shared-development gates.

### Initial assignment preparation and name repair (AC4 / DR6)

Initial assignment retains event name, submitting organiser ID and assigned
coordinator ID on Event's transaction. The worker looks up that **saved** ID at
`GET /users/<id>`; the User Service returns `username` (not `name`). Freeze saves
that name and the envelope once, before RabbitMQ publication. Publication retries
never look up or rewrite the prepared name.

User timeouts/5xx retry with the existing durable backoff. User 404 or absent,
blank or non-string username produces `CoordinatorNameUnavailable` plus the
saved coordinator ID. The authenticated `hold` operation clears its lease and
excludes it from claims; unrelated work continues. Operators can inspect holds
with `GET /internal/notification-outbox/held` using `X-Internal-Token`. After
repairing the saved user's data, use authenticated
`POST /internal/notification-outbox/<source-id>/release` (JSON `{}`) to make that
same historical change eligible again. This does not alter assignment or
substitute the current coordinator. Held work is never deleted or automatically
published with an ID-only placeholder.

`tests/integration/test_scrum45_organiser_decision_notifications.py` checks saved-ID lookup,
missing-name hold, transient lookup retry and independent job progress with strict
Event/User HTTP stubs; owner transaction/storage is tested in the owning services.
