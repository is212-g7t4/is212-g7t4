# Integration Testing — Instructions for AI Agents

Read [AGENTS.md](../../AGENTS.md) first. This file extends its *Testing
expectations* section for integration tests only.

Equipment issues 6/7/8: PR115's Issue8 fix and regressions are integrated; the owner
PostgreSQL suite and Safety Check HTTP-boundary cases passed after integration.
Collection alone is not execution.

If this file and AGENTS.md disagree, **stop and ask** rather than picking one.
AGENTS.md still describes the old setup in places; see
[Transition](#transition-target-state-vs-today) and
[§12.3](#123-doc-disagreements-to-resolve-not-by-the-agent).

Before writing or reviewing any integration test, read the scope rules in
[§1.1–§1.2](#11-single-service-scope) and the naming and documentation
conventions in [§6.1](#61-naming-and-documenting-tests-traceability).

---

## 1. What an integration test is in this repo

**Real components working together, with only the external boundary controlled.**

- One service at a time (single-service scope, §1.1).
- The request enters through the **Flask test client** and runs through the
  **real** route → identity/role checks → business logic → data-access code →
  a **real, throwaway Postgres**.
- Only what lives **outside the service** is doubled: other ConnectSphere
  services' HTTP APIs, the RabbitMQ publisher, email/SMS.

*Why:* unit tests check each side of a boundary in isolation, and both sides
can pass while the boundary itself is broken. Integration tests exist to exercise the boundary.

| | Unit (`tests/unit/`) | Integration (`tests/integration/`) | Repo e2e (`e2e/` at the repo root) |
|---|---|---|---|
| Scope | One function/class | One service, route to DB | Maintained real-stack Playwright journeys |
| Database | Mocked (`psycopg2.connect` patched) | Real Postgres in a throwaway container | Shared development stack (manual journeys only) |
| Other services | Mocked | Stubbed/faked at the HTTP layer | Real stack; never run by service integration tests |
| Speed | Milliseconds | Seconds | Minutes |

Frontend unit/component tests remain in `frontend/event-management-ui/src/`.
The mocked frontend browser suite and unused lifecycle helper/tests were
archived and retired; that browser coverage has not been replaced. Existing
service-test docstrings naming former frontend smoke specs are historical
cross-references, not current runnable browser coverage; service tests were
preserved byte-for-byte during retirement.

### 1.1 Single-service scope

Each service's integration tests live in **that service's**
`tests/integration/` and exercise only that service's code.

**Allowed:**

- The service's own Flask app, routes, business logic and data-access code.
- A throwaway Postgres container loaded with the full migration chain,
  including tables that other services own (§4).
- Inserting parent rows into other services' tables with factories, so real
  foreign keys are satisfied (§4, §5). This writes to the shared schema; it
  does not run or call the other service.
- `test_infra_*` checks of the service's own wiring, e.g. that it connects to
  the test database (§6.1).

**Not allowed:**

- Starting, calling or importing another ConnectSphere service. Its HTTP API
  is stubbed with `respx` instead (§3, §7).
- A real RabbitMQ broker, `docker compose`, or starting services as
  subprocesses.
- The live Supabase project (that's the `live` tier, §2).

A test that needs two or more real services is an **end-to-end test**, not an
integration test, and doesn't belong in any service. Because it spans
services, it lives in the repo-root `e2e/` folder (§2). If a requirement seems
to need one, **stop and ask** (§11). The maintained Playwright journeys are in `e2e/journeys/`.

### 1.2 Atomic vs composite services

Both kinds get integration tests. What differs is where the boundary is.

| | Atomic (DB-backed) | Composite (no database) |
|---|---|---|
| Boundary under test | Route → business logic → SQL → Postgres | Route → orchestration → outbound HTTP to the atomics |
| Real | Flask app, logic, data-access code, Postgres container | Flask app, orchestration logic, the real HTTP client code in `app/clients.py` (`httpx`) |
| Doubled | Anything outside the service (rare for atomics) | Every atomic it calls, stubbed at the HTTP layer with `respx`; the RabbitMQ publisher, with a recording fake |
| Postgres container | Yes (§4) | No. Composites have no database |
| Assert on | The HTTP response **and** the persisted rows, read directly from the database | The HTTP response, **exactly** what was sent to each stub (method, URL, JSON body), that every stub was hit, and any recorded message |
| Can't prove | Anything owned by another service | Rules that run inside the atomics (e.g. the venue overlap rule), or that the real atomics accept the payload sent |

*Why composites still get integration tests:* the orchestration, the
request-building and the handling of downstream 4xx/5xx/timeouts all run in
the composite, and only a route-level test through the real `httpx` client
shows they work together. Only the network response is faked.

**Out of scope for this file:** cross-service tests (repo-root `e2e/`), tests
against the live Supabase project (the `live` tier below), contract tests, and
continuous delivery.

---

## 2. Tiers and where they run

| Tier | Folder | Marker | Database | Runs |
|---|---|---|---|---|
| Unit | `tests/unit/` | none | mocked | Every CI run; enforces the coverage floor |
| Integration | `tests/integration/` | `integration` | `postgres:17.6` via Testcontainers | Every CI run (separate job); needs Docker, no secrets |
| Live | `tests/live/` | `live` | The real Supabase project | Opt-in, locally only, **never in CI** |
| Repo e2e | `e2e/journeys/` | none | Real development stack | Manual, opt-in only (`npm run test:journeys`); never in CI |

```
uv run pytest                            # unit only (the default selection)
PYTHON_DOTENV_DISABLED=1 uv run pytest -m integration --no-cov    # integration tier (Docker must be running)
uv run pytest -m live --no-cov           # live tier, needs real credentials in .env
```

This file covers the integration tier only. Repo-root `e2e/journeys/` belongs
to no service and is not collected by service pytest runs. The five legacy
root Python harnesses, their CI jobs and the story-specific verification runners
were retired. Run maintained application tests directly as described above;
maintained journeys and shared helpers stay unchanged.

- Integration tests run with `--no-cov`. *Why:* the `fail_under` ratchet is
  defined against the unit run, so integration tests can't be used to paper
  over missing unit tests.
- Every integration test module sets
  `pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]`.
  *Why:* `pytest-socket` blocks sockets by default, but the Postgres container
  and the Docker API need real sockets.
- Test dependencies for this tier are `testcontainers[postgres]` and `respx`,
  added per service with `uv add --dev`. *Why:* every composite uses `httpx`,
  which `respx` intercepts.
- Import `PostgresContainer` from `testcontainers.community.postgres`. *Why:*
  the old `testcontainers.postgres` path is deprecated (since 4.15) and warns
  on every run.

### Transition (target state vs today)

The table above is the **target state**. Moving to it requires changes the
agent must **not** make unless the user explicitly asks:

Already done:

- Venue Availability's live smoke test is in `tests/live/test_calendar.py`
  under the `live` marker.
- The legacy SCRUM-46/171/173 root Python harnesses and dedicated
  SCRUM-173 integration workflow have been retired. Maintained journeys remain manual.
- Venue Availability registers the `live` marker and deselects it by default.
  Venue Booking's `integration` marker description now matches the others.
- `.github/workflows/ci.yml` retains the `integration-tests` matrix job (one per
  service with `tests/integration/`), required by `ci-passed`. Only the retired
  root-harness job and, subsequently, the approved mocked frontend browser job
  and their matching gate references were removed; all other jobs remain.

Still to do:

- **Register a `live` marker in any other service** that grows such a test,
  using the same pattern (`-m "not integration and not live"`).
- **Reconcile Equipment Request and Equipment Reservation with this guide.**
  Their current configs already register `integration`, deselect it by default,
  enforce the 100% unit coverage gate and use `tests/unit/`. They use local I/O
  guards rather than `pytest-socket`. Equipment Request has a fixture-owned
  PostgreSQL tier, but it loads selected baseline FK tables plus the owner outbox
  migration rather than the full unmodified migration chain; PR115's separate
  `safety_reset_owner` fixture does load the full chain. Equipment Reservation
  currently has unit HTTP doubles only. These documented exceptions were not
  changed by the test reorganisation.

If a task depends on any of these and they're not in place yet, **stop and
say so**. Don't work around it.

---

## 3. What stays real and what gets doubled

| Dependency | Treatment | Why |
|---|---|---|
| Flask app, routes, business logic | **Real**, built with `create_app(<test config>)` where the service accepts config | It's the thing under test. |
| Data-access code (raw `psycopg2`) | **Real** | The SQL is part of the boundary being tested. |
| Postgres | **Real engine, throwaway container** | SQLite can't run our Postgres SQL, and the live Supabase project needs secrets and shared state. |
| Caller identity and role checks | **Real** token verification (SCRUM-8), fed a token minted in the test with a test key: `bearer(user_id, role)` / `signed_in(client, ...)` from `tests/unit/factories.py`, with the autouse `trusted_test_signing_key` fixture in `tests/conftest.py` swapping only the JWKS key lookup for the test key. Composites: assert the caller's `Authorization` header reaches each stub. Never patch the check itself. | Role checks are acceptance criteria too, and patching them hides bugs. Only Supabase's own sign-in is out of reach (§12.2). |
| Other ConnectSphere services (HTTP) | **Stub at the HTTP layer with `respx`** | Single-service scope; the other service has its own tests. |
| RabbitMQ publisher | **Fake** that records published messages | Keeps the broker out of the test while still letting you assert on the message. |
| Email/SMS, any third-party API | **Fake** | Cost, rate limits, nondeterminism. |

- **What each kind of service exercises and asserts on is defined in §1.2.**
- **Composites freeze base URLs and `INTERNAL_SERVICE_TOKEN` at import** (all
  except Equipment Reservation). Stub against the URL actually held in
  `app.clients`, and change the token with `monkeypatch.setattr` on that
  module. *Why:* setting an env var after import has no effect on those
  globals.
- **An integration test proves only the ACs whose logic runs inside the
  service under test.** For example, the venue overlap rule lives in Venue
  Availability, so only Venue Availability's tests can prove it. A composite
  test with that atomic stubbed cannot. *Why:* asserting on a stub's canned
  answer proves the stub, not the rule.

---

## 4. The test database

- **Use `postgres:17.6`.** *Why:* it matches the Supabase project's major
  version, so dialect, constraints, quoted identifiers and `timestamptz`
  behave as they do in production.
- **Never SQLite, and never the live Supabase project, in this tier.** *Why:*
  SQLite runs a different dialect, and live Supabase breaks Isolated and
  Repeatable and needs secrets CI doesn't have.
- **Load the full migration chain unmodified:** every file in
  `database/supabase/migrations/*.sql`, in filename order, with autocommit on.
  *Why:* this is the single schema source; some files contain their own
  `BEGIN/COMMIT`, and autocommit lets them run as written.
- **Never filter, edit or hand-copy the schema**, even though it means loading
  tables other services own. *Why:* a transformed schema is one that doesn't
  exist in production.
- **When the service's tables have foreign keys to tables other services own
  (Event, Venue, User, …), insert those parent rows with factories in the
  arrange step.** *Why:* the foreign keys stay real, and it's the test, not
  the app, that writes the other service's tables.
- **Connect as the container's superuser (the table owner).** *Why:* every
  table has RLS enabled with no policies, so a non-owner role sees zero rows
  and every query returns empty.
- **Start one container per test session, and give every test fresh data:**
  truncate all `public` tables after each test with
  `TRUNCATE ... RESTART IDENTITY CASCADE`. *Why:* container startup takes
  seconds (Fast), and truncation keeps tests Isolated.
- **Before connecting or truncating, the fixtures must assert that the target
  host is `localhost` or `127.0.0.1`, and fail loudly otherwise.** *Why:*
  `load_dotenv()` runs at import and can put the live Supabase URL into the
  environment, and a `TRUNCATE ... CASCADE` there would wipe the team's data.
- **Point the app at the container through both channels:** pass
  `DATABASE_URL` in `create_app(config)`, and also
  `monkeypatch.setenv("DATABASE_URL", <container url>)`. *Why:* some code
  paths read `os.environ` directly rather than `app.config` (§12.2).
- **Disable Ryuk:** set `TESTCONTAINERS_RYUK_DISABLED=true` with
  `os.environ.setdefault` at the top of `conftest.py`, before testcontainers
  is imported, and start the container in a `with` block so it is always
  stopped. *Why:* on Docker Desktop, Ryuk (testcontainers' reaper container)
  intermittently fails at startup with "Port mapping ... port 8080 is not
  available", erroring the whole session; this was seen in about a third of
  back-to-back runs. Without Ryuk, only a hard kill of pytest can leave a
  container running; check with `docker ps --filter ancestor=postgres:17.6`.

---

## 5. Test data

- Build data with small helpers in `tests/integration/factories.py`, imported as
  `from tests.integration.factories import ...`. Builders **insert** rows and
  return their IDs, following the fixed-UUID-constants-plus-overrides shape of
  the existing `tests/unit/factories.py`. Never import one test module from
  another. *Why:* AGENTS.md rule, because cross-test imports break when files
  move.
- **Make the values that matter visible in the test and default the rest**, for
  example `make_venue(capacity=50)`. *Why:* the reader should see why the test
  passes or fails without opening a fixture.
- **Never rely on rows another test created.** There is no shared "seed
  world" beyond the empty schema. *Why:* that is the classic order-dependence
  flake.
- **Never use real personal data**: no real names, emails or phone numbers
  copied from Supabase. Use `@example.com`. *Why:* course rule and PDPA hygiene.
- **Dates:** use fixed, timezone-aware datetimes far in the future (e.g.
  2030). Where the server stamps or compares times with SQL `now()` or
  `datetime.now()`, assert relative to it (e.g. "within the last minute")
  rather than against a hard-coded time. *Why:* the clock can't be injected
  yet (§12.2); far-future dates keep "is this in the past?" logic stable, and
  relative assertions don't fail at midnight or month-end.

---

## 6. Workflow for writing integration tests

1. **Start from the Jira story and its acceptance criteria, not from the
   implementation.** If you don't have the story key and AC text, ask for them;
   never invent a key. *Why:* tests derived from the code only confirm what the
   code already does.
2. **State the boundary.** Name what is real and what is doubled for this
   service, using §3 and §12.1.
3. **Propose a scenario list and wait for the user's OK before writing.** Map
   each scenario to an AC and cover:
   - **normal:** the happy path
   - **boundary:** capacity exactly equal to attendance, a booking that starts
     exactly where another ends *including the buffer minutes*, quantity =
     stock
   - **conflict:** double-booking, over-capacity venue, insufficient or
     partially available equipment, invalid status transitions (e.g.
     approving an already-rejected request)
   - **failure:** missing or invalid fields → 4xx, wrong role → 403, not
     found → 404; for composites, a downstream atomic returning 4xx/5xx or
     timing out

   *Why:* the user has to be able to explain every test in the Week 13 Q&A.
4. **Write each test as Arrange-Act-Assert. Assert on both the HTTP response
   and the persisted state** by querying the database directly in the assert
   step (or, for composites, on what was sent to each stub and any recorded
   message). *Why:* a `200` with nothing committed is a bug the response alone
   won't show.
5. **Prove that each test can fail.** Temporarily break the key assertion
   (wrong expected value), watch it go red, then revert. *Why:* a test that
   can't fail proves nothing. The break must show as **failed**, not
   **error**: an error (a setup failure, or a syntax error from the edit)
   means the assertion never ran, so repeat that one until it fails properly.
6. **Run the tier** (`uv run pytest -m integration --no-cov`), run the
   unit tier too, then report (§10).

Name and document every file and test as §6.1 describes.

### 6.1 Naming and documenting tests (traceability)

The goal: someone with a Jira story can find its tests with `ls`, and the
`pytest -v` output reads as a checklist of its ACs. *Why:* traceability from
requirement to code to test is graded, and the team has to explain every test
in the Week 13 Q&A.

```
services/<name>-service/tests/integration/
├── __init__.py
├── conftest.py                  # fixtures only
├── factories.py                 # inserting builders only
├── test_scrum12_drafts.py       # one feature (story) per file
├── test_scrum11_submission.py
└── test_infra_db_connection.py  # not tied to a story
```

**File names**

- **`test_scrum<N>_<feature>.py`**, the Jira number of the story it tests
  followed by the feature in words (`test_scrum12_drafts.py`). *Why:* you can
  find a story's integration tests with `ls *scrum12*`. The full key and story
  also go in the module header.
- **Use the same `<feature>` wording as the unit-test file where there is one**
  (`tests/unit/test_scrum12_drafts.py` ↔ `tests/integration/test_scrum12_drafts.py`).
- **When a story touches several services, give each service's file the same
  name.** Each file still tests only its own service (§1.1).
- **One feature per file.** Don't add a different story's tests to an
  existing file. If it's unclear which feature a test belongs to, ask.
- **Tests not tied to a story** (database connectivity, migrations loading,
  health) go in `test_infra_<topic>.py`, e.g. `test_infra_db_connection.py`.
- **Only `test_*.py` files, `conftest.py` and `factories.py` belong in
  `tests/integration/`.** No standalone scripts (`verify_*.py`). *Why:* pytest
  never collects them, so they look like tests but never run.

**Test function names**

- **`test_ac<N>_<behaviour>`**, where the behaviour reads as the AC outcome,
  not the implementation. For example:
  `test_ac2_overlapping_booking_for_same_venue_is_rejected`. *Why:* `pytest -v`
  prints names, not docstrings, and `pytest -k ac2` runs one AC.
- **If a test covers more than one AC, prefix the AC it mainly proves** and
  name the others in its docstring.
- Tests in `test_infra_*` files have no AC prefix.

**Test docstrings**

One line: `"""<Scenario>: <why this case matters>."""`, where `<Scenario>` is
`Normal`, `Boundary`, `Conflict` or `Failure` (§6 step 3). Don't repeat the
story key; it's in the module header.

```python
def test_ac1_a_draft_without_a_name_is_refused_and_nothing_is_stored(client, db):
    """Failure: Event Name is the one field a draft needs."""
```

**Module docstring (the file header)**

Every story file starts with this header:

```python
"""SCRUM-12 Save Event Request as Draft: Event Service integration tests.

Story:      As an Event Organiser, I want to ..., so that ....
Real:       Flask app and routes, validation, app/models.py SQL, postgres:17.6
            with the full migration chain.
Doubled:    nothing (Event Service makes no outbound calls).
Not proven: authentication; identity is the organiserId the caller sends.

AC1  <AC text exactly as in Jira>
AC2  <AC text exactly as in Jira>
AC3  Not covered here: <reason, e.g. the rule runs in Venue Availability>.
"""
```

- **Copy the Jira key, title, story sentence and AC text word for word from
  Jira.** If you don't have them, ask (§6 step 1). Never paraphrase or invent
  them.
- **List every AC of the story, including the ones this file doesn't cover,**
  and give the reason for each uncovered one. *Why:* a gap stays visible in the
  code rather than only in a chat.
- **Fill in `Real` and `Doubled` from §1.2 and §3.** `Not proven` is the
  file-wide part of the §10 report.
- **For a `test_infra_*` file,** replace the first line with
  `Infra: <topic>: <Service> integration tests.` and the `Story` line with
  `Why: <what would break unnoticed without it>`. Name the Jira ticket if
  there is one. No AC lines.

**Layout inside the file:** group tests under `# AC1 ----` comment banners,
in AC order, with normal, then boundary, conflict and failure tests under each
banner.

---

## 7. Rules for test doubles

- **Never patch, stub or mock the thing under test.** For example,
  `@patch("app.models.create_booking")` in a test of booking creation is
  forbidden. *Why:* the test then checks the mock, not the code (the W9
  `EWallet.top_up` trap).
- **Patch where the name is looked up, not where it is defined.**
  `from x import f` inside `app/routes.py` means you patch `app.routes.f`.
  *Why:* patching the definition leaves the module's own reference pointing at
  the real function.
- **Stub to control inputs, then assert on state.** Use a mock (an interaction
  assertion) only when the interaction itself is the requirement, e.g.
  "exactly one notification is published with this payload." *Why:*
  over-mocking couples tests to implementation details.
- **Use `respx.mock(assert_all_mocked=True)`, and keep `assert_all_called` on,
  so any unmatched request fails and every stub must actually be hit.**
  *Why:* sockets are enabled in this tier, so an unstubbed call would
  otherwise reach a real service, and an unused stub means the test doesn't
  exercise the path you think it does.
- **Stubbed responses must mirror the real atomic's JSON shape**: field names,
  types and units. Copy the shape from the atomic's route or serialiser, and
  cite the file in a comment. *Why:* a stub that drifts from the real API
  creates the exact "mock-based integration illusion" this tier exists to
  prevent.
- **Never mock `psycopg2` or the database in this tier.** *Why:* a test that
  does that is a unit test in the wrong folder.

---

## 8. Flaky tests

**Forbidden "fixes":**

- `time.sleep()` to paper over timing
- Retry or rerun plugins, or "run it again until it's green"
- Weakening or deleting an assertion
- `skip` or `xfail` without the user's approval and a Jira key in the reason

**Required fixes:**

- Wait for a condition, not a duration
- Use fixed dates and relative time assertions (§5), and seed randomness
- Give every test fresh state
- Double the network boundary

If a test flakes, **report it** with how many runs you did, the
pass/fail pattern, and the suspected cause: timing, test
order and shared state, time and date, randomness, external services,
concurrency and resources. *Why:* once red starts to mean "just re-run it,"
real failures get ignored.

---

## 9. When a test fails

1. **Decide whether the test or the app is wrong by checking against the
   acceptance criterion, not against the code.**
2. **If the app is wrong, do not change application code.** Report:
   - the Jira story and AC
   - the failing test
   - expected vs actual
   - a minimal reproduction
   - the suspected location in the code

   Then ask how the user wants to proceed, e.g. fix it under its own ticket, or
   mark it `xfail(strict=True, reason="SCRUM-123: ...")` with their approval.
   *Why:* every change has to be explainable and traceable to a ticket.
   `strict=True` turns the test red again once the bug is fixed, so the marker
   can't go stale.
3. **Never change an expected value just to match the actual output.**
   *Why:* that turns a bug report into a test that enshrines the bug.
4. **When a test surfaces behaviour the AC doesn't specify**, e.g. a real
   foreign-key violation returning a misleading 503, assert only what the AC
   requires (the request is refused and nothing is stored), not the incidental
   status code, and report the behaviour as in step 2. *Why:* locking in the
   current response would enshrine it as correct.

---

## 10. Report what the tests actually prove

After running, give one line per test:

> **AC** → **what was real** → **what was doubled** → **what this does *not* prove**

Example: *"SCRUM-28 AC2 — real route and request-building logic; Event,
Venue and Venue Availability stubbed — doesn't prove the overlap rule (only
Venue Availability's tests do) or that the real atomics accept this payload."*

*Why:* to judge what doubled or generated tests actually prove.
This keeps the remaining gaps visible to the team.

Whatever applies to the whole file also goes in the module header's
`Not proven` line (§6.1), so it stays in the repo and isn't lost with the chat.

---

## 11. Stop and ask when

- A test seems to need an atomic to call another service, or a composite to
  read another service's database. That's a design question; see AGENTS.md's
  service boundaries.
- A test seems to need two or more real services (an end-to-end test for the
  repo-root `e2e/`, §1.1).
- You'd need to rename, move or edit tests in a service the user doesn't own.
  The team member who owns that service makes those changes. Report what
  should change instead.
- The architecture docs disagree with each other (see §12.3), or a test
  touches one of the open architecture questions listed in AGENTS.md.
- You'd need to change `pyproject.toml` markers or coverage settings,
  `fail_under`, any workflow file, `docker-compose.yml`, AGENTS.md or INDEX.md.
- You'd need to change application code to make it testable, e.g. to stop
  reading `os.environ` at import. Report it as a known gap instead.
- You'd need a new dependency beyond `testcontainers[postgres]` and `respx`.
  When adding any, use `uv add --dev` and commit both `pyproject.toml` and
  `uv.lock`.
- You're about to commit: follow AGENTS.md (ask for the Jira key; use
  `<SCRUM-KEY>-<summary>` branch names).

---

## 12. Repo-specific reference

### 12.1 Per-service reference (as of 22 Oct 2026; write-role gates added 30 Oct 2026 for SCRUM-10; re-check before relying on it)

All DB-backed atomics use raw `psycopg2` with a new connection per call, and
call `load_dotenv()` at import. Composites have no database and use `httpx`.

| Service | Kind | How the DB URL reaches the app | Outbound HTTP (where base URLs are set) | Identity today | RabbitMQ |
|---|---|---|---|---|---|
| user | atomic | `create_app(config)["DATABASE_URL"]` | none | Supabase token; `POST /auth/login` is public | none |
| event | atomic | `create_app(config)` | none | Supabase token (`?viewerRole=` asks for a wider view, judged on the token's role); `X-Internal-Token` (outbox, notification-context and workflow-only routes) checked against `app.config["INTERNAL_SERVICE_TOKEN"]`, failing closed with `503` when unset; write roles per route (Organiser, Lead, Coordinators; Safety Officer on `/safety-status` decisions) | none |
| venue | atomic | `create_app(config)` | none | Supabase token; Venue Staff role on `POST /venues`, `PUT /venues/<id>` and `PUT /venues/<id>/safety-info` (SCRUM-167, SCRUM-10) | none |
| venue-availability | atomic | `create_app(config)`; closures and outbox read `current_app.config` | none | Supabase token (requester/reviewer from it); write roles: Coordinators create/edit/cancel, Venue Staff approve/reject, Safety Officer plus `X-Internal-Token` (config) on `safety-reset`; outbox token read via `os.getenv` | owns the outbox table; doesn't publish |
| equipment | atomic | `create_app(config)` | none | Supabase token | none |
| equipment-request | atomic | `create_app(config)` | none | Supabase token; create = Coordinators, review = Technical Support; `safety-reset` needs the Safety Officer role plus `X-Internal-Token`; outbox routes use `X-Internal-Token` | none (service-specific guard/schema exceptions, see Transition) |
| registration | atomic | `create_app(config)` | none | Supabase token (the attendee); register and withdraw need the Attendee role (SCRUM-10) | none |
| safety-check-record | atomic | `create_app(config)` | none | Supabase token; Coordinators open, withdraw, restore and delete rounds, Safety Officer decides and reopens (SCRUM-10) | none |
| notification | atomic | **env only**: `create_app()` takes no config | none | Supabase token (the inbox owner) | consumer (pika) |
| attendee-registration | composite | n/a | Event, Registration, User (`app/clients.py`, frozen at import) | Supabase token, forwarded; register and withdraw need the Attendee role (SCRUM-10) | none |
| coordinator-assignment | composite | n/a | User, Event (`app/clients.py`, frozen at import) | Supabase token, forwarded; Lead role looked up via User Service | none |
| equipment-reservation | composite | n/a | Equipment Request, Event, Equipment, Safety Check Record (`app/clients.py`, **read per call**) | Supabase token, forwarded | none (service-specific guard/schema exceptions, see Transition) |
| event-workflow | composite | n/a | Event, User, Venue Availability, Venue, Equipment Request, Equipment (`app/clients.py`, frozen at import, plus `INTERNAL_SERVICE_TOKEN`) | Supabase token, forwarded; role via User Service; `PATCH /events/<id>/details` also needs a coordinator role on the token (SCRUM-10) | none |
| safety-check | composite | n/a | Event, Venue Availability, Equipment Request, Safety Check Record, User, Venue, Equipment (`app/clients.py`, frozen at import; uses a `ThreadPoolExecutor`) | Supabase token, forwarded; Safety Officer role via User Service for decisions; submit, re-check and venue-change routes need a coordinator role on the token (SCRUM-10) | none |
| venue-booking | composite | n/a | Event, Venue, Venue Availability, Safety Check Record (`app/clients.py`, mostly frozen at import) | Supabase token, forwarded; Venue Staff role for review (`GET /booking-requests/<id>`, `/review`, and since SCRUM-29 the legacy `/approve` and `/reject`) and for `PUT /venues/<id>`; create, edit and cancel need a coordinator role (SCRUM-10) | **the only publisher**: `app/dispatcher.py`, queue `notifications.v1`; in-process seam `dispatch_once(api, publish)` |

### 12.2 Known gaps

Each gap below limits what this tier can do today. Don't work around them by
changing app code; report them.

- **Supabase sign-in itself is out of reach.** Every service verifies the
  caller's Supabase token (SCRUM-8), and tests mint that token with a test key
  (§3). *Why it matters:* these tests prove verification and the role checks
  for a signed-in user, not that Supabase issues the token.
- **One shared `public` schema with cross-service foreign keys**, not one
  schema per atomic (e.g. `VenueBooking → Event/Venue/User`,
  `SafetyCheck → Event/User`). This is why §4 loads the full chain and inserts
  FK-parent rows via factories.
- **Some code reads `os.environ` instead of `app.config`:** Notification
  Service's store, consumer and diagnostics, and Venue Availability's outbox
  token. That's why §4 sets the env var as well as the config. Code that
  captured env values in module globals at import isn't reachable even that
  way.
- **The clock can't be injected.** SQL `now()` is used in Venue Availability
  and Safety Check Record; `datetime.now()` is used in Venue Availability's
  hold logic and Attendee Registration's validation. Time-dependent behaviour
  such as hold expiry can't be tested at a chosen time yet.
- **The only RabbitMQ publisher isn't behind a Flask route.** Venue Booking's
  dispatcher runs as its own process. Test it in-process through
  `dispatch_once(api, publish)` with a recording fake `publish` and the outbox
  endpoints stubbed.
- **Equipment Request and Equipment Reservation retain service-specific guard
  and schema exceptions** (see Transition).
- **Equipment Request's integration suite needs a pinned image.** Its
  `tests/integration/conftest.py` sets `PG_IMAGE` to
  `postgres@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3`
  and asserts it is already present locally; it never pulls it, so every test
  errors at setup on a machine without that exact digest. CI pulls it for you
  (`ci.yml` greps `tests/integration` for `postgres@sha256:` and runs
  `docker pull`); locally run
  `docker pull postgres@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3`
  first. It does not use `postgres:17.6` like the other suites.
- **The write-role gates in the composites** (Venue Booking, Safety Check,
  Attendee Registration, Event Workflow) are unit-tested only. Safety Check
  Record's gates are now proven in its integration tier.
- **A foreign-key violation in Safety Check Record reads as a database outage.**
  A round for an event that doesn't exist, or a flag naming an unknown booking
  or equipment request, is refused with the generic `503` "check the database
  connection" message rather than a `4xx`. Its tests assert only that the
  request is refused and nothing is stored (§9 step 4).

### 12.3 Doc disagreements to resolve (not by the agent)

- **INDEX.md duplicates and status errors:**
  - Attendee Registration and Registration still appear twice with conflicting
    status. Equipment Reservation's stale duplicate and the separate Equipment
    Availability row have been removed.
- **Equipment ownership (aligned):** Equipment Reservation supplies catalogue/event
  inputs and read-time availability; Equipment Request owns current allocation
  reads and final approval in one locked transaction. This is not proof of
  external input provenance or concurrent catalogue/event mutation safety.
- **Event Workflow scope:** equipment reads now name Equipment Request and
  Equipment consistently. The catalogue still describes planned Broker
  work rather than the complete implemented edit-validation callee list in INDEX.
- **Missing services:** Safety Check and Safety Check Record are absent from
  `docs/microservices-catalog.md`.
- **Safety Check Record callee:** INDEX lists it for Venue Booking and Equipment
  Reservation; the architecture catalogue is not yet an exhaustive service list.
- **AGENTS.md says "one Supabase project/schema per atomic"**; the migrations
  use one shared schema (§12.2).

### 12.4 Reference implementations

Validated suites to copy from when building a new one. Each was run and proven
able to fail (§6 step 5) before being listed here. Copy the fixture *patterns*
(§3–§5), not service-specific constants or schema details.

| Kind | Suite | Use it for |
|---|---|---|
| DB-backed atomic | `services/event-service/tests/integration/` | `conftest.py` (session container, migration loading, localhost guard, both-channel `DATABASE_URL`, per-test truncate, `db` helper for arrange/assert), `factories.py` (inserting builders incl. FK parents) |
| DB-backed atomic | `services/registration-service/tests/integration/` | Auditable status transitions, direct persisted-state assertions, and proving that withdrawn rows no longer consume confirmed capacity |
| Composite | `services/attendee-registration-service/tests/integration/` | `respx` HTTP-boundary stubs, exact downstream request assertions, deadline short-circuiting, and downstream failure handling |
| DB-backed atomic | `services/venue-service/tests/integration/` | Header-role gate on an atomic and FK-backed editor stamp: refused roles leave persisted values unchanged, a real `User` FK rejects an unknown editor, and a no-change save doesn't restamp |
| DB-backed atomic | `services/safety-check-record-service/tests/integration/` | Concurrency guards: two requests released together by a barrier (`at_once`), proving `FOR UPDATE` and a `UNIQUE` backstop let exactly one win; multi-statement transactions rolled back by a real FK failure |
| Composite | `services/safety-check-service/tests/integration/` | First suite for this composite: `ThreadPoolExecutor` fan-out under `respx` (the stubs are hit from worker threads) |

**Adding to this table:** once a new suite passes and every test has been
proven able to fail, add one row here: its kind, its path, and what it is the
best example of. Put any lesson that applies beyond that service into the
general sections above, not here.

#### Still to build

No publisher suite exists yet, so a recording publisher has no reference
implementation. Other recommended examples:

- **Atomic: Venue Availability, `POST /venue-bookings`.** It holds the SQL
  overlap-plus-buffer conflict check, which is exactly what unit tests can't
  prove.
  - SCRUM-30 AC2: an overlapping request for a venue with an Approved
    booking → `409`, `code == "VENUE_UNAVAILABLE"`, and still exactly one
    `VenueBooking` row for that venue.
  - SCRUM-28 AC6 (boundary): a booking that starts exactly where the existing
    one ends, including buffer minutes, is accepted; one minute earlier
    conflicts. If the buffer semantics are ambiguous in the code, stop and ask.
- **Composite: Venue Booking, `POST /booking-requests`.** It calls Event,
  Venue and Venue Availability; copy the Venue Availability stub's shape from
  the atomic example's route.
  - SCRUM-28 AC2 / SCRUM-30 AC1: a valid request → `201`, the Venue
    Availability stub called once with exactly the expected JSON body, and
    every stub hit.
- **Publisher: Venue Booking `dispatch_once`.**
  - SCRUM-173 AC1 + AC2: one message recorded, addressed to the assigned
    coordinator, with the event name, venue, closure dates, rejection reason
    and link.
  - SCRUM-173 AC3: the publisher fails on the first attempt, dispatch runs
    again, and exactly one message ends up recorded (no duplicate).
