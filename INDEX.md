# INDEX.md

A map of every service in this monorepo: what it is, where it lives, and what
it owns. For *why* the architecture looks like this, see
[docs/microservices-catalog.md](docs/microservices-catalog.md) and
[docs/microservices-diagram-notes.md](docs/microservices-diagram-notes.md) —
this file is a directory, not a design rationale.

> **Status:** two template services and the frontend's dependencies are
> scaffolded (see below); the 15 real services listed in this file are still
> **planned** — copy the matching template to create each one. Update the
> status column as each service is actually created.

## Repo map

```
is212-g7t4/
├── frontend/
│   └── event-management-ui/            # React SPA — Vite scaffold, deps installed, no real UI yet
├── services/
│   ├── _template-atomic-service/       # copy this to start any atomic service
│   ├── _template-composite-service/    # copy this to start any composite service
│   ├── event-workflow-service/         # composite (planned)
│   ├── coordinator-assignment-service/ # composite (planned)
│   ├── venue-booking-service/          # composite (planned)
│   ├── equipment-reservation-service/  # composite (planned)
│   ├── attendee-registration-service/  # composite (planned)
│   ├── user-service/                   # atomic (planned)
│   ├── event-service/                  # atomic (planned)
│   ├── venue-service/                  # atomic (planned)
│   ├── booking-conflict-service/       # atomic (planned)
│   ├── venue-availability-service/     # atomic (planned)
│   ├── equipment-service/              # atomic (planned)
│   ├── equipment-availability-service/ # atomic (planned)
│   ├── registration-service/           # atomic (planned)
│   ├── notification-service/           # atomic (planned)
│   ├── forum-service/                  # atomic, MongoDB (planned)
│   └── email-sms-wrapper-service/      # wrapper (planned)
├── docs/
├── docker-compose.yml                  # planned — not yet created
├── AGENTS.md
├── INDEX.md
└── README.md
```

## Templates

Two minimal, non-working skeletons that exist purely to fix the file
structure every real service should follow — Flask app factory, `uv`-managed
`pyproject.toml`/`uv.lock`, a `/health` route, one passing test, Dockerfile,
and `.env.example`. Copy one, rename it, then fill in the real logic.

| Template | Path | Distinguishing feature | Status |
|---|---|---|---|
| Atomic | `services/_template-atomic-service/` | Has `app/models.py`; no HTTP client — atomics never call out | scaffolded |
| Composite | `services/_template-composite-service/` | Has `app/clients.py` (httpx) for calling downstream services; no `models.py` — composites hold no data | scaffolded |

## Frontend

| Path | Description | Status |
|---|---|---|
| `frontend/event-management-ui/` | React + TypeScript SPA (Vite default template). Dependencies installed via `npm install`; no app code written yet. Calls composite/atomic services directly — no API gateway. | deps installed |

## Composite services

Orchestrate one business process across atomics, Forum, and the broker. Only
composites are allowed to call other services.

| Service | Path | Calls | Description | Status |
|---|---|---|---|---|
| Event Workflow Service | `services/event-workflow-service/` | Booking Conflict, Equipment Availability, Forum, Broker | Re-validates existing venue/equipment commitments on event change; cascades cancellations. **Provisional** — see open question below. | planned |
| Coordinator Assignment Service | `services/coordinator-assignment-service/` | User, Event, Forum, Broker | Assigns/reassigns the Event Coordinator on an event. | planned |
| Venue Booking Service | `services/venue-booking-service/` | Event, Venue, Booking Conflict, Venue Availabilities, Forum, Broker | Two sub-flows: booking request submission, and venue-staff approval/rejection. | planned |
| Equipment Reservation Service | `services/equipment-reservation-service/` | Event, Equipment Availability, Forum, Broker | Two sub-flows: request submission, and technical-support approval/rejection. | planned |
| Attendee Registration Service | `services/attendee-registration-service/` | Event, Registration, Broker | Register/withdraw an attendee for an event. No Forum call. | planned |

## Atomic services

Each owns exactly one entity/concern and its own data store. Atomics never
call another service, Forum, or the broker.

| Service | Path | Data store | Owns | Status |
|---|---|---|---|---|
| User | `services/user-service/` | Supabase Postgres + Supabase Auth | Accounts, roles, login/JWT issuance | planned |
| Event | `services/event-service/` | Supabase Postgres | Event entity: details, status, change-request records | planned |
| Venue | `services/venue-service/` | Supabase Postgres | Venue catalogue (capacity, facilities, accessibility, layouts) + suitability-check computation | planned |
| Booking Conflict | `services/booking-conflict-service/` | Supabase Postgres | Conflict-detection algorithm only — no booking records | planned |
| Venue Availabilities | `services/venue-availability-service/` | Supabase Postgres | Actual venue booking records: id, eventId, venueId, status, proposed date/time, decision reason | planned |
| Equipment | `services/equipment-service/` | Supabase Postgres | Equipment catalogue only (types, quantities owned, technical specs) — no reservation data | planned |
| Equipment Availability | `services/equipment-availability-service/` | Supabase Postgres | Reservation records + availability-checking algorithm | planned |
| Registration | `services/registration-service/` | Supabase Postgres | Attendee registration records | planned |
| Notification | `services/notification-service/` | Supabase Postgres | Notification records; consumes the broker queue, calls the Email/SMS Wrapper | planned |
| Forum / Communication | `services/forum-service/` | **MongoDB (Atlas)** | All communication tied to a request — clarifications, approval/rejection reasons, comments — keyed by `entityType` + `entityId` | planned |

## Infrastructure

| Component | Path / source | Description | Status |
|---|---|---|---|
| Message Broker | RabbitMQ image, `docker-compose.yml` | The only async path — composites publish, Notification Service consumes | planned |
| Email/SMS Wrapper | `services/email-sms-wrapper-service/` | Wraps the external email/SMS provider; called only by Notification Service | planned |

## Running a template (or any scaffolded service) locally

```
cd services/_template-atomic-service   # or _template-composite-service
uv sync
uv run flask --app app run --debug
uv run pytest
```

## Running everything locally (once real services + docker-compose.yml exist)

```
docker compose up
```

Will bring up every Flask service + RabbitMQ. Supabase and MongoDB Atlas stay
cloud-hosted (not run locally) — each service reads its connection string
from its own `.env`.

## Open architecture questions

Tracked in detail in [docs/microservices-catalog.md](docs/microservices-catalog.md)
and referenced in [AGENTS.md](AGENTS.md):

- Whether Event Workflow Service is needed at all.
- Whether Coordinator Assignment Service actually needs a Forum call.
