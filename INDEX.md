# INDEX.md

A map of every service in this monorepo: what it is, where it lives, and what
it owns. For *why* the architecture looks like this, see
[docs/microservices-catalog.md](docs/microservices-catalog.md) and
[docs/microservices-diagram-notes.md](docs/microservices-diagram-notes.md) —
this file is a directory, not a design rationale.

> **Status:** two template services and the frontend's dependencies are
> scaffolded (see below); User, Event, Coordinator Assignment, Registration,
> Venue, Venue Booking, and Venue Availability are built (see their rows
> below — User remains deliberately minimal and read-only
> of their eventually-planned scope); the remaining real services in this
> file are still **planned** — copy the matching template to create each
> one. Update the status column as each service is actually created.
>
> **Architecture note:** Booking Conflict Service (previously listed as a
> separate atomic) has been merged into Venue Availability Service — see
> that service's row below and its README for why.

## Repo map

```
is212-g7t4/
├── frontend/
│   └── event-management-ui/            # React SPA — Vite scaffold, deps installed, no real UI yet
├── services/
│   ├── _template-atomic-service/       # copy this to start any atomic service
│   ├── _template-composite-service/    # copy this to start any composite service
│   ├── event-workflow-service/         # composite (planned)
│   ├── coordinator-assignment-service/ # composite (built)
│   ├── venue-booking-service/          # composite (built)
│   ├── equipment-reservation-service/  # composite (built, availability check + review)
│   ├── attendee-registration-service/  # composite (built)
│   ├── user-service/                   # atomic (built, read-only)
│   ├── event-service/                  # atomic (built)
│   ├── venue-service/                   # atomic (built, read-only)
│   ├── venue-availability-service/     # atomic (built) — owns booking records + conflict-checking
│   ├── equipment-service/              # atomic (built)
│   ├── equipment-request-service/      # atomic (built, request records + review)
│   ├── registration-service/           # atomic (built, read-only)
│   ├── notification-service/           # atomic (planned)
│   ├── forum-service/                  # atomic, MongoDB (planned)
│   └── email-sms-wrapper-service/      # wrapper (planned)
├── docs/
├── docker-compose.yml                  # wires up User, Event, Coordinator Assignment, Registration, plus the composite template placeholder
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
| Event Workflow Service | `services/event-workflow-service/` | Booking Conflict, Equipment Request, Forum, Broker | Re-validates existing venue/equipment commitments on event change; cascades cancellations. **Provisional** — see open question below. | planned |
| Coordinator Assignment Service | `services/coordinator-assignment-service/` | User, Event, Forum, Broker | Assigns/reassigns the Event Coordinator on an event; only the Event Coordinator manager may do so. No Forum call yet. | built |
| Venue Booking Service | `services/venue-booking-service/` | Event, Venue, Venue Availability, Forum, Broker | Three sub-flows: booking request submission (`POST /booking-requests`), venue-staff approval/rejection (`PATCH /booking-requests/<id>/approve\|reject`), and venue search (`GET /venue-search`, SCRUM-26 — filters the catalogue via Venue Service and merges it with the window's bookings from Venue Availability Service, in parallel; read-only). Validates event + venue, then persists/conflict-checks via Venue Availability Service. No Forum call/notification yet. | built |
| Equipment Reservation Service | `services/equipment-reservation-service/` | Event, Equipment Availability, Forum, Broker | Two sub-flows: request submission, and technical-support approval/rejection. | planned |
| Attendee Registration Service | `services/attendee-registration-service/` | Event, Registration | Registers an attendee after checking that the event is confirmed, open, and has capacity. No Forum call. | built (registration) |
| Equipment Reservation Service | `services/equipment-reservation-service/` | Event, Equipment, Equipment Request | Availability checking and review validation (SCRUM-33), port 5010: `GET /equipment-reservations` groups requests by event with each Pending line's two-stage availability (physical status, then total less quantity held by Approved lines of other non-rejected events overlapping the window); `PATCH /equipment-reservations/requests/:id` and `.../events/:id` approve/reject, blocking Approve while any line is insufficient. Request submission not built yet; no Forum call/notification. | built (review) |
| Attendee Registration Service | `services/attendee-registration-service/` | Event, Registration, Broker | Register/withdraw an attendee for an event. No Forum call. | planned |

## Atomic services

Each owns exactly one entity/concern and its own data store. Atomics never
call another service, Forum, or the broker.

| Service | Path | Data store | Owns | Status |
|---|---|---|---|---|
| User | `services/user-service/` | Supabase Postgres | Accounts, roles, manager relationship. Read-only (`GET /users`, `GET /users/:id`) — Supabase Auth/login/JWT issuance not implemented yet | built (read-only) |
| Event | `services/event-service/` | Supabase Postgres | Event entity: details, status, change-request records | built |
| Venue | `services/venue-service/` | Supabase Postgres | Venue catalogue (capacity, facilities, accessibility, layouts) + suitability-check computation. Read-only: `GET /venues` (catalogue, with SCRUM-26's optional `minCapacity`/`location`/`layout`/`facility`/`accessibility` filters — the suitability check) and `GET /venues/:id` (one venue's full profile, SCRUM-24) | built (read-only; no add/edit yet) |
| Venue Availability | `services/venue-availability-service/` | Supabase Postgres | Venue booking records (`public."VenueBooking"`), timed holds (`public."VenueHold"`), and the overlap/conflict-checking algorithm together — merged design, see the service's README. Replaces the previously separate Booking Conflict Service. Reads: `GET /venue-bookings` (one venue, SCRUM-25's calendar), `GET /venue-bookings/window` (all bookings and holds in a window, for SCRUM-26's search), and `GET /venue-holds` (active holds); `POST /venue-holds` creates a Venue Staff hold with expiry. | built |
| Equipment | `services/equipment-service/` | Supabase Postgres | Equipment catalogue only (types, quantities owned, technical specs) — no reservation data. `GET /equipment[?status=]` and `POST /equipment` (Technical Support only, DEV headers) | built (list + add; no edit/delete yet) |
| Equipment Availability | `services/equipment-availability-service/` | Supabase Postgres | Reservation records + availability-checking algorithm | planned |
| Registration | `services/registration-service/` | Supabase Postgres | Attendee registration records. Supports read lookups/counts and an internal write used by Attendee Registration Service with duplicate and capacity enforcement. | built |
| Equipment Request | `services/equipment-request-service/` | Supabase Postgres | Equipment request records (`public."EquipmentRequest"`) and their Pending/Approved/Rejected status. `GET /equipment-requests[?status=&eventId=&eventIds=]`, `GET /equipment-requests/:id`, `PATCH /equipment-requests/:id` and `PATCH /events/:id/equipment-requests` (Technical Support, SCRUM-33). Does no availability checking — that is Equipment Reservation Service | built (records + review) |
| Registration | `services/registration-service/` | Supabase Postgres | Attendee registration records. Read-only (`GET /registrations?eventId=`) — no registration/withdrawal endpoints yet; called directly by the frontend (a "simple read," no composite needed) | built (read-only) |
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

## Running everything locally

`docker-compose.yml` wires up the composite template placeholder plus the
real services built so far (User, Event, Coordinator Assignment,
Registration, Venue, Venue Booking, Venue Availability) — add a service
entry there each time another real service is copied from a template (see
the comment in that file).

```
npm run dev          # frontend (Vite) + backend (docker compose up), together
npm run dev:frontend # frontend only
npm run dev:backend  # backend only, via docker compose up
```

`docker compose up` will eventually bring up every Flask service + RabbitMQ.
Supabase and MongoDB Atlas stay cloud-hosted (not run locally) — each service
reads its connection string from its own `.env`.

## Open architecture questions

Tracked in detail in [docs/microservices-catalog.md](docs/microservices-catalog.md)
and referenced in [AGENTS.md](AGENTS.md):

- Whether Event Workflow Service is needed at all.
- Whether Coordinator Assignment Service actually needs a Forum call.
