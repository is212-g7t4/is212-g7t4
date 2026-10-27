# Coordinator assignment

Assigns or reassigns the Event Coordinator on an event. A composite — holds
no data of its own, calls `user-service` (to validate coordinators and check
who's making the request) and `event-service` (to persist the assignment).

## 1. Start the service

Copy `.env.example` to `.env` — the defaults already match the Docker
Compose service names for `USER_SERVICE_URL`/`EVENT_SERVICE_URL` (see the
comment in that file for the localhost equivalents if running outside
Docker):

```
cp .env.example services/coordinator-assignment-service/.env
```

Then run:

```
cd services/coordinator-assignment-service
uv sync
uv run --env-file .env flask --app app run --port 5004
```

Alternatively, after creating `.env`, run
`docker compose up --build coordinator-assignment-service` from the
repository root — or just `npm run dev`/`npm run dev:backend`, which brings
this up alongside every other service.

## Endpoints

- `GET /coordinators` — everyone an event can be assigned to: the Event
  Coordinator Lead (so the Lead can take an event on themselves) and every
  Event Coordinator, fetched from `user-service`.
- `GET /queue?actingUserId=<user id>` — the Lead's assignment worklist:
  unassigned `Submitted` requests and assigned `Under Review` requests, oldest
  submission first (from `event-service`'s `GET /events/submitted`). Only the
  Event Coordinator Lead may view it — `403` for everyone else, `400` without
  `actingUserId`. Assigned requests remain visible so the Lead can reassign
  them without leaving the worklist.
- `GET /workload?actingUserId=<user id>` — the Lead's read-only workload
  view: every coordinator from `GET /coordinators` (the Lead included, and
  those with nothing assigned) with their active events under `events`, plus
  `unassigned` (active events with no coordinator) and `otherAssigned`
  (events whose coordinator is no longer an Event Coordinator, so they don't
  silently vanish). Events come from `event-service`'s `GET /events/active`,
  which leaves out `Confirmed`, `Rejected` and `Cancelled`. Only the Event
  Coordinator Lead may view it — `403` for everyone else, `400` without
  `actingUserId`.
- `POST /events/<event_id>/assign-coordinator/<coordinator_id>` — assigns or
  reassigns the coordinator on an event. Body must include
  `{"actingUserId": "<user id>"}`; only the Event Coordinator Lead (role
  `Event Coordinator Lead`) may do this — `403` otherwise.
  Validates `coordinator_id` is a real, available Event Coordinator before
  calling `event-service` to persist the change. The acting Lead is sent as
  `assignedBy`; `event-service` stores it with the assignment time
  (`assigned_by`/`assigned_at`) and returns both as `assignedBy`/`assignedAt`
  for the event's detail page. On a reassignment it also keeps the
  outgoing coordinator as `previousCoordinatorId` (latest handover only).
  `event-service` refuses with `409` — passed through with its message —
  when the event is `Rejected`/`Cancelled` or the coordinator is already the
  assigned one (no change). Venue bookings, equipment requests and safety
  checks authorise against the event's current coordinator, so they move to
  the new coordinator with no further calls.

## Known limitation

No Forum Service call yet for logging the assignment/reassignment reason —
flagged as an open architecture question in `AGENTS.md`/`docs/microservices-catalog.md`
(whether this composite needs one at all, since most assignments won't have
a reason worth logging).

## Tests

Run the hermetic unit tier (the default):

```bash
uv run pytest
```

Run the opt-in SCRUM-112 composite integration tier:

```bash
uv run pytest -m integration --no-cov
```

The integration tests run the real Flask routes and `httpx` client code while
`respx` controls User Service and Event Service at their HTTP boundaries. They
require no live services, database, or secrets.
