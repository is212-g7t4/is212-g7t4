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
before enabling approval and initial assignment notifications. Both forward
migrations extend the installed type constraint rather than replacing other
supported types. This slice adds no backfill or reassignment notifications.
Both approval/rejection entry paths and initial assignment save historical
source facts in the same transaction as the event mutation. Ownerless legacy changes
remain actionable but log a missing-organiser diagnostic without broadcast.

Event's internal claim/freeze/published/retry HTTP APIs use a fenced 60-second
lease, one job per claim, immutable source/envelope and retry scheduling. A
50-second subprocess budget includes claim, preparation and publication.
Unknown outcomes recover with the same identity after lease expiry. Inbox
source-ID deduplication preserves read state. A publisher confirmation is not
an inbox receipt. Diagnose worker logs and Event-owned pending rows/last_error.
No atomic calls other services or RabbitMQ.

### Real isolated acceptance run

With Docker Desktop running and `postgres:17` / `rabbitmq:4-management`
available, first `uv sync --locked` in Event, Notification, User and Event Workflow,
then from Event Workflow:

```sh
uv run --with psycopg2-binary python -m pytest -m integration --no-cov
```

The tests own disposable UUID-named containers, separate Event/Notification/User
databases, real HTTP/consumer/worker processes, synthetic identities and finally
cleanup. The User lookup is the real User Service, not an HTTP mock server.
They disable dotenv and never use a remote database. They check both approval
and rejection paths, distinct approval/initial-assignment updates, clean and
existing rejection-only schema upgrades, broker outage/recovery, duplicate delivery/read-state preservation,
recipient isolation and real mutation rollback. Use `python -m pytest` so uv's
overlay driver is available; the bare pytest executable uses its venv shebang.
Browser checks remain separate mocked Playwright journeys, not persistence
proof (`event-approval-notifications.spec.ts`, `event-rejection-notifications.spec.ts`,
`event-assignment-notifications.spec.ts` and existing `notifications.spec.ts`).


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

`test_initial_assignment_delivery.py` additionally verifies real User lookup,
missing/blank-name hold/release, unrelated rejection delivery, transient User
503 recovery, assignment transaction rollback, broker recovery with a renamed
user after freeze and duplicate consumption. The browser regression
`event-assignment-notifications.spec.ts` separately checks the existing bell,
inbox name rendering and event-only link using mocked APIs. No new UI is added.
