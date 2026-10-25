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
| Event Workflow Service | `services/event-workflow-service/` | Event, User, Venue Availability, Venue, Equipment Request, Equipment | SCRUM-20, port 5014: `PATCH /events/:id/details` lets the assigned coordinator, or the Event Coordinator Lead when no coordinator is assigned (role looked up in User Service), edit an event. Event Service classifies the edit with a `dryRun`; a high-impact one is checked against venue bookings (new dates overlap none of the live bookings), equipment stock in the new window and venue capacity (attendance increase), and a contradiction is refused with `409 CHANGE_CONTRADICTS_ARRANGEMENTS` and the reasons. Otherwise Event Service saves it. The change/cancellation cascade, Forum and Broker are not built — **provisional**, see open question below. | built (edit validation) |
| Coordinator Assignment Service | `services/coordinator-assignment-service/` | User, Event, Forum, Broker | Assigns/reassigns the Event Coordinator on an event; only the Event Coordinator Lead (role `Event Coordinator Lead`) may do so. No Forum call yet. | built |
| Venue Booking Service | `services/venue-booking-service/` | Event, Venue, Venue Availability, Safety Check Record, Safety Check, Forum, Broker | Submits independently evaluated venue requests (`POST /booking-requests`) with booking-level time, capacity and requirements; rejects submissions unless the event is Submitted, Under Review, Approved or Safety Changes Requested (SCRUM-28); lists every request for an event (`GET /events/<id>/booking-requests`); gives Venue Staff a queue (`GET /booking-requests`) with each event's dates and which requests are awaiting review, plus approval/rejection; and provides venue search (`GET /venue-search`, SCRUM-26). Validates event + venue, then persists/conflict-checks via Venue Availability Service. Editing or cancelling a booking is refused while the safety check is pending or the event is closed; on a Confirmed event it first asks Safety Check Service to withdraw the safety approval (event back to Approved) and restores it if the booking change fails (SCRUM-28 Part B). No Forum call/notification yet. | built |
| Equipment Reservation Service | `services/equipment-reservation-service/` | Event, Equipment Availability, Forum, Broker | Two sub-flows: request submission, and technical-support approval/rejection. | planned |
| Attendee Registration Service | `services/attendee-registration-service/` | Event, Registration, User | Registers an attendee after checking that the event is confirmed, open, and has capacity. Lists registrations with the attendee's name, email and organisation from User Service (`GET /events/<id>/registrations` for coordinators). No Forum call. | built (registration) |
| Equipment Reservation Service | `services/equipment-reservation-service/` | Event, Equipment, Equipment Request | Availability checking and review validation (SCRUM-33), port 5010: `GET /equipment-reservations` groups requests by event with each Pending line's two-stage availability (physical status, then total less quantity held by Approved lines of other non-rejected events overlapping the window); `PATCH /equipment-reservations/requests/:id` and `.../events/:id` approve/reject, blocking Approve while any line is insufficient. Request submission not built yet; no Forum call/notification. | built (review) |
| Attendee Registration Service | `services/attendee-registration-service/` | Event, Registration, Broker | Register/withdraw an attendee for an event. No Forum call. | planned |
| Safety Check Service | `services/safety-check-service/` | Event, Venue Availability, Equipment Request, Safety Check Record, User, Venue, (later Forum, Broker) | The Operational Safety Check workflow, port 5012. SCRUM-149 builds submit: `POST /safety-checks` checks the caller is the assigned coordinator, gathers every venue booking and equipment request in parallel and lists what's outstanding, creates the round with the coordinator's notes, then moves the event to `Pending Safety Check` (rolling the round back if that fails). SCRUM-150 adds approve: `POST /safety-checks/approve` checks the caller is a Safety Officer via User Service, checks the event is `Pending Safety Check`, decides the open round, then moves the event to `Confirmed` with the internal token (reopening the round if that fails). SCRUM-151 adds the other two decisions, sharing those same steps: `POST /safety-checks/request-changes` (reason + 1-3 area flags) moves the event to `Safety Changes Requested` without touching bookings or equipment; `POST /safety-checks/reject` (reason + `confirmed: true`) moves it to `Cancelled` and then releases every live venue booking via Venue Availability Service. `GET /safety-checks/readiness` is the read-only version for the UI. SCRUM-162 adds `GET /safety-checks/queue`, the Safety Officer's queue: every `Pending Safety Check` event, nearest first, with its venue names (Venue Service), attendance, the open round's submission date and a resubmission flag (`roundNumber > 1`). SCRUM-153 adds re-check: `POST /safety-checks/recheck` withdraws an approval after a high-impact change — it checks the caller is the assigned coordinator, the event is `Confirmed` and a high-impact field really changes, withdraws round N and opens round N+1 (one transaction in Record Service, whose row lock is the race guard), then saves the edit and moves the event to `Pending Safety Check` via `PATCH /events/:id/details` (restoring the withdrawal if that fails). Resubmit (SCRUM-164) and the notification are not built. | built (submit, approve, request changes, reject, queue, re-check) |

## Atomic services

Each owns exactly one entity/concern and its own data store. Atomics never
call another service, Forum, or the broker.

| Service | Path | Data store | Owns | Status |
|---|---|---|---|---|
| User | `services/user-service/` | Supabase Postgres | Accounts, roles, manager relationship. Read-only (`GET /users`, `GET /users/:id`) — Supabase Auth/login/JWT issuance not implemented yet | built (read-only) |
| Event | `services/event-service/` | Supabase Postgres | Event entity: details, status, change-request records and, provisionally until Forum Service exists, append-only event clarification rounds. An organiser may create one pending change request for their own `Submitted`, `Under Review` or `Approved` event; the proposal records its changed fields, justification, identity and timestamp without mutating the event. An assigned coordinator can request clarification from `Submitted`/`Under Review`; the organiser response returns it to `Submitted` without changing the assignment or original fields. Blocks any non-safety move into `Confirmed` (SCRUM-152). `PATCH /events/:id/safety-status` (Safety Check Service only) also moves `Pending Safety Check` to `Safety Changes Requested` or `Cancelled` (SCRUM-151); `Cancelled` is terminal — no move leaves it. SCRUM-153 adds `PATCH /events/:id/details`, the one endpoint that edits an event's details and the single authority on the low/high-impact split (`LOW_IMPACT_FIELDS` / `HIGH_IMPACT_FIELDS`, shared with SCRUM-20): a low-impact edit saves in place, a high-impact edit of a `Confirmed` event is refused with `409 SAFETY_RECHECK_REQUIRED` unless it carries the internal token and the new round — with them it saves the fields *and* moves `Confirmed → Pending Safety Check` in one transaction. That move is in `SAFETY_TRANSITIONS` but listed in `RECHECK_ONLY_MOVES`, so `/safety-status` refuses it on its own. | built |
| Venue | `services/venue-service/` | Supabase Postgres | Venue catalogue (capacity, facilities, accessibility, layouts) + suitability-check computation. Read-only: `GET /venues` (catalogue, with SCRUM-26's optional `minCapacity`/`location`/`layout`/`facility`/`accessibility` filters — the suitability check) and `GET /venues/:id` (one venue's full profile, SCRUM-24) | built (read-only; no add/edit yet) |
| Venue Availability | `services/venue-availability-service/` | Supabase Postgres | Venue booking records (`public."VenueBooking"`), booking-level capacity/requirements, timed holds (`On Hold` rows in `public."VenueBooking"`), and the overlap/conflict-checking algorithm together. Reads include one venue's calendar, all bookings/holds in a search window, and all bookings linked to one event. Conflicts are scoped by venue and time, never merely by event. | built |
| Equipment | `services/equipment-service/` | Supabase Postgres | Equipment catalogue only (types, quantities owned, technical specs) — no reservation data. `GET /equipment[?status=]` and `POST /equipment` (Technical Support only, DEV headers) | built (list + add; no edit/delete yet) |
| Equipment Availability | `services/equipment-availability-service/` | Supabase Postgres | Reservation records + availability-checking algorithm | planned |
| Registration | `services/registration-service/` | Supabase Postgres | Attendee registration records (attendee ID only; one row per event and attendee). Supports read lookups/counts and an internal write used by Attendee Registration Service with duplicate and capacity enforcement; re-registering after withdrawal reuses the row. | built |
| Equipment Request | `services/equipment-request-service/` | Supabase Postgres | Equipment request records (`public."EquipmentRequest"`) and their Pending/Approved/Rejected status. `GET /equipment-requests[?status=&eventId=&eventIds=]`, `GET /equipment-requests/:id`, `PATCH /equipment-requests/:id` and `PATCH /events/:id/equipment-requests` (Technical Support, SCRUM-33). Does no availability checking — that is Equipment Reservation Service | built (records + review) |
| Registration | `services/registration-service/` | Supabase Postgres | Attendee registration records. Read-only (`GET /registrations?eventId=`) — no registration/withdrawal endpoints yet; called directly by the frontend (a "simple read," no composite needed) | built (read-only) |
| Safety Check Record | `services/safety-check-record-service/` | Supabase Postgres | Operational Safety Check records (`public."SafetyCheck"`), port 5013 — one row per **review round**, so earlier decisions stay visible as history. `POST /safety-check-records` opens round N+1 and refuses a new round while one is `Pending` (`UNIQUE (event_id, round_number)` behind it); `GET /safety-check-records?eventId=[&status=]` lists rounds newest first with each round's flags; `PATCH /safety-check-records/:id/decision` decides the open round under `FOR UPDATE` (SCRUM-150's race guard) as `Safety Approved`, `Changes Requested` (1-3 `SafetyCheckFlag` rows, area-level only) or `Safety Rejected` (SCRUM-151); `DELETE /safety-check-records/:id` and `POST /safety-check-records/:id/reopen` undo a create/decide for Safety Check Service's rollback only, the latter also clearing the round's flags. SCRUM-153 adds `POST /safety-check-records/:id/withdraw`, which in one transaction turns round N from `Safety Approved` into `Approval Withdrawn` (keeping its decision fields, plus `withdrawn_at`/`withdrawn_by`/`withdrawal_reason`) and opens round N+1 as `Pending` with round N's notes — its `FOR UPDATE` is the re-check's race guard; `POST /safety-check-records/:id/restore` undoes that, for Safety Check Service's rollback only. | built (records, decide, withdraw) |
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
