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

## SCRUM-45 rejection dispatcher

Run a separate `uv run python -m app.dispatcher` process; Flask requests never
publish notifications. Compose starts `event-notification-dispatcher` from this
same image. Configure `EVENT_SERVICE_URL`, `INTERNAL_SERVICE_TOKEN` (must match
Event Service) and `RABBITMQ_URL`. Missing/mismatched tokens fail closed.

Install `20261021000000_event_notification_outbox.sql` on the **Event-owned**
database before enabling new rejections. The existing Notification inbox
migration belongs on its own database. This slice adds no backfill, approval or
assignment notifications. Both rejection entry paths save historical source
facts in the same transaction as the event mutation. Ownerless legacy changes
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
available, first `uv sync --locked` in Event, Notification and Event Workflow,
then from Event Workflow:

```sh
uv run --with psycopg2-binary python -m pytest -m integration --no-cov
```

The tests own disposable UUID-named containers, two separate databases, real
HTTP/consumer/worker processes, synthetic identities and finally cleanup.
They disable dotenv and never use a remote database. They check both rejection
paths, broker outage/recovery, duplicate delivery/read-state preservation,
recipient isolation and real mutation rollback. Use `python -m pytest` so uv's
overlay driver is available; the bare pytest executable uses its venv shebang.
Browser checks remain separate mocked Playwright journeys, not persistence
proof (`event-rejection-notifications.spec.ts` and existing `notifications.spec.ts`).
