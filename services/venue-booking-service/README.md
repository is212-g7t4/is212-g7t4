# Venue booking

Processes a venue booking request end to end. A composite — holds no data of
its own, calls `event-service` (to confirm the event exists and is assigned
to the requesting coordinator), `venue-service` (to confirm the venue is a
real catalogue entry, is operational, and has enough capacity), and
`venue-availability-service` (to persist the booking and check for
double-booking — see that service's README for the merged
Venue Availability + Booking Conflict design).

Called by the frontend directly: the booking flow from the event request
form, and the "Find a venue" page (SCRUM-26). `FRONTEND_ORIGIN` must match
the UI's origin — the Vite dev server is pinned to `http://localhost:5174`.

## 1. Start the service

Copy `.env.example` to `.env` — the defaults already match the Docker
Compose service names for `EVENT_SERVICE_URL`/`VENUE_SERVICE_URL`/
`VENUE_AVAILABILITY_SERVICE_URL` (see the comment in that file for the
localhost equivalents if running outside Docker):

```
cp .env.example services/venue-booking-service/.env
```

Then run:

```
cd services/venue-booking-service
uv sync
uv run --env-file .env flask --app app run --port 5007
```

Alternatively, after creating `.env`, run
`docker compose up --build venue-booking-service` from the repository root —
or just `npm run dev`/`npm run dev:backend`, which brings this up alongside
every other service.

## Tests

```
uv run pytest                                          # unit tier (tests/unit), coverage floor
uv run pytest -m integration --no-cov tests/integration  # integration tier: real httpx client, respx stubs
```

The integration tier needs no Docker and no secrets: every downstream
service is stubbed at the HTTP layer with `respx`. See
`docs/testing/integration-testing.md`.

## SCRUM-47 booking notifications

Venue Availability commits a durable submission intent with each new booking and
one decision intent with the first staff decision for that booking. Its existing
`VenueNotificationOutbox` also continues to own closure-rejection notifications;
closure mutations do not create a second SCRUM-47 decision alert.

Before rollout, apply the additive migration
`database/supabase/migrations/20261027000001_venue_booking_notifications.sql`
through the team's approved database process, then update Venue Availability,
this service's `venue-notification-dispatcher` worker, Notification consumer and
frontend together. Do not drop the outbox on rollback: it may contain pending
work. This source change does not itself apply any migration.

The existing worker (`python -m app.dispatcher`) looks up all `Venue Staff` users
through User Service. `USER_SERVICE_URL` defaults to `http://user-service:5000`
for the existing Compose worker; set it to `http://localhost:5001` when running
on the host. User Service must be reachable; lookup failures or an empty staff
list retain the intent for retry. A successful owner-side expansion atomically
captures the staff recipient list and creates deterministic per-recipient jobs.

Booking IDs, original submitter, requested period and decision are transaction-time
snapshots. Event/venue display names are captured through their HTTP APIs when
submission expansion or decision preparation first succeeds, not at the original
booking transaction. Frozen envelopes are reused on retries, with the existing
leases, broker confirmations and inbox source-ID deduplication. Submission text
uses the booking's requested start/end in Singapore time and links to ordinary
`/venue-requests`; decision alerts go to the original submitter and link to the
existing event booking detail. Edits, cancellations and resubmissions add no
new story alerts and do not change existing booking eligibility.

Initial development checks (not the full coverage/release gate):

```sh
PYTHON_DOTENV_DISABLED=1 uv run --no-env-file --locked pytest -q --no-cov tests/unit/test_scrum47_venue_booking_notifications.py
```

These three backend cases cover submission, approval and rejection with owner,
User, Event and Venue HTTP doubles and a recording publisher. The fourth case,
`src/features/notifications/venueBookingNotifications.test.ts` in the frontend,
checks the staff destination resolver. Real database, broker, service integration,
manual acceptance and the unchanged 100% owner coverage floors remain separate
verification gates.

## Endpoints

Every endpoint except `/health` needs `Authorization: Bearer <token>`
(SCRUM-8); `401` without it. The caller (coordinator or Venue Staff reviewer)
is taken from the token, and the header is forwarded to every downstream
service.

- `GET /venue-search` — SCRUM-26 Venue Search and Filtering. Finds the venues
  that fit an event's requirements **and** are free at the requested time.
  Read-only: nothing is booked.

  Neither atomic can answer this alone — venue characteristics live in Venue
  Service and bookings in Venue Availability Service — so the merge happens
  here. The bookings come from that service's `GET /venue-bookings/window`
  (all venues, one call); its `GET /venue-bookings` is the single-venue
  calendar read SCRUM-25 added. The initial catalogue and availability
  calls run in parallel (`ThreadPoolExecutor`, 2.5 s timeout each). When a
  matching venue has non-zero buffers, one widened availability read includes
  records just outside the advertised event window; the composite then applies
  the exact per-venue padded overlap.

  | Parameter | Required | Notes |
  | --- | --- | --- |
  | `start`, `end` | yes | naive local ISO date-times, e.g. `2026-11-10T09:00:00`. `end` must be after `start`, and `start` must not be in the past |
  | `expectedAttendance` | yes | whole number of at least 1 |
  | `minCapacity` | no | combined with attendance as `max(expectedAttendance, minCapacity)` |
  | `location`, `layout` | no | forwarded to Venue Service |
  | `facility`, `accessibility` | no | repeatable; forwarded to Venue Service |

  Each venue Venue Service returns gets an `availability`:

  | Condition | `availability` | In the results? |
  | --- | --- | --- |
  | `status` is not `Available` (Under Maintenance, or the static `Booked`) | `Not operational` | no |
  | an `Approved` booking overlaps the window | `Booked` | no |
  | only non-approved bookings overlap | `Pending request` | yes |
  | no overlapping booking | `Available` | yes |

  Booking statuses disagree across the system (`Pending` in the live data,
  `Pending Review` from Venue Availability Service), so anything that is not
  `Approved` is treated as a pending request and both spellings behave the
  same.

  - `400` with `{"message", "missing"}` if a required criterion is empty, or
    with a message naming the field if one is invalid.
  - `504` if a downstream service exceeds the timeout.
  - `502` if a downstream service fails — the downstream error text is not
    passed on.
  - `200` with `{"venues": [...], "count": n}`, `Available` venues first then
    `Pending request`, each group by name. No matches is a normal `200` with
    `count: 0`.

  ```json
  {"count": 1, "venues": [
    {"id": "...", "name": "Rooftop Garden", "location": "Level 12, Main Tower",
     "capacity": 150, "facilities": ["lighting", "outdoor", "wifi"],
     "accessibility": "Elevator access, no stairs",
     "supportedLayouts": ["standing", "banquet"],
     "status": "Available", "availability": "Available"}
  ]}
  ```

- `POST /booking-requests` — submits one independently evaluated venue booking
  request. Body must include `eventId`, `venueId`,
  `requestedStartTime`, `requestedEndTime`, `requiredCapacity`, and
  `venueRequirements`. More than one request may share an `eventId`.
  - `404` if the event doesn't exist, or if `venueId` isn't in Venue
    Service's catalogue.
  - `403` if the event isn't assigned to the caller.
  - `409` with `code: "EVENT_NOT_ACCEPTING_VENUE_REQUESTS"` and `eventStatus`
    if the event isn't `Submitted`, `Under Review`, `Approved` or
    `Safety Changes Requested` (SCRUM-28). Checked before the venue
    catalogue, so a refused request makes no further downstream calls.
  - `409` if the venue exists but isn't `Available`, or if it's already
    booked (Approved) for that time window.
  - `422` if the venue's capacity is below this booking's `requiredCapacity`.
    The event's total attendance is deliberately not used for this check.
  - `201` with the persisted booking (`status: "Pending Review"`, plus the
    `requestedAt` submission time) once all checks pass.
- `PUT /venues/<venueId>` — saves a Venue Staff profile edit through Venue
  Service and then automatically reconciles legacy buffer conflicts through
  Venue Availability Service. No booking is cancelled or rescheduled.
- `GET /venues/<venueId>/legacy-conflicts` — returns the current conflict
  pairs with original and effective occupancy times. It reconciles on read so
  later booking edits or cancellations cannot leave stale buffer markers.
- `GET /events/<eventId>/booking-requests` — lists every
  venue booking for the assigned coordinator's event as a separate item,
  enriched with the venue name.
- `PATCH /booking-requests/<id>` — modifies only the selected booking. The
  body uses the same booking fields as creation. Event assignment, venue
  operational status, booking-specific capacity, and conflicts are checked
  again. Success resets that booking to `Pending Review` and clears its prior
  reviewer; cancelled bookings cannot be modified.
- `PATCH /booking-requests/<id>/cancel` — body `{eventId}`;
  retains only the selected booking with `status: "Cancelled"`. The operation
  is idempotent and does not alter sibling bookings for the event.
- **Edit and cancel are gated (SCRUM-28 Part B).** Both answer `409` with
  `code: "EVENT_NOT_ACCEPTING_VENUE_CHANGES"` and `eventStatus` unless the
  event is `Submitted`, `Under Review`, `Approved`, `Safety Changes
  Requested` or `Confirmed`, checked right after the event lookup. For a
  **`Confirmed`** event, this service first calls Safety Check Service's
  `POST /safety-checks/withdraw-for-venue-change` (the event goes back to
  `Approved`; for an edit, after the catalogue and capacity checks pass), then
  changes the booking. If that booking call fails (conflict, immutable, not
  found, 5xx), it calls `POST /safety-checks/restore-after-venue-change` and
  returns the original error; a failed restore is logged at `ERROR` for
  manual repair. If the withdrawal itself is refused, the booking is never
  touched (`403`/`404`/`409` passed through, anything else `502`). Needs
  `SAFETY_CHECK_SERVICE_URL` (default `http://localhost:5012`).
- `PATCH /booking-requests/<id>/approve` / `PATCH /booking-requests/<id>/reject`
  — legacy decision URLs, kept as thin wrappers around `/review` below
  (SCRUM-29): same Venue Staff role, reason, event-status and
  awaiting-review checks, with the decision taken from the URL.

## Venue Staff Request Review

The frontend `/venue-requests` page provides an event-grouped queue, status
filtering and latest-round safety feedback. Each awaiting request has a
**Review** button opening a dialog with the request's details and
Approve/Reject (a reason is required to reject); decided rows show "Approved
on …" / "Rejected on …" and open the same dialog read-only (SCRUM-29).
`GET /booking-requests[?status=Pending|Approved|Rejected]` requires a
signed-in Venue Staff caller. Pending includes both `Pending` and `Pending Review`.
Each event group also carries `eventStart`/`eventEnd` (the event's preferred
dates, `null` when unset) and `awaitingReviewCount`; each booking carries
`requestedAt` (`null` for legacy rows) and `awaitingReview`. Within an event,
awaiting bookings come first, oldest submission first (SCRUM-28).
The composite reads events, bookings and venue names from their owning APIs;
`SAFETY_CHECK_RECORD_SERVICE_URL` supplies safety flags for revision events.

`GET /booking-requests/<id>` (SCRUM-29 AC1) requires the same caller and
opens one request: `booking` (the Venue Availability record plus `venueName`,
`awaitingReview` and the buffered `occupiedFrom`/`occupiedTo` window), `event`
(`id`, `eventName`, `status`, `coordinatorId`, `preferredStartDate`,
`preferredEndDate`, `expectedAttendance`, `venueRequirements`,
`accessibilityNeeds`; unset values are `null`), `venue` (`id`, `name`,
`capacity`, `status`, `setupTimeMinutes`, `turnaroundTimeMinutes`),
`canDecide` and `decisionBlockedReason`. `401`/`403` for identity/role, `404`
for an unknown booking, `502` on a downstream failure, `504` on a timeout.

`PATCH /booking-requests/<id>/review` requires the same caller and body
`{status: "Approved" | "Rejected", rejectionReason?}`; the reviewer is the
signed-in caller. Existing conflict checks still run on approval. Results:

- `200` with the decided booking, including `reviewedBy`, `reviewedAt` and
  `rejectionReason` (SCRUM-29).
- `400` for a bad status;
  `400 REJECTION_REASON_REQUIRED` for a reject whose reason is missing, blank
  or over 500 characters (checked before any downstream call).
- `404` if the booking doesn't exist.
- `409 EVENT_NOT_REVIEWABLE` (+ `eventStatus`) unless the event is Under
  Review, Approved or Safety Changes Requested.
- `409 BOOKING_ALREADY_DECIDED` unless the booking is `Pending`/`Pending
  Review` (also when another staff member decides first).
- `409 BOOKING_IMMUTABLE` for a Cancelled/Rejected booking at Venue
  Availability; `409 VENUE_UNAVAILABLE` + `conflictTypes` when approval would
  overlap (with buffers) an approved booking, an active hold or a closure.
- `502` on a downstream failure.

The staff queue and `GET /events/<id>/booking-requests` pass `reviewedAt` and
`rejectionReason` through, so the coordinator sees why a booking was rejected.

The rejection reason is stored on the booking in Venue Availability
(SCRUM-29). No async decision notification yet —
SCRUM-47 owns that (see `INDEX.md`).
