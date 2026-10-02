# is212-g7t4
Development of an event Management System using Scrum Agile methodology

## Setup

Install root dependencies (used to run frontend + backend together):

```
npm install
```

The frontend has its own dependencies, installed separately:

```
npm --prefix frontend/event-management-ui install
```

Backend services run in Docker, so no separate install step is needed for
them — see [AGENTS.md](AGENTS.md) if you're adding a new service.

## Running the app

Run the frontend dev server and backend services (via Docker Compose)
together:

```
npm run dev
```

Or run either side on its own:

```
npm run dev:frontend   # frontend only, via Vite
npm run dev:backend    # backend only, via docker compose up
```

See [INDEX.md](INDEX.md) for the current status of each backend service.

## Testing

```
cd services/<name>-service && uv sync && uv run pytest --cov=app   # one backend service

cd frontend/event-management-ui
npm ci
npm test                  # Vitest unit/component tests
npx playwright install chromium   # first time only
npm run test:e2e          # Playwright smoke tests (backend APIs are mocked)
```

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on every pull request and on
pushes to `main`: backend `pytest` per service, frontend lint/tests/build,
Playwright e2e, dependency audits (`npm audit`, `pip-audit`), a Docker build
check and a Gitleaks secret scan. Only the parts a PR touches are run. See the
CI section of [AGENTS.md](AGENTS.md) for details, including what to change when
adding a service.
