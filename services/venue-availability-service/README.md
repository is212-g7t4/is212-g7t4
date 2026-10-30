# Venue Availability — SCRUM-25 backend

Owns `public."VenueBooking"`, timed venue holds, and their overlap algorithm. Extends the existing
atomic; there is no duplicate availability/conflict service. The calendar UI
may read this atomic directly; booking writes come through Venue Booking
Service, and Venue Staff hold writes are checked against the signed-in token (see Authentication).
No calls to User/Venue/Event services or their tables are added.
`GET /venues` remains owned by Venue Service.

## Safety Re-Review

If the local database has not applied the closure-rejection migration,
`VENUE_BOOKING_LEGACY_SCHEMA=true` makes ordinary booking reads and decisions
project missing optional closure-history fields as null. It does not alter
the database schema. Closure-rejection writes still require their existing
migration; normal mode remains the default for migrated databases.

`POST /events/<event_id>/venue-bookings/safety-reset` accepts
`{"bookingIds": ["<uuid>"]}` and requires `X-Internal-Service-Token` matching
`INTERNAL_SERVICE_TOKEN` **and** the `Safety Officer` role (SCRUM-10; Safety Check
Service forwards the signed-in Safety Officer's token). All selected bookings must
belong to the event.
Selected active bookings return to `Pending Review` and clear their reviewer;
Cancelled, Expired and Rejected history is not reopened. Other bookings are
unchanged. Only the safety composite calls this internal operation.

## Local setup (from repository root)

Python 3.12+ and `uv` are required. Keep the real root `.env` git-ignored;
it must contain the server-only `DATABASE_URL`. Never put it in a `VITE_` variable.
If starting from scratch, copy root `.env.example` to root `.env` and privately
fill its database password; do not overwrite an existing `.env`.

```sh
cd services/venue-availability-service
uv sync --locked
uv run --env-file ../../.env flask --app app run --host 127.0.0.1 --port 5008
```

This explicitly loads the **root** `.env`, not an assumed service-local file.
Alternatively create a service `.env` using this service's `.env.example` and
use `--env-file .env`. `FRONTEND_ORIGIN` defaults to `http://localhost:5174`, the port
`vite.config.ts` pins with `strictPort`.

From repository root, once the other existing Compose entries' service `.env`
files are configured:

```sh
docker compose up --build venue-availability-service
```

The new Compose entry uses root `.env` and binds `127.0.0.1:5008:5000`.
Do not expose this development service publicly. Full Compose validation can fail on other services' missing
`.env` files even when starting only this service; local Flask avoids that.

## Authentication (SCRUM-8)

Every endpoint except `/health` needs a Supabase access token
(`Authorization: Bearer <token>`); the caller's id and role come from the
token, never from the request. `401` without a valid token. Background
workers send `X-Internal-Token` instead.

### Who may change what (SCRUM-10)

The role is checked first, before the body is read; a wrong role gets
`403 {"message": "Your role cannot change this information."}` and nothing is
written. Create, edit and cancel a booking (`POST /venue-bookings`,
`PATCH /venue-bookings/<id>`, `PATCH .../cancel`): `Event Coordinator` or
`Event Coordinator Lead`. Approve and reject (`PATCH .../approve`, `.../reject`) and
`POST /venue-holds`: `Venue Staff`. `POST /venues/<id>/legacy-conflicts/reconcile`
follows the booking-view roles (coordinators, Venue Staff, Technical Support) because
reading legacy conflicts triggers it. The closure routes were already Venue Staff only.
See [docs/scrum-10-role-based-modification-control.md](../../docs/scrum-10-role-based-modification-control.md).

`GET /venue-bookings` is for internal roles: `Event Coordinator`,
`Event Coordinator Lead`, `Venue Staff`, `Technical Support` and the canonical
alias `Technical Support Staff`. `Event Organiser`, `Attendee` and all other
roles receive `403`.

`POST /venue-holds` requires the `Venue Staff` role. Its JSON body is
`{"venueId": "<UUID>", "expiresAt": "2026-10-09T12:00"}`. Expiry is required,
must be a future naive Singapore-local ISO datetime, and returns `400` if
invalid. A hold conflicting with any non-rejected/non-cancelled booking or
another active hold returns `409`; a missing venue returns `404`. Success is
`201` with the hold ID, venue ID, creation time, expiry and staff ID.

`GET /venue-holds` returns only unexpired holds; the catalogue overlays these
as `On Hold` and naturally returns to the venue's operational status after
expiry. `GET /venue-bookings/window` includes overlapping hold intervals as
`status: "On Hold"`, allowing venue search to hide them. Booking creation and
approval check active holds in the same venue-locked transaction, so a hold
cannot be bypassed by a new or newly approved booking. Holds are `On Hold` rows in
`public."VenueBooking"` (see `docs/db-structure.md`); there is no separate hold
table.

CORS allows only the configured exact `FRONTEND_ORIGIN`, including on errors.
`OPTIONS` requires no token and returns allowed headers
`Content-Type, Authorization` and methods `GET, OPTIONS, POST` on every path.
No wildcard origin or credentials support is enabled. CORS is not authentication.

## Calendar read

`GET /venue-bookings?venueId=<UUID>&dateFrom=<datetime>&dateTo=<datetime>`

The calendar caller also supplies the venue's optional
`setupTimeMinutes` and `turnaroundTimeMinutes`. Event rows are returned when
their effective occupancy (`start - setup` through `end + turnaround`)
overlaps the requested window. The response retains the advertised times and
adds `effectiveStartTime`/`effectiveEndTime`; holds retain their exact stored
interval.

All three parameters are required exactly once. UUID must parse as a UUID.
Both dates must be ISO 8601 datetimes containing `T`; date-only and malformed
values are rejected, never silently ignored. Require `dateFrom < dateTo` and
**at most 42 days**, covering a six-week month grid as well as day/week views.
Missing, duplicate, invalid, reversed, empty or oversized ranges return `400`
before a database query. The bound is a time-window limit, not a row-count cap.

**Time convention:** the database stores `TIMESTAMPTZ`; this service converts
at the database boundary so its API keeps working in Singapore-local time.
Naive input is interpreted as Singapore local; offset input (`Z`, `+08:00`, or
another explicit offset) is converted to Singapore local before binding SQL.
GET output always includes `+08:00`. URL-encode `+` as `%2B`, or use curl's
`--data-urlencode`. No DB timezone conversion/migration is applied.

```sh
curl --get 'http://127.0.0.1:5008/venue-bookings' \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode 'venueId=00000000-0000-0000-0000-0000000000f1' \
  --data-urlencode 'dateFrom=2026-10-01T00:00:00+08:00' \
  --data-urlencode 'dateTo=2026-11-01T00:00:00+08:00'
```

The UUIDs above are illustrative; use a venue selected from `GET /venues`.
`$TOKEN` is the `accessToken` from User Service's `POST /auth/login`.

## Buffer conflicts and legacy reconciliation

Booking creation, modification and approval accept the current venue buffer
values from Venue Booking Service and use the padded half-open interval for
approved-booking, hold and closure checks. The atomic never calls Venue
Service.

`POST /venues/<venueId>/legacy-conflicts/reconcile` receives the current
buffer values from the composite. It identifies pairs whose advertised times
do not overlap but whose effective occupancy does, marks both rows with
`conflict_reason = 'BUFFER_OVERLAP'`, and clears only stale markers owned by
this rule. It never changes event IDs, advertised times, or booking statuses.
A syntactically valid but nonexistent venue returns an empty list, not `404`:
this atomic does not verify another service's entity.

Success envelope: `{"bookings": [...]}`. Each booking keeps `id`, `eventId`,
`venueId`, `requestedBy`, `reviewedBy`, `status`, `requestedStartTime`,
`requestedEndTime`, and adds boolean **`blocksSelection`**.

| Stored status | In calendar | blocksSelection |
|---|---|---|
| Approved | yes | true |
| Pending | yes (legacy DB value) | false |
| Pending Review | yes (existing write value) | false |
| Rejected / Cancelled | no | — |
| Null / unknown status | fail relevant read with 503 | never infer free time |

Overlap is half-open: `existing_start < dateTo AND existing_end > dateFrom`.
Adjacent intervals do not overlap; an interval spanning the entire window does.
Full original booking times are returned, not clipped to the visible window.
Ordering is start time then booking ID. Invalid booking/event/venue IDs,
non-local/non-finite times, null or inverted intervals on relevant non-excluded
records fail the whole response with `503`, never a partial successful list.
SQL explicitly retains null/inverted time candidates so SQL NULL comparisons
cannot hide them. Such invalid intervals for the selected venue fail even
outside the requested window. Null venue IDs are treated conservatively as
potentially relevant to any venue when overlapping or time-invalid. Failures
contain no database exception detail. Nullable requester/reviewer fields remain
nullable; they do not determine overlap.

**Clients must show an error/unknown state on any failed read, not a free calendar.**
This read is a snapshot, not a reservation or a concurrency guarantee.

## Window read — `GET /venue-bookings/window` (SCRUM-26)

`GET /venue-bookings/window?dateFrom=<datetime>&dateTo=<datetime>`

Every venue's bookings overlapping one window, in a single call. The calendar
read above answers for one venue at a time, which is what a calendar grid
needs; Venue Booking Service's venue search asks the opposite question —
"across the whole catalogue, what is taken in this window?" — and doing that
one venue at a time would be N round trips inside a 3-second budget.

Both parameters are required exactly once, must contain `T`, must satisfy
`dateFrom < dateTo`, and must span at most 42 days; anything else is `400`
before a database query. Offset input is converted to Singapore local, as in
the calendar read. **Output times are naive local**, not `+08:00`, and carry
no `blocksSelection`: this is the existing write-side shape, because the
caller matches on `venueId` and `status` only.

Rejected and Cancelled bookings are excluded — they cannot take a venue. A row
this service cannot read raises `503` rather than being dropped, for the same
reason as the calendar: a dropped booking would show a taken venue as free.

**Not role-gated.** The caller is a composite forwarding the signed-in
user's token, not a browser. The endpoint exposes no more than the calendar
read does, and Venue Booking Service applies its own role rule.

```sh
curl --get 'http://127.0.0.1:5008/venue-bookings/window' \
  --data-urlencode 'dateFrom=2026-11-10T09:00:00' \
  --data-urlencode 'dateTo=2026-11-10T12:00:00'
```

## Venue booking writes and event grouping

- `POST /venue-bookings`: body `{eventId, venueId, requestedStartTime,
  requestedEndTime, requiredCapacity, venueRequirements}` (the requester is
  the signed-in caller);
  creates `Pending Review` and stamps `requested_at` with the database's
  `now()` (SCRUM-28); returns `409` on an approved overlap for the same
  venue. Conflict detection keys on venue and time, not event, so overlapping
  requests for different venues in one event remain independent. The write
  accepts **naive** datetime input only and returns naive times.
- Every booking response carries `requestedAt`: the submission time as
  Singapore-offset ISO 8601 (`2030-03-01T10:30:00+08:00`), or `null` for rows
  recorded before SCRUM-28. It also carries the Venue Staff decision
  (SCRUM-29): `reviewedAt` (same format, `null` while undecided) and
  `rejectionReason` (`null` unless a staff member rejected it).
- `GET /events/<eventId>/venue-bookings`: returns all booking rows linked to
  one event, ordered independently by requested start time and booking ID.
- `PATCH /venue-bookings/<id>`: updates one row, scoped by `eventId`, rechecks
  approved-booking/hold conflicts while excluding that row's old interval,
  and resets the selected booking to `Pending Review` with no reviewer,
  decision time or rejection reason, restamping `requested_at` so it rejoins the staff queue as a new
  submission (SCRUM-28 Part B).
- `PATCH /venue-bookings/<id>/cancel`: scopes by `eventId` and retains the
  selected row as `Cancelled`; repeating the request is idempotent.
- `PATCH /venue-bookings/<id>/approve` or `/reject`: body `{setupTimeMinutes?, turnaroundTimeMinutes?, rejectionReason?}`; approval
  rechecks buffered conflicts (`409 VENUE_UNAVAILABLE` + `conflictTypes`).
  Both stamp `reviewed_by` and `reviewed_at = now()` (SCRUM-29).
  - A reject needs `rejectionReason`: text of 1–500 characters after trimming,
    stored trimmed; otherwise `400 REJECTION_REASON_REQUIRED`. A reason sent
    with an approval is ignored.
  - Decisions are final: only `Pending`/`Pending Review` rows can be decided.
    `Cancelled`/`Rejected` return `409 BOOKING_IMMUTABLE`; any other status
    (e.g. `Approved`) returns `409 BOOKING_ALREADY_DECIDED`. To change an
    approved booking, edit it, which sends it back to `Pending Review`.
- `POST /events/<eventId>/venue-bookings/safety-reset` also clears
  `reviewed_at` and `rejection_reason` on the bookings it resets.
- `GET /health` remains available without a sign-in token.

## Tests and review

```sh
# In services/venue-availability-service
# Unit tests (tests/unit). All pytest and coverage settings, including the
# coverage floor, live in pyproject.toml — no flags needed.
uv run pytest
uvx ruff check --isolated --select E4,E7,E9,F,I app tests
# Explicit opt-in: live DB SELECTs only, PostgreSQL read-only transactions;
# prints counts/status codes, never identities or credentials. Marked
# `live`, so it is deselected by every default run.
RUN_LIVE_CALENDAR_SMOKE=true uv run --env-file ../../.env pytest -m live --no-cov -q -s
# Integration tier (tests/integration): the real app and SQL against a
# throwaway postgres:17.6 loaded with the full migration chain. Needs Docker,
# no secrets. See docs/testing/integration-testing.md.
uv run pytest -m integration --no-cov tests/integration
```

See [BACKEND_REVIEW.md](BACKEND_REVIEW.md) for flow, file map, acceptance mapping,
actual verification results and remaining scope. Frontend/AC2 and operational
`venueBlock` support are deferred. Database constraints,
index audits and concurrent-write locking improvements remain separate work.
