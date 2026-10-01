# SCRUM-25 backend review checkpoint

**Backend only. Stop here for review before any frontend work.**
Branch `SCRUM-25-Venue-Availability-Calendar` was clean, fetched, then safely
fast-forwarded to `origin/main` at `d4caf6e`. No commit/push, schema migration,
live DB writes or frontend edits were performed for this implementation.

## File map and request flow

| File | Review focus |
|---|---|
| `app/__init__.py` | Calendar-only DEV gate, bounded/required query validation, CORS/preflight, sanitized 503 handling; existing write routes preserved |
| `app/calendar.py` | Separate read-only boundary parser: offset → Singapore naive; no changes to write parser |
| `app/models.py` | Parameterized half-open read; preserve malformed candidates, fail closed; `blocksSelection` and explicit `+08:00` output |
| `tests/conftest.py` | Shared isolated DB fixture moved out of the original test module |
| `tests/test_bookings.py` | Original write tests; existing GET test updated to the required range/header contract |
| `tests/test_calendar.py` | Route/time/status/role/error/CORS tests plus SQL bind assertions |
| `tests/test_calendar_sql.py` | Real in-memory SQL predicate execution, including NULL and venue isolation; not a mocked overlap algorithm |
| `tests/test_write_regressions.py` | Naive write times, Pending Review status, no DEV gate on writes, validation/failure regressions |
| `tests/test_live_calendar.py` | Explicit opt-in live GET through Flask; every DB connection set read-only, no personal rows printed |
| `.env.example`, `README.md`, `uv.lock` | Exact opt-in/header/run contract and reproducible service dependencies |
| Root `docker-compose.yml` | New existing-service entry on loopback host port 5008, root `.env`, disabled-by-default DEV mode |
| `docs/supabase-setup.md` | Corrected ownership/Event SQL/migration claims against checked source; documented live read findings and DEV-only auth scope |

Read flow: `GET` → DEV mode → user UUID/role headers → unique required
venue/range parameters → normalize timezone and enforce 42-day bound → query
only `VenueBooking` → validate all relevant rows → half-open selection →
serialize complete envelope. Any unsafe data or DB error returns 503 without a
partial calendar. OPTIONS is Flask's unauthenticated preflight; it reads no DB.

## Acceptance criteria → tests

| Criterion / guard | Evidence |
|---|---|
| AC1: selected venue and day/week/month visible range | `test_ac1_visible_ranges`, `test_ac1_invalid_range`, `test_ac1_half_open_overlap`, `test_ac1_offset_inputs_bind_singapore_naive`; SQL suite independently executes the predicate |
| AC3: approved blocks; pending visible/nonblocking; rejected/cancelled absent | `test_ac3_status_and_explicit_timezone`, `test_ac3_excluded_status`, `test_actual_sql_statuses` |
| AC3: never imply availability after malformed data | `test_ac3_malformed_rows_fail_closed`, `test_query_includes_invalid_rows_not_silently_lost`, `test_actual_sql_invalid_candidates_survive_filter`, DB error tests |
| AC4: internal-role simulation only, external denied | `test_ac4_disabled_by_default`, `test_ac4_reject_identity`, `test_ac4_internal_roles`, exact environment/role tests and live smoke |
| Browser contract | preflight, untrusted-origin, error-response CORS tests |
| Write compatibility | Original `test_bookings.py` write tests plus `test_write_regressions.py`; adjacent Venue Booking and Event service suites |
| AC2: rendering, interaction and selection prevention | **Deferred frontend work; not claimed complete** |

Incremental RED→GREEN slices were executed for default denial, role denial,
required/bounded inputs, offset inputs, status/output shape, exclusion/half-open
logic, invalid stored data, preflight, duplicate query parameters and non-finite
times. Existing-behavior characterization tests were added for regression
coverage. SQLite tests validate the actual SQL predicate but do not substitute
for PostgreSQL type/driver or concurrency testing.

## Exact commands and recorded results

From repository root:

```sh
cd services/venue-availability-service
uv sync --locked
uv run pytest --cov=app --cov-branch --cov-report=term-missing -q
uvx ruff check --isolated --select E4,E7,E9,F,I app tests
RUN_LIVE_CALENDAR_SMOKE=true uv run --env-file ../../.env pytest tests/test_live_calendar.py -q -s
CALENDAR_DEV_MODE=true uv run --env-file ../../.env flask --app app run --host 127.0.0.1 --port 5008
```

Recorded availability suite: **120 passed, 1 skipped**, **100% statement and
branch coverage**: 194 statements, 58 branches, none missed. The skip is the
explicitly opt-in live test. The listed isolated Ruff rules pass (the host has
broader ambient lint rules that warn about intentionally naive database times).

Live command: **1 passed**. PostgreSQL `transaction_read_only=on`; actual GET
returned 200 for all internal role strings, 403 for Event Organiser/Attendee,
401 for missing identity, and 503 with DEV mode disabled. Each internal GET
returned one booking for the sampled existing venue/window. Whole-table status
counts at verification: Approved 2, Pending 3, Rejected 1. Output checks passed
for `+08:00` and `blocksSelection`. Only status/count summaries were printed;
no IDs, credentials or personal booking fields were exposed. Separately checked
live column metadata confirmed UUID IDs and `timestamp without time zone`.
This is a read integration check, not an audit of all data or write concurrency.

Adjacent regression commands (run from repository root):

```sh
(cd services/venue-booking-service && uv run pytest --cov=app --cov-report=term-missing -q)
(cd services/event-service && uv run pytest --cov=app --cov-report=term-missing -q)
```

Results: Venue Booking **12 passed, 71% coverage**; Event **96 passed, 95%
coverage**. Their coverage gaps are pre-existing and outside this read feature.
No adjacent-service implementation changes were made.

Full `docker compose config --quiet` is blocked by pre-existing missing
service-local `.env` files (User/Event). The new availability entry was extracted
to a scratch Compose file and successfully validated with `docker compose
--project-directory <repo> -f <scratch-file> config --quiet`; port 5008 had no
listener at inspection. No container stack was started. Use the standalone
Flask command above without needing other services' `.env` files.

## Deliberate limits / review decisions

- Caller headers are spoofable. AC4 is **DEV behavior simulation**, not secure
  authentication/authorization. Disabled-by-default is not production auth.
- GET now requires headers and all range parameters: an intentional read-contract
  tightening. Existing POST/PATCH input, output and status handling are unchanged.
- 42 days supports a six-week month grid; no silent row truncation/pagination is
  used because that could conceal blocking bookings. Large-window/high-density
  performance and database index audits remain separate work.
- Singapore naive DB convention is explicit; no migration or data rewrite.
  Both legacy Pending and write-side Pending Review are supported.
- Unknown/null relevant status, ambiguous venue, or invalid relevant interval
  means unknown availability (503), not free time. The UI must honor this.
- No venue existence lookup: a valid unknown venue UUID can yield an empty list.
  Venue selection/catalogue remains Venue Service's concern.
- Operational `venueBlock`, venue search/filtering, frontend/AC2, real auth,
  write authorization, DB constraints and concurrent-write lock improvements
  remain deferred. Existing row locks are **not** a proven prevention of all
  concurrent double-bookings, especially when there are no existing rows.
