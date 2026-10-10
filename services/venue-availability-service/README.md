# Venue Availability — SCRUM-25 backend

Owns `public."VenueBooking"`, timed venue holds, and their overlap algorithm. Extends the existing
atomic; there is no duplicate availability/conflict service. The calendar UI
may read this atomic directly; booking writes come through Venue Booking
Service, and Venue Staff hold writes use the DEV identity simulation below.
No calls to User/Venue/Event services or their tables are added.
`GET /venues` remains owned by Venue Service.

## Local setup (from repository root)

Python 3.12+ and `uv` are required. Keep the real root `.env` git-ignored;
it must contain the server-only `DATABASE_URL`. Never put it in a `VITE_` variable.
If starting from scratch, copy root `.env.example` to root `.env` and privately
fill its database password; do not overwrite an existing `.env`.

```sh
cd services/venue-availability-service
uv sync --locked
CALENDAR_DEV_MODE=true uv run --env-file ../../.env flask --app app run --host 127.0.0.1 --port 5008
```

This explicitly loads the **root** `.env`, not an assumed service-local file.
Alternatively create a service `.env` using this service's `.env.example` and
use `--env-file .env`. `FRONTEND_ORIGIN` defaults to `http://localhost:5174`, the port
`vite.config.ts` pins with `strictPort`.

From repository root, once the other existing Compose entries' service `.env`
files are configured:

```sh
CALENDAR_DEV_MODE=true docker compose up --build venue-availability-service
```

The new Compose entry uses root `.env` and binds `127.0.0.1:5008:5000`.
It defaults to disabled DEV calendar mode. Do not expose this development
service publicly. Full Compose validation can fail on other services' missing
`.env` files even when starting only this service; local Flask avoids that.

## DEV user-switcher header contract — NOT authentication

Calendar reads are disabled (`503`) unless environment **`CALENDAR_DEV_MODE=true`**
is set exactly (lowercase). The Flask test/config equivalent is boolean `True`.
This deliberate opt-in only simulates the existing user-switcher's identity.

Every `GET /venue-bookings` needs both headers:

| Header | Value |
|---|---|
| `X-Dev-User-Id` | Selected user's UUID; syntactically validated, **not** looked up |
| `X-Dev-Role` | Exact selected role string |

Allowed roles: `Event Coordinator`, `Venue Staff`, `Technical Support`, and the
canonical alias `Technical Support Staff`. `Event Organiser`, `Attendee` and
all other role strings receive `403`. Missing/invalid user UUID or missing role
receives `401`. There is no user-table query, JWT verification or real auth.
**Headers are caller-supplied and spoofable. This is not secure access control.**
Production must replace this simulation with verified identity/role enforcement.
Existing POST/PATCH endpoints are intentionally not gated or reworked here.

`POST /venue-holds` requires `CALENDAR_DEV_MODE=true`, a valid
`X-Dev-User-Id`, and exact `X-Dev-Role: Venue Staff`. Its JSON body is
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
cannot be bypassed by a new or newly approved booking. Database setup must
apply `database/supabase/migrations/20261008100000_create_venue_hold.sql`.

CORS allows only the configured exact `FRONTEND_ORIGIN`, including on errors.
`OPTIONS /venue-bookings` requires no identity and returns allowed headers
`Content-Type, X-Dev-User-Id, X-Dev-Role` and methods `GET, OPTIONS, POST`.
No wildcard origin or credentials support is enabled. CORS is not authentication.

## Calendar read

`GET /venue-bookings?venueId=<UUID>&dateFrom=<datetime>&dateTo=<datetime>`

All three parameters are required exactly once. UUID must parse as a UUID.
Both dates must be ISO 8601 datetimes containing `T`; date-only and malformed
values are rejected, never silently ignored. Require `dateFrom < dateTo` and
**at most 42 days**, covering a six-week month grid as well as day/week views.
Missing, duplicate, invalid, reversed, empty or oversized ranges return `400`
before a database query. The bound is a time-window limit, not a row-count cap.

**Time convention:** existing DB timestamps are Singapore-local naive values.
Naive input is interpreted as Singapore local; offset input (`Z`, `+08:00`, or
another explicit offset) is converted to Singapore local before binding SQL.
GET output always includes `+08:00`. URL-encode `+` as `%2B`, or use curl's
`--data-urlencode`. No DB timezone conversion/migration is applied.

```sh
curl --get 'http://127.0.0.1:5008/venue-bookings' \
  -H 'X-Dev-User-Id: 00000000-0000-0000-0000-000000000001' \
  -H 'X-Dev-Role: Event Coordinator' \
  --data-urlencode 'venueId=00000000-0000-0000-0000-0000000000f1' \
  --data-urlencode 'dateFrom=2026-10-01T00:00:00+08:00' \
  --data-urlencode 'dateTo=2026-11-01T00:00:00+08:00'
```

The UUIDs above are illustrative; use a venue selected from `GET /venues`.
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

**Not behind `CALENDAR_DEV_MODE` or the `X-Dev-*` headers.** Those simulate
the browser's user switcher, and this caller is a composite, not a browser —
it has no user identity to forward and should not invent one. The endpoint
exposes no more than the calendar read does, and Venue Booking Service applies
its own role rule. If the DEV simulation is ever replaced by real
service-to-service auth, this endpoint is a caller to cover.

```sh
curl --get 'http://127.0.0.1:5008/venue-bookings/window' \
  --data-urlencode 'dateFrom=2026-11-10T09:00:00' \
  --data-urlencode 'dateTo=2026-11-10T12:00:00'
```

## Venue booking writes and event grouping

- `POST /venue-bookings`: body `{eventId, venueId, requestedStartTime,
  requestedEndTime, requiredCapacity, venueRequirements, requestedBy}`;
  creates `Pending Review`; returns `409` on an approved overlap for the same
  venue. Conflict detection keys on venue and time, not event, so overlapping
  requests for different venues in one event remain independent. The write
  accepts **naive** datetime input only and returns naive times.
- `GET /events/<eventId>/venue-bookings`: returns all booking rows linked to
  one event, ordered independently by requested start time and booking ID.
- `PATCH /venue-bookings/<id>`: updates one row, scoped by `eventId`, rechecks
  approved-booking/hold conflicts while excluding that row's old interval,
  and resets the selected booking to `Pending Review` with no reviewer.
- `PATCH /venue-bookings/<id>/cancel`: scopes by `eventId` and retains the
  selected row as `Cancelled`; repeating the request is idempotent.
- `PATCH /venue-bookings/<id>/approve` or `/reject`: body `{reviewedBy}`;
  approval rechecks conflicts. `Cancelled` is terminal and cannot be edited,
  approved, or rejected.
- `GET /health` remains available without DEV headers.

## Tests and review

```sh
# In services/venue-availability-service
# Unit tests (tests/unit). All pytest and coverage settings, including the
# coverage floor, live in pyproject.toml — no flags needed.
uv run pytest
uvx ruff check --isolated --select E4,E7,E9,F,I app tests
# Explicit opt-in: live DB SELECTs only, PostgreSQL read-only transactions;
# prints counts/status codes, never identities or credentials. Marked
# `integration`, so it is deselected by every default run.
RUN_LIVE_CALENDAR_SMOKE=true uv run --env-file ../../.env pytest -m integration --no-cov -q -s
```

See [BACKEND_REVIEW.md](BACKEND_REVIEW.md) for flow, file map, acceptance mapping,
actual verification results and remaining scope. Frontend/AC2 and operational
`venueBlock` support are deferred. Real authentication, database constraints,
index audits and concurrent-write locking improvements remain separate work.
