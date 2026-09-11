# AGENTS.md

Instructions for AI coding agents (and a quick orientation for humans) working
in this repository. Read [INDEX.md](INDEX.md) for the full service directory
and [docs/microservices-catalog.md](docs/microservices-catalog.md) /
[docs/microservices-diagram-notes.md](docs/microservices-diagram-notes.md) for
the architecture those files summarise.

## What this project is

ConnectSphere: an event management system built for IS212 (Software Project
Management). It's a monorepo of Flask microservices plus a React frontend,
graded partly on process (sprints, backlog, tests, CI) and partly on working
software — see the project rubric before assuming "it works" is sufficient;
explainability and traceability (requirement → code → test) matter as much as
functionality.

The team runs **Scrum**, tracking the product backlog, sprint backlogs, and
all tickets in **Jira** — see [Process note — Scrum & Jira](#process-note--scrum--jira)
below for how this should shape commits.

## Repo layout

```
is212-g7t4/
├── frontend/                        # React SPA (Event Management System UI)
├── services/
│   ├── <name>-service/              # one Flask app per microservice
│   │   ├── app/                     # Flask app factory + routes/models
│   │   ├── tests/
│   │   ├── pyproject.toml
│   │   ├── uv.lock
│   │   ├── Dockerfile
│   │   ├── .env.example
│   │   └── README.md
│   └── ...
├── docs/                            # architecture notes, diagrams, rationale
├── docker-compose.yml                # local orchestration of all services
├── .github/workflows/                # per-service CI
├── AGENTS.md                        # this file
├── INDEX.md                         # service directory / map
└── README.md
```

See [INDEX.md](INDEX.md) for the concrete list of every service directory.

## Tech stack

- **Backend:** Python + Flask, one service per directory under `services/`.
- **Dependency management:** `uv`, one `pyproject.toml` + `uv.lock` per
  service. There is **no shared/common package** — each service is fully
  self-contained, even at the cost of some duplicated boilerplate (auth
  decorators, error handling, HTTP client helpers). Do not introduce a shared
  library without checking with the user first; this was a deliberate choice
  to keep services independently deployable and easy to reason about in
  isolation.
- **Data stores:**
  - Supabase Postgres — one Supabase project/schema per Postgres-backed
    atomic service (see INDEX.md for which services these are).
  - Supabase Auth — used by User Service for login/JWT issuance rather than
    hand-rolled auth. Other services verify the JWT Supabase issues; they
    don't call Supabase Auth themselves.
  - MongoDB (Atlas) — Forum/Communication Service only. This is the one
    deliberate polyglot-persistence choice in the system (variable-shape,
    append-only, no relational joins needed). Do not "fix" this to Postgres.
- **Messaging:** RabbitMQ — the *only* asynchronous path in the system, used
  exclusively for notification delivery. Every other cross-service call is
  synchronous REST/JSON.
- **Frontend:** React SPA in `frontend/`. There is no API gateway — the UI
  calls whichever composite or atomic service owns the capability it needs,
  directly.

## Service boundaries — do not violate these

These rules come directly from the SOA design in `docs/` and are load-bearing
for the "system design" and "code quality" rubric criteria:

- **Composites orchestrate; atomics never call another service, Forum, or the
  broker.** Only composite services are allowed to call other services. If a
  task seems to require an atomic to reach into another service, that logic
  belongs in a composite instead — flag it rather than adding the call to the
  atomic.
- **No API gateway.** The UI (or a composite) calls the owning service
  directly.
- **Notifications are the one async path.** Composites publish to RabbitMQ;
  Notification Service consumes and calls the Email/SMS Wrapper. Don't make
  notification delivery a synchronous, blocking part of any other flow.
- Each atomic owns exactly one entity/concern and its own schema. Don't let a
  composite reach past a service's HTTP API into another service's database.

## Working inside a single service

- Install deps: `cd services/<name>-service && uv sync`
- Run locally: `uv run flask --app app run --debug`
- Run tests: `uv run pytest`
- Run the whole system together: `docker compose up` from the repo root

## Testing expectations

- `pytest`, with `tests/` mirroring the structure of `app/`.
- The rubric expects **100% coverage unless not possible, with a stated
  reason** — run `uv run pytest --cov=app --cov-report=term-missing` before
  treating a service as done, and cover normal, boundary, conflict, and
  failure scenarios, not just the happy path (e.g. double-booking, over-
  capacity venues, insufficient equipment, rejected approvals).
- Tests should be traceable back to a user story / acceptance criterion —
  favor test names and docstrings that make that link obvious.

## CI

- One GitHub Actions workflow per service (or a single workflow with path
  filters on `services/<name>-service/**`), running lint + `pytest` for the
  service(s) that changed. Don't build every service on every PR.

## Secrets & environment

- Never commit real Supabase keys, Mongo URIs, or RabbitMQ credentials.
- Each service ships a `.env.example` listing required variables; real values
  go in a git-ignored `.env`.

## Known open architecture questions

These are flagged as unresolved in `docs/microservices-catalog.md` — don't
silently resolve them while implementing; surface the question instead:

- Whether **Event Workflow Service** is needed at all, since edits might
  already be handled by Venue Booking Service / Equipment Reservation
  Service's own edit paths.
- Whether **Forum Service** is actually needed inside **Coordinator
  Assignment Service** — most assignments won't have a reason worth logging.

If you (the agent) notice the two architecture docs disagree on something
(they previously did, on whether Venue Availabilities is a separate atomic
from Booking Conflict — now resolved: **they are separate**, per
[INDEX.md](INDEX.md)), stop and ask rather than picking one silently.

## Process note — Scrum & Jira

This is a graded Scrum project. The team runs Jira for the product backlog,
sprint backlogs, and all tickets — every piece of work should be traceable to
a Jira ticket. Prefer working in small increments that map to sprint backlog
items, and don't take on scope beyond what's asked without flagging it — the
team is accountable for explaining every decision in the Week 13 Q&A,
including what an AI agent contributed.

**Before creating any git commit, ask the user whether they want to include a
Jira ticket key in the commit message (e.g. `PROJ-123: fix venue conflict
check`), and if so, which key.** Don't guess the key or silently omit it —
Jira's commit integration relies on the key being present and correct, and
picking the wrong ticket misattributes the work.
