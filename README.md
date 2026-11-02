# ConnectSphere — IS212 G7T4

An event management system developed using Scrum: event requests, venue/equipment arrangements, safety reviews and in-app notifications.

**Stack:** React/TypeScript, Flask microservices, Supabase PostgreSQL/Auth and RabbitMQ.

## Setup

Install **Node.js 22**, **Docker Desktop with Compose**, and **uv/Python 3.12** if running backend tests on the host.

From the repository root:

```bash
npm ci
npm --prefix frontend/event-management-ui ci
```

These install JavaScript dependencies only. Docker builds install backend dependencies inside images; host execution/tests need per-service `uv sync`.

Create missing `.env` files from the corresponding `.env.example` at the root, frontend and services required by `docker-compose.yml`; preserve existing files. Configure the team's approved Supabase settings, service database connections and shared internal-service token. Keep secrets out of Git and out of frontend `VITE_*` settings. Database schemas and accounts must already be prepared (instructions: `docs/supabase-setup.md`); Compose does not apply migrations.

## Run and stop

Start Docker Desktop, then run from the repository root:

```bash
docker compose up --build -d
npm run dev:frontend
```

Open **http://localhost:5174**. These are source-checked local development instructions, not a verified fresh-machine run or production deployment. Optional host service execution is described in INDEX.md; do not bind the same port as a Docker container.

Alternatively, after setup, `npm run dev` runs the frontend and Compose together; `npm run dev:backend` starts only Compose. Detached containers still need explicit shutdown.

Stop the frontend with **Ctrl+C**, then, from the repository root:

```bash
docker compose down
```

Do not add `-v` (it deletes named data volumes). Use `docker compose ps` to inspect backend status.

## Login accounts

| Email | Role |
|---|---|
| wei.chen@connectsphere.example | Technical Support |
| siti.aminah@connectsphere.example | Venue Staff |
| attendee@example.com | Attendee |
| priya.nair@connectsphere.example | Event Coordinator |
| nurul.huda@connectsphere.example | Safety Officer |
| michaellee@connect.com | Event Organiser |
| marcus.lim@connectsphere.example | Event Coordinator |
| jon.tan@example.com | Attendee |
| danielkoh@connect.com | Event Organiser |
| alice.tan@connectsphere.example | Event Coordinator Lead |

## Tests

### Backend

Install **uv and Python 3.12** for host tests. Docker builds install Python dependencies inside containers, not on your machine; run `uv sync` in each service you test.

| Tier | What runs | Runtime needed |
|---|---|---|
| Unit (default) | Service behaviour with database/HTTP dependencies doubled; service-specific coverage gates apply | No application containers, shared database or broker |
| Integration (opt-in) | One service's real components; DB-backed services use disposable PostgreSQL, composites stub downstream HTTP | Docker Desktop for database suites; not the full Compose stack |

**1. One service's unit tests** — start from the repository root:

```bash
cd services/equipment-request-service
uv sync --locked --python 3.12
PYTHON_DOTENV_DISABLED=1 uv run --no-env-file --locked --python 3.12 pytest
```

Substitute another service directory as needed. Its `pyproject.toml` selects the default unit tier and coverage gate.

**2. All backend default unit suites** — first repeat `uv sync --locked --python 3.12` inside **each** `services/*/` directory, then run from the repository root:

```bash
PYTHON_DOTENV_DISABLED=1 npm run test:backend
```

The existing root script enters each service and runs `uv run pytest`, stopping on the first failure. It uses each service's prepared environment/Python selection; it does not pass `--python 3.12`, `--locked` or `--no-env-file`. Prepare the Python 3.12 environments first; there is no aggregate dependency-install script.

**3. Integration tests** — choose a service with `tests/integration/`, sync its dependencies as above, and read `docs/testing/integration-testing.md` plus that service's `tests/README.md` where present. For **Equipment Request**, start Docker Desktop and, from the repository root:

```bash
cd services/equipment-request-service
docker pull postgres@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3
mkdir -p "$HOME/.cache/connectsphere-test-tmp"
TMPDIR="$HOME/.cache/connectsphere-test-tmp" PYTHON_DOTENV_DISABLED=1 \
  uv run --no-env-file --locked --python 3.12 pytest -m integration --no-cov tests/integration
```

The owner fixture requires that exact image locally (`--pull=never`) and a writable `TMPDIR` for evidence. Keep pre-existing containers stable during the run: teardown verifies they are unchanged, so unrelated restarts can fail it. Other database suites use `postgres:17.6`; composite suites need no database container. Fixtures own disposable databases and enforce connection/cleanup guards; the environment flags alone do **not** protect shared Supabase. Do not point tests at it or start application workers.

| Option | Meaning |
|---|---|
| `PYTHON_DOTENV_DISABLED=1` | Stops application `python-dotenv` from loading `.env` files |
| `--no-env-file` | Stops **uv** from loading an environment file; separate from application dotenv |
| `--locked` / `--python 3.12` | Requires an up-to-date lockfile without rewriting it / selects Python 3.12 |
| `pytest -m integration` | Selects the opt-in integration marker instead of the default unit selection |
| `--no-cov` | Disables coverage measurement and its gate, **not test assertions** |

### Frontend

From the repository root:

```bash
cd frontend/event-management-ui
npm test
npm run test:coverage
npm run lint
npm run build
```

The mocked frontend browser suite and unused lifecycle-helper tests were retired, not replaced. Unit/component tests do not replace that browser coverage. Real-stack journeys (`e2e/journeys/`) are opt-in locally: read `e2e/journeys/TRACEABILITY.md` before `npm run test:journeys` from the root; against your own stack they write shared test data, and they do not yet replace all retired coverage.

### E2E

**Journeys in CI.** The `journeys` job in `.github/workflows/ci.yml` runs J1 (A and B), J3 (a, b, c), J5a, J5b and J7 after `unit-tests`, `integration-tests` and `frontend` all succeed, on every workflow trigger including manual runs. If any prerequisite fails, is cancelled or is skipped, journeys are skipped and `ci-passed` fails. These are real-stack Chromium journeys, not mocked browser tests. The isolated runner (`e2e/isolated/run.mjs`) provisions a throwaway PostgreSQL database from migrations/seed data, local Supabase Auth with ES256/JWKS and a role hook, RabbitMQ, services/workers and Vite. It uses generated credentials and dynamic loopback ports, not development `.env` files or shared Supabase. J2, J4, J5c, J6a/b and J8 are outside CI's grep selection; J5c waits about 8 minutes for a real hold to expire. With Docker running, root/frontend dependencies installed and Playwright Chromium installed (`npx playwright install --with-deps chromium`), reproduce CI from the repository root:

```bash
npm run test:journeys:isolated -- --grep "J1|J3|J5a|J5b|J7" --retries=1
```

Playwright uses one worker; CI overrides the default zero retries with one retry per failed test. The runner tears down its own containers/volumes on exit or failure; interrupted cleanup may require the printed recovery command. Reports include HTML, traces, failure screenshots and retained failure videos under `e2e/journeys/report/` and `e2e/journeys/test-results/` (run-specific subfolders). CI attempts to upload these even after failure; missing reports are ignored. See `e2e/journeys/TRACEABILITY.md` for recovery and coverage limits.

### Test locations

```text
services/<service>/tests/
├── unit/                       # Service behaviour with test doubles
└── integration/                # Service integration, where present

frontend/event-management-ui/
└── src/                        # Unit/component tests beside application code

e2e/
├── journeys/                   # Manual real-stack browser journeys
├── helpers/                    # Shared journey setup/cleanup
├── conftest.py                 # Retained Python setup
├── factories.py
└── signing.py

scripts/
├── test_compose_configuration.py
└── test_support/               # Shared test helpers
```

## CI

`.github/workflows/ci.yml` runs on pull requests, pushes to `main`, nightly at 02:00 Singapore time and on demand. It checks changes; it does not deploy. Jobs form a dependency graph, **not** a lint → unit → integration pipeline:

| Jobs | Inputs/dependencies | Checks and output |
|---|---|---|
| `changes`, `discover-services` | Start independently on checkout | Classify changed paths; discover unit/audit services from `services/*/pyproject.toml` and integration services from `tests/integration/`. Empty matrices fail discovery. |
| `unit-tests`, `integration-tests`, `dependency-audit` | Each needs only `discover-services`; their service matrices can run in parallel | Locked dependencies; unit tests with coverage floors/reports; integration tests with disposable PostgreSQL images and JUnit reports; `pip-audit` of locked dependencies. All maintained backend CI tiers run regardless of changed paths. |
| `frontend`, `gitleaks` | Independent of discovery and backend tests; not path-filtered | Frontend runs **in order**: `npm ci` → `npm audit --audit-level=high` → `npm run lint` (oxlint) → `npm run test:coverage` (Vitest) → `npm run build` (`tsc -b` + Vite). Gitleaks separately scans full Git history. |
| `journeys` | Needs `unit-tests`, `integration-tests` and `frontend`; starts only after all three succeed; not path-filtered; 60-minute timeout | Installs root/frontend dependencies and Chromium, then runs `npm run test:journeys:isolated -- --grep "J1\|J3\|J5a\|J5b\|J7" --retries=1` on the disposable real stack described above. |
| `docker-build` | Needs `changes`; runs only when its `docker` filter matches `services/**`, `docker-compose.yml` or the workflow | Copies example environment files and runs `docker compose build`; it does not start services. |
| `ci-passed` | `always()` join of all preceding jobs, including `journeys` | Fails on any failure/cancellation, and explicitly requires unit, integration, dependency-audit **and journeys** results to be `success` (skips fail these checks). A conditional Docker skip is allowed; the gate does not explicitly require success from every other job. Intended single required branch-protection check; actual protection settings are not established by this file. |

Backend unit and integration jobs and the frontend job can run in parallel (backend jobs wait only for service discovery); journeys wait for all three to succeed and are skipped otherwise. Frontend lint is inside its own job, so it gates journeys through the frontend result but does not gate backend tests. Unit (`test-reports-<service>`), integration (`integration-reports-<service>`) and browser (`journey-reports`) artifacts are uploaded with `always()`, retained for 14 days and ignored if absent. Unit reports include JUnit and coverage XML; integration reports include JUnit. Journey failures also print service logs before teardown in CI.

This describes the configured workflow, not a guarantee that the latest run passed. CI needs no team Supabase credentials; the isolated runner generates its own temporary credentials. Python lint/formatting, frontend formatting, journeys outside the selected subset and opt-in live Supabase tests are not included.

## Further documentation

- [INDEX.md](INDEX.md) — service directory, ownership and local commands.
- [AGENTS.md](AGENTS.md) — repository rules, service boundaries and testing conventions.
- [Architecture diagrams](c4_diagram/) — C4 sources and exported diagrams; older artwork may retain historical design choices.
