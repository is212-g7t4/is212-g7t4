# INDEX.md

A map of every service in this monorepo: what it is, where it lives, and what
it owns. For *why* the architecture looks like this, see
[docs/microservices-catalog.md](docs/microservices-catalog.md) and
[docs/microservices-diagram-notes.md](docs/microservices-diagram-notes.md) —
this file is a directory, not a design rationale.

> **Status:** the React frontend has implemented workflows, including the notification bell/inbox; Notification
> Service and its RabbitMQ consumer are built. See the rows below for each
> service's implemented scope and remaining planned work. User Service remains
> deliberately minimal and read-only.
>
> **Architecture note:** Booking Conflict Service (previously listed as a
> separate atomic) has been merged into Venue Availability Service — see
> that service's row below and its README for why.
>
> **Access control:** every user-facing write route checks the caller's role
> from the token before anything else (SCRUM-10). The per-service READMEs list
> the roles each route requires.

## Repo map

```
is212-g7t4/
├── frontend/
│   └── event-management-ui/            # React SPA — event/venue/safety flows and notification bell/inbox
├── services/
│   ├── event-workflow-service/         # composite (built, edit validation)
│   ├── coordinator-assignment-service/ # composite (built)
│   ├── venue-booking-service/          # composite (built)
│   ├── equipment-reservation-service/  # composite (built, availability check + review)
│   ├── attendee-registration-service/  # composite (built)
│   ├── safety-check-service/           # composite (built, submit/decide/re-check) — safety-check workflow
│   ├── user-service/                   # atomic (built, read-only)
│   ├── event-service/                  # atomic (built)
│   ├── venue-service/                   # atomic (built, read-only)
│   ├── venue-availability-service/     # atomic (built) — owns booking records + conflict-checking
│   ├── equipment-service/              # atomic (built)
│   ├── equipment-request-service/      # atomic (built, request records + review)
│   ├── registration-service/           # atomic (built, read-only)
│   ├── safety-check-record-service/    # atomic (built) — owns the SafetyCheck review rounds
│   ├── notification-service/           # atomic (built; inbox API + consumer), port 5015
│   └── email-sms-wrapper-service/      # wrapper (planned)
├── docs/
├── docker-compose.yml                  # wires up every built service plus RabbitMQ
├── AGENTS.md
├── INDEX.md
└── README.md
```

## Frontend

Unit/component tests remain beside frontend source (`npm test` / `npm run test:coverage`
in `frontend/event-management-ui`). The mocked browser suite and unused lifecycle
helper were retired, not replaced. Real-stack journeys in `e2e/journeys/` stay
manual/opt-in; see [journey traceability](e2e/journeys/TRACEABILITY.md).

| Path | Description | Status |
|---|---|---|
| `frontend/event-management-ui/` | React + TypeScript SPA (Vite). Implemented event/venue/safety flows plus notification bell/inbox, read controls and validated event/venue-request destinations in `frontend/event-management-ui/src/features/notifications/`. Calls composite/atomic services directly — no API gateway. | built (implemented flows) |

## Composite services

Orchestrate one business process across atomics and the broker. Only
composites are allowed to call other services.

| Service | Path | Calls | Description | Status |
|---|---|---|---|---|
| Event Workflow Service | `services/event-workflow-service/` | Event, User, Venue Availability, Venue, Equipment Request, Equipment | SCRUM-20, port 5014: `PATCH /events/:id/details` lets the assigned coordinator, or the Event Coordinator Lead when no coordinator is assigned (role looked up in User Service), edit an event. Event Service classifies the edit with a `dryRun`; a high-impact one is checked against venue bookings (new dates overlap none of the live bookings), equipment stock in the new window and venue capacity (attendance increase), and a contradiction is refused with `409 CHANGE_CONTRADICTS_ARRANGEMENTS` and the reasons. Otherwise Event Service saves it. The change/cancellation cascade and Broker path are not built — **provisional**, see open question below. | built (edit validation) |
| Coordinator Assignment Service | `services/coordinator-assignment-service/` | User, Event, Broker | Assigns/reassigns the Event Coordinator on an event; only the Event Coordinator Lead (role `Event Coordinator Lead`) may do so. | built |
| Venue Booking Service | `services/venue-booking-service/` | Event, Venue, Venue Availability, Safety Check Record, Safety Check, Broker | Submits independently evaluated venue requests (`POST /booking-requests`) with booking-level time, capacity and requirements; rejects submissions unless the event is Submitted, Under Review, Approved or Safety Changes Requested (SCRUM-28); lists every request for an event (`GET /events/<id>/booking-requests`); gives Venue Staff a queue (`GET /booking-requests`) with each event's dates and which requests are awaiting review; Venue Staff review with recorded decision and reason (SCRUM-29): opens one request with the event's timing and requirements (`GET /booking-requests/<id>`), and approves or rejects it (`PATCH /booking-requests/<id>/review`, reason required on reject, decisions final); and provides venue search (`GET /venue-search`, SCRUM-26). Validates event + venue, then persists/conflict-checks via Venue Availability Service. Editing or cancelling a booking is refused while the safety check is pending or the event is closed; on a Confirmed event it first asks Safety Check Service to withdraw the safety approval (event back to Approved) and restores it if the booking change fails (SCRUM-28 Part B). `services/venue-booking-service/app/dispatcher.py` publishes venue-closure rejection notifications through RabbitMQ, with React bell/inbox links to the rejected request. | built |
| Attendee Registration Service | `services/attendee-registration-service/` | Event, Registration, User | Registers an attendee after checking that the event is confirmed, open, and has capacity. Lists registrations with the attendee's name, email and organisation from User Service (`GET /events/<id>/registrations` for coordinators). | built (registration) |
| Equipment Reservation Service | `services/equipment-reservation-service/` | Event, Equipment, Equipment Request, Safety Check Record, User, Broker | Port 5010: submission, read-time availability and Technical Support review. Supplies catalogue/event inputs and exact checked request IDs to Equipment Request for final transactional stock enforcement. Submission creates Pending requests, not stock holds. Owns the separate HTTP/RabbitMQ notification dispatcher. See [service README](services/equipment-reservation-service/README.md). | built (submission, review, in-app alerts) |
| Attendee Registration Service | `services/attendee-registration-service/` | Event, Registration, Broker | Register/withdraw an attendee for an event. | planned |
| Safety Check Service | `services/safety-check-service/` | Event, Venue Availability, Equipment Request, Safety Check Record, User, Venue, (later Broker) | The Operational Safety Check workflow, port 5012. SCRUM-149 builds submit: `POST /safety-checks` checks the caller is the assigned coordinator, gathers every venue booking and equipment request in parallel and lists what's outstanding, creates the round with the coordinator's notes, then moves the event to `Pending Safety Check` (rolling the round back if that fails). SCRUM-150 adds approve: `POST /safety-checks/approve` checks the caller is a Safety Officer via User Service, checks the event is `Pending Safety Check`, decides the open round, then moves the event to `Confirmed` with the internal token (reopening the round if that fails). SCRUM-151 adds the other two decisions, sharing those same steps: `POST /safety-checks/request-changes` (reason + 1-3 area flags) moves the event to `Safety Changes Requested` without touching bookings or equipment; `POST /safety-checks/reject` (reason + `confirmed: true`) moves it to `Cancelled` and then releases every live venue booking via Venue Availability Service. `GET /safety-checks/readiness` is the read-only version for the UI. SCRUM-162 adds `GET /safety-checks/queue`, the Safety Officer's queue: every `Pending Safety Check` event, nearest first, with its venue names (Venue Service), attendance, the open round's submission date and a resubmission flag (`roundNumber > 1`). SCRUM-153 adds re-check: `POST /safety-checks/recheck` withdraws an approval after a high-impact change — it checks the caller is the assigned coordinator, the event is `Confirmed` and a high-impact field really changes, withdraws round N and opens round N+1 (one transaction in Record Service, whose row lock is the race guard), then saves the edit and moves the event to `Pending Safety Check` via `PATCH /events/:id/details` (restoring the withdrawal if that fails). Resubmit (SCRUM-164) and the notification are not built. | built (submit, approve, request changes, reject, queue, re-check) |

## Atomic services

Each owns exactly one entity/concern and its own data store. Atomics never
call another service or the broker.

| Service | Path | Data store | Owns | Status |
|---|---|---|---|---|
| User | `services/user-service/` | Supabase Postgres | Accounts, roles, manager relationship. `GET /users`, `GET /users/:id`, and `POST /auth/login` (SCRUM-8), which exchanges email + password for a Supabase Auth access token; no sign-up | built (read-only + login) |
| Event | `services/event-service/` | Supabase Postgres | Event entity: details, status, change-request records and append-only event clarification rounds. An organiser may create one pending change request for their own `Submitted`, `Under Review` or `Approved` event; the proposal records its changed fields, justification, identity and timestamp without mutating the event. An assigned coordinator can request clarification from `Submitted`/`Under Review`; the organiser response returns it to `Submitted` without changing the assignment or original fields. Blocks any non-safety move into `Confirmed` (SCRUM-152). `PATCH /events/:id/safety-status` (Safety Check Service only; role-gated and, without `INTERNAL_SERVICE_TOKEN`, refused with `503`, SCRUM-10) also moves `Pending Safety Check` to `Safety Changes Requested` or `Cancelled` (SCRUM-151); `Cancelled` is terminal — no move leaves it. SCRUM-153 adds `PATCH /events/:id/details`, the one endpoint that edits an event's details and the single authority on the low/high-impact split (`LOW_IMPACT_FIELDS` / `HIGH_IMPACT_FIELDS`, shared with SCRUM-20): a low-impact edit saves in place, a high-impact edit of a `Confirmed` event is refused with `409 SAFETY_RECHECK_REQUIRED` unless it carries the internal token and the new round — with them it saves the fields *and* moves `Confirmed → Pending Safety Check` in one transaction. That move is in `SAFETY_TRANSITIONS` but listed in `RECHECK_ONLY_MOVES`, so `/safety-status` refuses it on its own. | built |
| Venue | `services/venue-service/` | Supabase Postgres | Venue catalogue (capacity, facilities, accessibility, layouts) + suitability-check computation. Read-only: `GET /venues` (catalogue, with SCRUM-26's optional `minCapacity`/`location`/`layout`/`facility`/`accessibility` filters — the suitability check) and `GET /venues/:id` (one venue's full profile, SCRUM-24) | built (read-only; no add/edit yet) |
| Venue Availability | `services/venue-availability-service/` | Supabase Postgres | Venue booking records (`public."VenueBooking"`), booking-level capacity/requirements, timed holds (`On Hold` rows in `public."VenueBooking"`), and the overlap/conflict-checking algorithm together. Reads include one venue's calendar, all bookings/holds in a search window, and all bookings linked to one event. Conflicts are scoped by venue and time, never merely by event. | built |
| Equipment | `services/equipment-service/` | Supabase Postgres | Equipment catalogue only (types, quantities owned, technical specs) — no reservation data. `GET /equipment[?status=]` and `POST /equipment` (Technical Support only) | built (list + add; no edit/delete yet) |
| Registration | `services/registration-service/` | Supabase Postgres | Attendee registration records (attendee ID only; one row per event and attendee). Supports read lookups/counts and an internal write used by Attendee Registration Service with duplicate and capacity enforcement; re-registering after withdrawal reuses the row. | built |
| Equipment Request | `services/equipment-request-service/` | Supabase Postgres | Equipment request records (`public."EquipmentRequest"`) and their Pending/Approved/Rejected status. `GET /equipment-requests[?status=&eventId=&eventIds=]`, `GET /equipment-requests/:id`, `PATCH /equipment-requests/:id` and `PATCH /events/:id/equipment-requests` (Technical Support, SCRUM-33). Owns final stock enforcement: reads current owner allocations after a shared transaction lock and commits the checked approval selection with its notification outbox. Catalogue/event inputs come from Equipment Reservation; their provenance and concurrent external changes are outside this transaction guarantee. See [service README](services/equipment-request-service/README.md) | built (records + review) |
| Registration | `services/registration-service/` | Supabase Postgres | Attendee registration records. Read-only (`GET /registrations?eventId=`) — no registration/withdrawal endpoints yet; called directly by the frontend (a "simple read," no composite needed) | built (read-only) |
| Safety Check Record | `services/safety-check-record-service/` | Supabase Postgres | Operational Safety Check records (`public."SafetyCheck"`), port 5013 — one row per **review round**, so earlier decisions stay visible as history. `POST /safety-check-records` opens round N+1 and refuses a new round while one is `Pending` (`UNIQUE (event_id, round_number)` behind it); `GET /safety-check-records?eventId=[&status=]` lists rounds newest first with each round's flags; `PATCH /safety-check-records/:id/decision` decides the open round under `FOR UPDATE` (SCRUM-150's race guard) as `Safety Approved`, `Changes Requested` (1-3 `SafetyCheckFlag` rows, area-level only) or `Safety Rejected` (SCRUM-151); `DELETE /safety-check-records/:id` and `POST /safety-check-records/:id/reopen` undo a create/decide for Safety Check Service's rollback only, the latter also clearing the round's flags. SCRUM-153 adds `POST /safety-check-records/:id/withdraw`, which in one transaction turns round N from `Safety Approved` into `Approval Withdrawn` (keeping its decision fields, plus `withdrawn_at`/`withdrawn_by`/`withdrawal_reason`) and opens round N+1 as `Pending` with round N's notes — its `FOR UPDATE` is the re-check's race guard; `POST /safety-check-records/:id/restore` undoes that, for Safety Check Service's rollback only. | built (records, decide, withdraw) |
| Notification | `services/notification-service/` | Supabase Postgres | Inbox list/unread count/read-state API on host port 5015; `services/notification-service/app/consumer.py` consumes durable `notifications.v1` messages into PostgreSQL. Malformed-message diagnostics/replay in `services/notification-service/app/diagnostics.py`; bell/inbox UI lives in `frontend/event-management-ui/src/features/notifications/`. Email/SMS delivery is not implemented. | built (in-app notifications) |

## Infrastructure

| Component | Path / source | Description | Status |
|---|---|---|---|
| Message Broker | RabbitMQ image, `docker-compose.yml` | Durable `notifications.v1` queue; loopback AMQP 5672 / management 15672; persistent `notification-rabbitmq-data` volume. Composite dispatchers publish; the consumer in `services/notification-service/` stores inbox records. | configured in Compose |
| Email/SMS Wrapper | `services/email-sms-wrapper-service/` | Wraps the external email/SMS provider; called only by Notification Service | planned |

## Running one service locally

Optional host execution, not an extra step after Docker startup. For Equipment Request, first configure its `.env` from its `.env.example` without overwriting existing settings, then run from the repository root:

```bash
cd services/equipment-request-service
uv sync --locked --python 3.12
uv run --env-file .env flask --app app run --port 5011
```

Do not run this alongside a container binding port 5011. Other services need their own configured environment and port. For unit tests from the service directory:

```bash
PYTHON_DOTENV_DISABLED=1 uv run --no-env-file --locked --python 3.12 pytest
```

## Running everything locally

`docker-compose.yml` wires up every service built so far — add a service
entry there each time a new service is created (see the comment in that
file).

```
npm run dev          # frontend (Vite) + backend (docker compose up), together
npm run dev:frontend # frontend only
npm run dev:backend  # backend only, via docker compose up
```

Install root/frontend JavaScript dependencies and configure the required environment files before startup; Docker builds install backend dependencies in their images. Database migrations and accounts must already be prepared; see [database setup](docs/supabase-setup.md). Full startup includes notification workers that may process shared database work: coordinate with the team first.

`docker compose up` brings up the configured Flask services, RabbitMQ and workers; it does not provision the databases. Stop the frontend with Ctrl+C and the backend with `docker compose down` (without `-v`, to preserve volumes).
Supabase stays cloud-hosted (not run locally) — each service
reads its connection string from its own `.env`.

## Open architecture questions

Tracked in detail in [docs/microservices-catalog.md](docs/microservices-catalog.md)
and referenced in [AGENTS.md](AGENTS.md):

- Whether Event Workflow Service is needed at all.
