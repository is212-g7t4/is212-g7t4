# SCRUM-170 — temporary venue closure backend review

> Historical backend-stage review: the boundaries and remaining gates below describe that stage only. Frontend implementation, authorized shared-database migration, live functional verification and subsequent review fixes are documented in [scrum-170-startup.md](scrum-170-startup.md).

## Review boundary

Backend recording and staff-only read-back are implemented. **Stop here for review; no frontend or operational enforcement is included.**

- A Venue Staff caller can record a closure for any existing venue, regardless of catalogue status. Ongoing and future closures are accepted; overlapping closures are deliberately accepted.
- No booking, hold, event, or venue status is checked or changed. No notifications, search/availability/calendar integration, rejection, editing/deletion, recurrence, automatic recovery, or idempotency infrastructure was added.
- No schema change is required for these endpoints. The pre-existing dirty `docs/db-structure.md`, untracked metadata migration, and `database/tests/` were left untouched. No shared database connection, migration deployment, reset, seed, or `.env` modification was performed.
- Existing booking timestamp contracts remain unchanged. The closure API alone uses explicit offsets and Singapore presentation.

## Request flow and reading order

1. `services/venue-booking-service/app/closures.py`: development identity guard, validation, HTTP orchestration.
2. Both services' `app/closure_contract.py`: independently deployable closure-only validation (intentionally duplicated, no shared package).
3. Composite `app/closure_clients.py`: `GET /venues/<venueId>` through the existing Venue Service URL, then closure persistence through Venue Availability. The venue profile's existing field is `venue.id`, not `venue.venueId`. No catalogue-status restriction.
4. `services/venue-availability-service/app/closures.py`: repeats identity and input validation, including direct calls to the atomic service; no creator-in-body bypass.
5. Atomic `app/closure_store.py`: parameterized SQL touching only `public."VenueClosure"`; commit on successful creation, rollback on failures, cursor/connection cleanup. Venue/User foreign keys remain the persistence protection. The atomic never calls another service or reads Venue/Booking/Hold/Event tables.
6. Both `tests/unit/test_temporary_closures.py` files: story tests, including injected HTTP/DB boundaries. Existing endpoint tests were not edited.

## API contract (same paths on both services)

| Method/path | Success | Behavior |
| --- | --- | --- |
| `POST /venue-closures` | `201 {"closure": {...}}` | Validate and persist a new record. Composite also checks venue existence through HTTP. |
| `GET /venue-closures/<closureId>` | `200 {"closure": {...}}` | Staff-only read-back; missing closure is 404. |
| `GET /venue-closures?venueId=<UUID>&limit=50&cursor=<opaque>` | `200 {"closures": [...], "nextCursor": string-or-null}` | Staff-only, venue-filtered keyset pagination. |

Create body contains **exactly** `venueId`, `startDateTime`, `endDateTime`, and `reason`. Unknown/server-owned fields (including `createdBy`, `createdAt`, and `closureId`) are rejected, not silently trusted.

- `venueId`: UUID string.
- Start/end: ISO date-times containing `T` and an explicit timezone offset, e.g. `2027-01-15T09:00:00+08:00`; `Z` also works. Naive date-times and unrepresentable instants are rejected.
- Compare actual instants: `end > start` and `end > server now`. A past start is allowed. Treat the recorded period as `[start, end)` for future integrations; this increment performs no overlap enforcement.
- `reason`: mandatory text, trimmed and nonblank; NUL and invalid Unicode are rejected before persistence.
- `createdBy`: validated `X-Dev-User-Id`, never a body value. `createdAt`: UTC server-generated timestamp. `closureId`: existing database UUID default.
- All response timestamps are ISO strings with Singapore `+08:00` offset, not naive strings.

| API field | Existing physical column |
| --- | --- |
| `closureId` | `closure_id` |
| `venueId` | `venue_id` |
| `startDateTime` | `start_date_time` |
| `endDateTime` | `end_date_time` |
| `reason` | `reason` |
| `createdBy` | `created_by` |
| `createdAt` | `created_at` |

The baseline permits null venue/creator/creation metadata. New writes always supply it; old null metadata is returned as JSON null rather than fabricated/backfilled. A null-venue legacy row can be retrieved by closure ID but naturally does not appear in a venue-filtered list.

### Pagination

`venueId` is required. `limit` defaults to 50 and must be 1–100. Unknown or duplicate query parameters, invalid UUIDs/limits, empty/oversized/malformed cursors, and cursors for another venue return 400. Ordering is ascending `(start_date_time, closure_id)`, using a one-row lookahead and a strict tuple continuation predicate. Continue until `nextCursor` is null; results are not silently capped at the first page.

Cursors encode the venue and last ordering key, are not signed, and are not an authorization token. All reads are independently staff-gated. Pagination is not a database snapshot: a concurrent insert before the cursor can require restarting the list to see it. A valid venue-filtered read with no rows returns an empty list, including an unknown venue; list reads do not perform catalogue lookups.

### Errors and simulated identity

Both services require `VENUE_CLOSURE_DEV_MODE=true` (exact lowercase opt-in; false/unset by default), `X-Dev-User-Id: <UUID>`, and `X-Dev-Role: Venue Staff` (exact role spelling).

**These headers are spoofable development simulation, not authentication.** There is no verified JWT or server-side user-role lookup. The creator FK proves existence only, not role. Keep enabled services in a trusted local environment; production security acceptance remains incomplete. Do not enable publicly. Existing endpoints' authentication behavior is outside this increment.

| Status | Meaning |
| --- | --- |
| 400 | Malformed input/query/cursor, invalid interval/reason, server-owned body fields, or nonexistent creator FK. |
| 401 | Missing/invalid development identity or missing role. |
| 403 | Role is not exactly `Venue Staff`. |
| 404 | Missing closure; missing venue on composite creation or atomic venue FK failure. |
| 502 | Malformed JSON/response envelope from a downstream service. |
| 503 | Development mode disabled, unavailable/unconfigured database, or downstream transport/server failure. |

Dependency/SQL details are not exposed in error bodies. The composite forwards controlled atomic error statuses without exposing upstream messages. Both services support unauthenticated OPTIONS preflight for these paths with configured-origin CORS and `Content-Type, X-Dev-User-Id, X-Dev-Role` allowed headers. CORS is not an authentication boundary.

## Local startup and exact example

**Commands below are for a later, explicitly approved local database run, not permission to use the shared database while DB changes are on hold.** No live POST was executed for this review. Use an already configured, approved disposable database containing existing Venue and User rows; do not run migrations, seed/reset, or copy shared credentials as part of this review.

From the repository root, in separate terminals:

```sh
# Venue catalogue (requires its approved database configuration)
cd services/venue-service
uv run flask --app app run --host 127.0.0.1 --port 5006
```

```sh
# Atomic, using its approved DATABASE_URL configuration
cd services/venue-availability-service
VENUE_CLOSURE_DEV_MODE=true uv run flask --app app run --host 127.0.0.1 --port 5008
```

```sh
# Composite: override Docker-style example URLs for host execution
cd services/venue-booking-service
VENUE_CLOSURE_DEV_MODE=true \
VENUE_SERVICE_URL=http://127.0.0.1:5006 \
VENUE_AVAILABILITY_SERVICE_URL=http://127.0.0.1:5008 \
uv run flask --app app run --host 127.0.0.1 --port 5007
```

`FRONTEND_ORIGIN` defaults to `http://localhost:5174`. `.env.example` documents the disabled-by-default flag on both services. Compose forwards `${VENUE_CLOSURE_DEV_MODE:-false}` to both; a shell opt-in overrides the default. Compose's existing `env_file` prerequisites and downstream URL configuration still apply. Full Compose startup was not attempted and no `.env` file was read explicitly or edited.

Example uses clearly synthetic UUIDs: replace both with existing IDs from the approved local database before executing. The date is illustrative; keep the end in the future when testing.

```sh
curl -i http://127.0.0.1:5007/venue-closures \
  -H 'Content-Type: application/json' \
  -H 'X-Dev-User-Id: 00000000-0000-0000-0000-000000000001' \
  -H 'X-Dev-Role: Venue Staff' \
  --data '{"venueId":"00000000-0000-0000-0000-000000000002","startDateTime":"2027-01-15T09:00:00+08:00","endDateTime":"2027-01-15T12:00:00+08:00","reason":"Air-conditioning maintenance"}'

curl -G http://127.0.0.1:5007/venue-closures \
  -H 'X-Dev-User-Id: 00000000-0000-0000-0000-000000000001' \
  -H 'X-Dev-Role: Venue Staff' \
  --data-urlencode 'venueId=00000000-0000-0000-0000-000000000002' \
  --data-urlencode 'limit=50'
```

Read back `/venue-closures/<closureId>` using the returned ID and the same headers. For subsequent list pages, preserve `venueId` and pass `--data-urlencode "cursor=$NEXT_CURSOR"`. Atomic paths are identical on port 5008, with the same opt-in/identity requirements.

### Before retrying an ambiguous save

There is **no idempotency guarantee**. A timeout or lost response can occur after commit; blindly retrying may create another permitted overlapping closure.

1. If a closure ID was received, GET that ID first.
2. Otherwise list the venue's closures, following every cursor; compare interval, trimmed reason, creator, and creation time.
3. If a matching record exists, do not automatically POST again. If the outcome remains ambiguous, reconcile with staff rather than assuming failure.
4. Only retry knowingly; identical legitimate closures and network retries cannot be distinguished automatically in this increment.

## Executed verification

All tests were run using the repository-prescribed **`uv run pytest` with no added coverage flags**, including actual RED runs before each feature slice and GREEN runs after implementation. Initial missing endpoints produced three 404-vs-503 failures per service; the identity/CORS slice produced 14 failures each; input validation produced 16 failures each. Subsequent persistence, reads/pagination, composite orchestration, malformed upstream envelopes, time boundaries, and legacy-null/Unicode regressions were exercised RED→GREEN. A venue-profile contract mismatch was caught and fixed against the actual `venue.id` field.

Final results:

| Command / directory | Actual result |
| --- | --- |
| `uv run pytest` in `services/venue-booking-service` | 179 passed; 90.88% line+branch coverage. |
| `uv run pytest` in `services/venue-availability-service` | 242 passed, 1 live integration test deselected; 99.44% line+branch coverage. |
| `npm run test:backend` from repository root | Exit 0; 1,165 passed across 15 service suites; 1 integration test deselected. |
| Ruff on the eight new Python modules/test files | All checks passed. |
| Black on those eight files | Formatted/verified. |
| `git diff --check` | Passed. |

All new closure production modules have 100% measured line+branch coverage. Remaining service gaps are pre-existing booking paths; they were not expanded into this story. Coverage floors were raised from 87→90 (composite) and 99→99.4 (atomic); atomic reporting precision is 2 so the fractional floor is checked correctly.

Unit HTTP calls are mocked; `pytest-socket` disables sockets. Every closure test in the atomic mocks `psycopg2.connect` (libpq is not intercepted by pytest-socket). Tests exercise real route/contract/store code, SQL bindings, commit, rollback, cursor exit, and connection close. No service was started against a live database.

### Acceptance-to-test map

| Requirement | Representative tests in `test_temporary_closures.py` |
| --- | --- |
| Both entry points guarded, opt-in off by default | `test_closure_disabled_by_default`, `test_staff_guard` |
| Creator from headers, server-owned body fields rejected | `test_invalid_create`, `test_create_persists_only_closure` |
| Existing venue, no status restriction | `test_composite_create_checks_existing_venue_any_status`, `test_downstream_errors`, `test_fk_failure` |
| Nonblank reason, malformed JSON/types/UUIDs | `test_invalid_create`, `test_malformed_json`, `test_reject_nul_reason`, `test_reject_invalid_unicode_reason` |
| Ongoing/future timing and actual instant comparisons | `test_ongoing_and_offset_create`, `test_ongoing_closure_forwarded`, `test_end_equal_server_now`, `test_unsafe_or_equal_instants` |
| Multiple overlapping records accepted; no booking mutations | `test_overlapping_creates_are_not_rejected`, `test_create_persists_only_closure` |
| Read-back / not found / nullable baseline metadata | `test_get_closure_and_missing`, `test_legacy_nullable_metadata`, `test_legacy_null_venue_is_not_string_none` |
| Bounded deterministic pagination / malformed and foreign cursor | `test_list_paginates_with_lookahead_and_foreign_cursor`, `test_invalid_read`, `test_malformed_cursor_payload`, `test_cursor_forwarded_without_truncation` |
| SQL parameters and cleanup on failure | `test_reason_is_parameterized`, `test_create_db_failure_rolls_back_and_closes`, `test_read_failure_cleanup` |
| Controlled upstream failure/malformed responses | `test_downstream_transport_failure`, `test_downstream_errors`, `test_reject_invalid_closure_response`, `test_malformed_downstream_json` |
| Browser preflight contract on both paths/services | `test_preflight`, `test_untrusted_origin_gets_no_cors_grant` |

### Isolated SQL check (not live integration)

The already installed scratch PGlite package was used with an **ephemeral in-memory database**, executing the unchanged tracked baseline schema there only. The four actual production SQL statements were captured using a mocked psycopg2 connection, converting only `%s` placeholders to PGlite `$n` parameters. No package/dependency was added to this repository.

Result: **PASS** for INSERT, single read, ordered lookahead/keyset continuation, UTC/+08:00 equivalence, generated UUID/metadata, permitted overlapping inserts, both existing foreign keys, and unchanged empty VenueBooking rows. This is SQL evidence, not proof of psycopg2/Supabase connectivity, RLS permissions, deployment, concurrency, or a browser-to-service flow.

Local review artifacts (scratch may be pruned):

- `/Users/daphnetok/.hermes/cache/scratch/scrum170-backend-check/capture_sql.py`
- `/Users/daphnetok/.hermes/cache/scratch/scrum170-backend-check/queries.json`
- `/Users/daphnetok/.hermes/cache/scratch/scrum170-backend-check/verify.mjs`
- `/Users/daphnetok/.hermes/cache/scratch/scrum170-backend-check/backend-tests.txt`

No commits or pushes were made. Remaining review gates: independent code review, approved disposable/live integration after the DB hold is lifted, real authentication before production exposure, and separately owned frontend/availability/notification work.
