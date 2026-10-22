# Integration Testing — Instructions for AI Agents

Read [AGENTS.md](../../AGENTS.md) first. This file extends its *Testing
expectations* section for integration tests only. 

If this file and AGENTS.md disagree, **stop and ask** rather than picking one.
AGENTS.md still describes the old setup in places; see
[Transition](#transition-target-state-vs-today) and
[§12.3](#123-doc-disagreements-to-resolve-not-by-the-agent).

---

## 1. What an integration test is in this repo

**Real components working together, with only the external boundary controlled.**

- One service at a time (single-service scope).
- The request enters through the **Flask test client** and runs through the
  **real** route → identity/role checks → business logic → data-access code →
  a **real, throwaway Postgres**.
- Only what lives **outside the service** is doubled: other ConnectSphere
  services' HTTP APIs, the RabbitMQ publisher, email/SMS.

*Why:* unit tests check each side of a boundary in isolation, and both sides
can pass while the boundary itself is broken. Integration tests exist to exercise the boundary.

| | Unit (`tests/unit/`) | Integration (`tests/integration/`) | E2E (`frontend/.../e2e/`) |
|---|---|---|---|
| Scope | One function/class | One service, route to DB | UI journey in a browser |
| Database | Mocked (`psycopg2.connect` patched) | Real Postgres in a throwaway container | Mocked via `page.route()` |
| Other services | Mocked | Stubbed/faked at the HTTP layer | Mocked |
| Speed | Milliseconds | Seconds | Seconds to minutes |

**Out of scope for this file:** cross-service tests via `docker compose`, tests
against the live Supabase project (the `live` tier below), contract tests, and
continuous delivery.

---

## 2. Tiers and where they run

| Tier | Folder | Marker | Database | Runs |
|---|---|---|---|---|
| Unit | `tests/unit/` | none | mocked | Every CI run; enforces the coverage floor |
| Integration | `tests/integration/` | `integration` | `postgres:17.6` via Testcontainers | Every CI run (separate job); needs Docker, no secrets |
| Live | `tests/live/` | `live` | The real Supabase project | Opt-in, locally only, **never in CI** |

```
uv run pytest                            # unit only (the default selection)
uv run pytest -m integration --no-cov    # integration tier (Docker must be running)
uv run pytest -m live --no-cov           # live tier, needs real credentials in .env
```

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

- **Move existing live-Supabase tests into `tests/live/`** under a new `live`
  marker. For example,
  `venue-availability-service/tests/integration/test_live_calendar.py` hits
  live Supabase.
- **Give the SCRUM-173 harness its own marker.** Its files in
  `venue-booking-service/tests/integration/` (`test_scrum173_real.py`,
  `verify_scrum173_backend.py`) drive Docker, a real RabbitMQ and subprocesses,
  and take minutes. It currently shares the `integration` marker and has its
  own workflow, `.github/workflows/scrum173-integration.yml`.
- **Register both markers and keep them deselected by default** in each
  service's `pyproject.toml`. Make the marker descriptions consistent: Venue
  Availability's says "never run in CI", Venue Booking's says "opt-in
  dedicated isolated job".
- **Make Equipment Request and Equipment Reservation tier-ready.** They need
  `pytest-socket`, a registered `integration` marker, `-m "not integration"`,
  `fail_under`, and their tests moved under `tests/unit/`.
- **Add an `integration-tests` matrix job to `.github/workflows/ci.yml`** and
  wire it into `ci-passed`.
- **Update AGENTS.md's *Testing expectations* and *CI* sections** to match.

If a task depends on any of these and they're not in place yet, **stop and
say so**. Don't work around it.

---

## 3. What stays real and what gets doubled

| Dependency | Treatment | Why |
|---|---|---|
| Flask app, routes, business logic | **Real**, built with `create_app(<test config>)` where the service accepts config | It's the thing under test. |
| Data-access code (raw `psycopg2`) | **Real** | The SQL is part of the boundary being tested. |
| Postgres | **Real engine, throwaway container** | SQLite can't run our Postgres SQL, and the live Supabase project needs secrets and shared state. |
| Caller identity and role checks | **Interim (now):** the service's real `X-Dev-*` header checks, with its dev-mode flag on, via a `dev_identity(user_id, role)` helper. **Target (after the auth/RBAC work lands):** real JWT verification, fed a token minted in the test with a test key. Where a service has no `X-Dev-*` headers and takes identity from body or query IDs (see the *Identity today* column in §12.1), send those IDs exactly as a real caller would; no helper is needed. Never patch the check itself. | Role checks are acceptance criteria too, and patching them hides bugs. No service verifies a JWT yet (§12.2). |
| Other ConnectSphere services (HTTP) | **Stub at the HTTP layer with `respx`** | Single-service scope; the other service has its own tests. |
| RabbitMQ publisher | **Fake** that records published messages | Keeps the broker out of the test while still letting you assert on the message. |
| Email/SMS, any third-party API | **Fake** | Cost, rate limits, nondeterminism. |

- **Atomic services:** the database is the boundary. Exercise route → SQL →
  Postgres and assert on what was persisted.
- **Composite services:** the atomics' HTTP APIs are the boundary, and no
  composite has a database. Exercise route → orchestration → outbound HTTP,
  with the atomics stubbed. Assert on the response, on exactly what was sent
  to each atomic, and on any published message.
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
6. **Run the tier** (`uv run pytest -m integration --no-cov`, scoped to your
   new files while the SCRUM-173 harness still shares the marker), run the
   unit tier too, then report (§10).

**Naming:** use story-based file names (`tests/integration/test_<story>.py`),
mirroring the unit-test convention, with test names that read as the AC, e.g.
`test_overlapping_booking_for_same_venue_is_rejected`. Each test's docstring
gives the Jira key and the AC it covers. *Why:* this gives traceability from
requirement to test, which the rubric grades.

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

---

## 11. Stop and ask when

- A test seems to need an atomic to call another service, or a composite to
  read another service's database. That's a design question; see AGENTS.md's
  service boundaries.
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

### 12.1 Per-service reference (as of 22 Oct 2026; re-check before relying on it)

All DB-backed atomics use raw `psycopg2` with a new connection per call, and
call `load_dotenv()` at import. Composites have no database and use `httpx`.

| Service | Kind | How the DB URL reaches the app | Outbound HTTP (where base URLs are set) | Identity today | RabbitMQ |
|---|---|---|---|---|---|
| user | atomic | `create_app(config)["DATABASE_URL"]` | none | `?role=` filter only; no check | none |
| event | atomic | `create_app(config)` | none | body/query `coordinatorId`, `?viewerRole=`; `X-Internal-Token` checked against `app.config["INTERNAL_SERVICE_TOKEN"]` | none |
| venue | atomic | `create_app(config)` | none | no identity check on routes | none |
| venue-availability | atomic | `create_app(config)`; closures and outbox read `current_app.config` | none | `X-Dev-*` gated by `CALENDAR_DEV_MODE` / `VENUE_CLOSURE_DEV_MODE`; body `requestedBy`; `X-Internal-Service-Token` (config); outbox token read via `os.getenv` | owns the outbox table; doesn't publish |
| equipment | atomic | `create_app(config)` | none | `X-Dev-User-Id` / `X-Dev-Role` | none |
| equipment-request | atomic | `create_app(config)` | none | `X-Dev-*` headers | none (not tier-ready, see Transition) |
| registration | atomic | `create_app(config)` | none | body `attendeeId` | none |
| safety-check-record | atomic | `create_app(config)` | none | body IDs | none |
| notification | atomic | **env only**: `create_app()` takes no config | none | `NOTIFICATION_DEV_MODE` gate | consumer (pika) |
| attendee-registration | composite | n/a | Event, Registration, User (`app/clients.py`, frozen at import) | body `attendeeId` | none |
| coordinator-assignment | composite | n/a | User, Event (`app/clients.py`, frozen at import) | role looked up via User Service | none |
| equipment-reservation | composite | n/a | Equipment Request, Event, Equipment, Safety Check Record (`app/clients.py`, **read per call**) | `X-Dev-*` headers | none (not tier-ready, see Transition) |
| event-workflow | composite | n/a | Event, User, Venue Availability, Venue, Equipment Request, Equipment (`app/clients.py`, frozen at import, plus `INTERNAL_SERVICE_TOKEN`) | role via User Service | none |
| safety-check | composite | n/a | Event, Venue Availability, Equipment Request, Safety Check Record, User, Venue, Equipment (`app/clients.py`, frozen at import; uses a `ThreadPoolExecutor`) | body/query IDs; role via User Service | none |
| venue-booking | composite | n/a | Event, Venue, Venue Availability, Safety Check Record (`app/clients.py`, mostly frozen at import) | `X-Dev-*` for Venue Staff review | **the only publisher**: `app/dispatcher.py`, queue `notifications.v1`; in-process seam `dispatch_once(api, publish)` |

### 12.2 Known gaps

Each gap below limits what this tier can do today. Don't work around them by
changing app code; report them.

- **No service verifies caller identity.** Roles and user IDs are whatever the
  caller sends (`X-Dev-*` headers, query params, body IDs). Use the interim
  `dev_identity` approach (§3) until the auth/RBAC work lands. *Why it
  matters:* these tests prove the role checks *given* an asserted identity,
  not authentication.
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
- **Equipment Request and Equipment Reservation aren't tier-ready** (see
  Transition).

### 12.3 Doc disagreements to resolve (not by the agent)

- **INDEX.md duplicates and status errors:**
  - Equipment Reservation, Attendee Registration and Registration each appear
    twice, with conflicting callees or status.
  - Notification is marked "planned", but working code exists.
- **Equipment Availability:** INDEX lists it as a planned atomic, while
  AGENTS.md and the catalog put availability inside the Equipment Reservation
  composite.
- **Event Workflow callees:** the catalog says Event, Venue Availabilities,
  Equipment Availabilities, Forum, Broker; INDEX and the code say Event, User,
  Venue Availability, Venue, Equipment Request, Equipment.
- **Missing services:** Safety Check and Safety Check Record are absent from
  `docs/microservices-catalog.md`.
- **Undocumented callees:** Venue Booking and Equipment Reservation call Safety
  Check Record Service, which neither INDEX row lists.
- **AGENTS.md says "one Supabase project/schema per atomic"**; the migrations
  use one shared schema (§12.2).
- **AGENTS.md says there is a single CI workflow**; `scrum173-integration.yml`
  also exists.

### 12.4 Reference implementations

Validated suites to copy from when building a new one. Each was run and proven
able to fail (§6 step 5) before being listed here. Copy the fixture *patterns*
(§3–§5), not service-specific constants or schema details.

| Kind | Suite | Use it for |
|---|---|---|
| DB-backed atomic | `services/event-service/tests/integration/` | `conftest.py` (session container, migration loading, localhost guard, both-channel `DATABASE_URL`, per-test truncate, `db` helper for arrange/assert), `factories.py` (inserting builders incl. FK parents) |

**Adding to this table:** once a new suite passes and every test has been
proven able to fail, add one row here: its kind, its path, and what it is the
best example of. Put any lesson that applies beyond that service into the
general sections above, not here.

#### Still to build

No composite or publisher suite exists yet, so the `respx` stubs and the
recording publisher have no reference implementation. Recommended first
examples:

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