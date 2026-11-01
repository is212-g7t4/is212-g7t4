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

**Journeys in CI.** The `journeys` job in `.github/workflows/ci.yml` runs J1 (A and B), J3 (a, b, c), J5a, J5b and J7 on every pull request, push to `main` and nightly run. It uses the isolated runner (`npm run test:journeys:isolated`), which starts a throwaway database, local Supabase Auth, RabbitMQ, every service and Vite with no secrets and no shared Supabase, and retries a failed test once. J2, J4, J5c, J6b and J8 are not in CI; J5c is excluded because it waits about 8 minutes for a real hold to expire. Reproduce the CI run locally with Docker running:

```
npm run test:journeys:isolated -- --grep "J1|J3|J5a|J5b|J7"
```

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
| `docker-build` | Needs `changes`; runs only when its `docker` filter matches `services/**`, `docker-compose.yml` or the workflow | Copies example environment files and runs `docker compose build`; it does not start services. |
| `ci-passed` | `always()` join of all eight preceding jobs | Fails on any failure/cancellation, and requires unit, integration and dependency-audit results to be `success`. A conditional Docker skip is allowed; the gate does not explicitly require success from every other job. Intended single required branch-protection check. |

Frontend lint is inside its own job, not a prerequisite for backend tests. Real-stack browser journeys are not run by CI.

## Further documentation

- [INDEX.md](INDEX.md) — service directory, ownership and local commands.
- [AGENTS.md](AGENTS.md) — repository rules, service boundaries and testing conventions.
- [GLOSSARY.md](GLOSSARY.md) — shared domain terms.
- [Architecture diagrams](c4_diagram/) — C4 sources and exported diagrams; older artwork may retain historical design choices.
