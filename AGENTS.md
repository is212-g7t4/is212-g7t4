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
│   │   │   ├── unit/                # mocked; always run in CI
│   │   │   └── integration/         # needs a real system; opt-in, never in CI
│   │   ├── pyproject.toml           # also holds all pytest/coverage settings
│   │   ├── uv.lock
│   │   ├── .python-version          # 3.12, shared by local, CI and Docker
│   │   ├── Dockerfile
│   │   ├── .env.example
│   │   └── README.md
│   └── ...
├── docs/                            # architecture notes, diagrams, rationale
├── docker-compose.yml                # local orchestration of all services
├── .github/
│   ├── workflows/ci.yml             # the single CI workflow (see CI below)
│   └── .gitleaksignore              # known Gitleaks false positives
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
- Run tests: `uv run pytest` (no flags — see [Testing expectations](#testing-expectations))
- Run every service's tests: `npm run test:backend` from the repo root
- Run the whole system together: see below

## Running the whole stack locally

The root `package.json` runs both halves at once with `concurrently`:

```
npm run dev            # frontend (Vite) + backend (docker compose up)
npm run dev:frontend   # frontend only — Vite on :5174
npm run dev:backend    # backend only — docker compose up
```

Run these **from the repo root**. `npm run dev` inside
`frontend/event-management-ui/` is a different script — it's plain `vite`
and starts no backend at all.

### Every compose service needs its own `.env` first

This is the most common way local dev "mysteriously" breaks. Docker Compose
validates every `env_file` before it starts anything, so **one missing
`.env` aborts the entire backend** with:

```
env file .../services/<name>-service/.env not found
```

Under `npm run dev` the frontend still comes up, so the app looks like it's
running while every API call fails. Worse, some failures don't look like
outages: if User Service is down the role falls back to `Event Organiser`,
so role-gated nav items silently disappear and it reads as a permissions
bug. Check the backend pane, or `docker compose ps`, before debugging the
UI.

Fix — one `.env` per service listed in `docker-compose.yml`:

```
for s in user event coordinator-assignment registration venue; do
  cp .env "services/$s-service/.env"
done
```

Each service also ships a `.env.example` listing the variables it needs; the
root `.env` is a superset and works for all of them today. `.env` files are
git-ignored — never commit one.

Check it worked without building anything:

```
docker compose config >/dev/null && echo OK
```

Then `docker compose ps` should show every service `Up`, and
`curl localhost:<port>/health` should return `{"status":"ok"}` — see
INDEX.md for the port each service uses. Containers started with
`docker compose up -d` outlive `npm run dev`; stop them with
`docker compose down`.

### `FRONTEND_ORIGIN` must match the port Vite actually used

Every service does its own CORS check against a single `FRONTEND_ORIGIN`
(plus its `127.0.0.1` twin), defaulting to `http://localhost:5174`. That is
the port `vite.config.ts` pins, and it sets `strictPort: true`, so if
something else already holds 5174 Vite **exits** rather than drifting to
another port. A dev server that is running is therefore always on 5174.

If you do override the port, every service's `FRONTEND_ORIGIN` has to follow
it. The mismatch is easy to misread: the service returns `200` and the
payload is fine, but with no `Access-Control-Allow-Origin` header the
browser discards it, so the UI shows only a generic "unable to load" error
while `curl` against the same endpoint looks perfectly healthy.

```
# in every services/*/.env, then: docker compose up -d
FRONTEND_ORIGIN=http://localhost:<the port Vite printed>
```

To confirm it's CORS rather than the service, compare the two — only the
matching origin comes back with the header:

```
curl -si -H "Origin: http://localhost:5174" localhost:5006/venues | grep -i allow-origin
```

## Testing expectations

- **`uv run pytest` needs no flags.** Every pytest and coverage setting lives
  in the service's `pyproject.toml`, so a local run and the CI run behave
  identically. Don't add `--cov=app` or similar by hand; if a setting should
  change, change it in `pyproject.toml` so everyone gets it.
- **Two folders, one pyramid:**
  - `tests/unit/` — fast, fully mocked tests. CI always runs these.
  - `tests/integration/` — anything needing a real external system (a database,
    another service). Marked `@pytest.mark.integration` (or a module-level
    `pytestmark`), **deselected by default** and never run in CI, which has no
    secrets. Run them deliberately:
    `uv run pytest -m integration --no-cov`.
- Both folders, and `tests/` itself, are packages (`__init__.py`). Shared
  helpers go in `tests/unit/factories.py` and are imported as
  `from tests.unit.factories import ...`. **A test module must never import
  another test module** — that only worked by accident of pytest's default
  import mode and breaks the moment files move.
- **Unit tests are hermetic.** `pytest-socket` runs them with `--disable-socket`,
  so a test that forgets to mock an HTTP call fails with `SocketBlockedError`
  instead of reaching a real service. Caveat: this patches Python's `socket`
  module, so it catches `httpx`/`requests` but **not** `psycopg2`, which
  connects from C inside libpq. Keep mocking `psycopg2.connect` — nothing will
  catch it for you. Integration tests opt back in with
  `@pytest.mark.enable_socket`.
- **Coverage has a floor.** Each service sets `fail_under` in
  `[tool.coverage.report]` to the line+branch coverage it has reached today, so
  a PR cannot lower it. The floor is a ratchet, not a target: when you add tests
  that push a service higher, raise its `fail_under` in the same PR. A floor
  below 100 is a record of work still owed, not permission to stop.
- The rubric expects **100% coverage unless not possible, with a stated
  reason** — cover normal, boundary, conflict, and failure scenarios, not just
  the happy path (e.g. double-booking, over-capacity venues, insufficient
  equipment, rejected approvals).
- Tests should be traceable back to a user story / acceptance criterion —
  favor test names and docstrings that make that link obvious. File names are
  story-based (`test_submission.py`, `test_event_progress.py`) rather than
  mirroring `app/` modules, deliberately: that is what traces a test back to
  its Jira story. Don't rename them to match `app/`.
- Run the whole backend before pushing: `npm run test:backend` from the repo
  root.
- **Frontend** (`frontend/event-management-ui`): Vitest unit/component tests
  live next to the code in `src/` (`npm test`, `npm run test:coverage`).
  Playwright e2e smoke tests live in `e2e/` (`npm run test:e2e`) and mock every
  backend call with `page.route()`, so they need no running services, database
  or secrets. A request a test hasn't mocked fails the test. Add new mocks via
  `mock()` in `e2e/fixtures.ts`. First run needs `npx playwright install chromium`.

## CI

A single workflow, `.github/workflows/ci.yml`, runs on every pull request, on
pushes to `main`, nightly at 02:00 Singapore time, and on demand via the
**Run workflow** button. No secrets are needed.

**Every run runs every test.** Backend unit tests, the frontend suite and the
e2e suite are not path-filtered: a change in one service can break another
through a shared contract, so nothing is skipped on the grounds that a PR
"didn't touch it". A skipped job that reports green is worse than a slow one.
Only `docker-build` still consults the `changes` job.

| Job | What it checks |
|---|---|
| `discover-services` | Lists `services/*/pyproject.toml` to build the test matrix; fails if the list is empty |
| `unit-tests` (matrix, one per service) | `uv sync --locked`, then `uv run pytest` — flags come from `pyproject.toml`. Enforces the coverage floor, writes `junit.xml` + `coverage.xml` as artifacts, and adds a coverage table to the run summary |
| `dependency-audit` (matrix, one per service) | `pip-audit` on the locked deps, so a vulnerable dependency reports as an audit failure rather than a test failure |
| `frontend` | `npm audit --audit-level=high`, oxlint, Vitest with coverage, `tsc -b` + Vite build |
| `e2e` | Playwright smoke tests (mocked APIs); uploads the report if it fails |
| `docker-build` | `docker compose build` using each service's `.env.example` |
| `gitleaks` | Secret scan of the full git history (always runs) |
| `ci-passed` | Summary check — require this one in branch protection |

- **`ci-passed` is the only required check.** It fails if any job failed or was
  cancelled, *and* separately if `unit-tests` or `dependency-audit` is anything
  other than `success` — a skipped backend job must never count as a pass.
  Renaming or adding jobs therefore never touches the branch protection rules.
- **Adding a service:** CI discovers services automatically — any folder under
  `services/` with a `pyproject.toml` joins both matrices on its first PR, with
  no edit to `ci.yml`. It still needs a committed `uv.lock`, a `.python-version`
  (`3.12`, matching the Dockerfile), a `fail_under` in `[tool.coverage.report]`,
  and an entry in `docker-compose.yml`.
- **`uv sync --locked`** (not `--frozen`) fails when `uv.lock` no longer matches
  `pyproject.toml`, so a dependency added without re-locking is caught in CI
  rather than by the next person. Add dependencies with `uv add` and commit both
  files.
- **Gitleaks:** known false positives (the public Supabase key in the root
  `.env.example`) are listed in `.github/.gitleaksignore`. Run it locally with
  `gitleaks detect --gitleaks-ignore-path .github/.gitleaksignore`.
- **Not covered:** Python lint/format, frontend formatting, real-database or
  full-stack e2e, and the opt-in live Supabase test
  (`venue-availability-service/tests/integration/test_live_calendar.py`) — it
  needs Supabase credentials, which CI deliberately does not have.

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

If you (the agent) notice the two architecture docs disagree on something,
stop and ask rather than picking one silently. This happened once already:
whether Venue Availabilities is a separate atomic from Booking Conflict.
That's now resolved — **they're merged into one atomic, Venue Availability
Service** (`services/venue-availability-service/`), which owns both the
booking records and the overlap/conflict-checking algorithm. This matches
`docs/supabase-setup.md`'s schema (`public."VenueBooking"`) and how the
Equipment domain is already decomposed (`Equipment Availability` owns both
reservation records and its availability-checking algorithm). It also
avoids a structural problem with the old split: a stateless Booking Conflict
atomic would have needed to read bookings owned by Venue Availabilities,
which atomics can't do. `INDEX.md`/`docs/microservices-catalog.md` reflect
this; there is no separate Booking Conflict service/table.

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

**Branch naming:** every branch should be named after the Jira ticket it
implements, in the form `<SCRUM-KEY>-<kebab-case-summary>` — e.g. `SCRUM-84`
titled "Set Up Repository" becomes `SCRUM-84-set-up-repository`. Look the
ticket up (or ask the user for its key and summary) before branching rather
than guessing; don't invent a key or a summary. Branch off `main`, and open
the PR back into `main` when the work is ready — `main` is protected, so
direct pushes and force-pushes to it are rejected and all changes must land
via PR.
