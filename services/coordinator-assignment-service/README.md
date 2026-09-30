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

- `GET /coordinators` — every Event Coordinator, fetched from `user-service`.
- `POST /events/<event_id>/assign-coordinator/<coordinator_id>` — assigns or
  reassigns the coordinator on an event. Body must include
  `{"actingUserId": "<user id>"}`; only the Event Coordinator manager (role
  `Event Coordinator`, `manager_id` is `null`) may do this — `403` otherwise.
  Validates `coordinator_id` is a real, available Event Coordinator before
  calling `event-service` to persist the change.

## Known limitation

No Forum Service call yet for logging the assignment/reassignment reason —
flagged as an open architecture question in `AGENTS.md`/`docs/microservices-catalog.md`
(whether this composite needs one at all, since most assignments won't have
a reason worth logging).
