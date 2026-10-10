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

## Endpoints

- `GET /venue-search` — SCRUM-26 Venue Search and Filtering. Finds the venues
  that fit an event's requirements **and** are free at the requested time.
  Read-only: nothing is booked.

  Neither atomic can answer this alone — venue characteristics live in Venue
  Service and bookings in Venue Availability Service — so the merge happens
  here. The bookings come from that service's `GET /venue-bookings/window`
  (all venues, one call); its `GET /venue-bookings` is the single-venue
  calendar read SCRUM-25 added, behind a DEV-mode identity simulation a
  composite should not impersonate. The two calls run in parallel (`ThreadPoolExecutor`, 2.5 s timeout
  each), so the search costs the slower one rather than both, which keeps it
  inside AC3's 3-second budget.

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
  request. Body must include `eventId`, `venueId`, `coordinatorId`,
  `requestedStartTime`, `requestedEndTime`, `requiredCapacity`, and
  `venueRequirements`. More than one request may share an `eventId`.
  - `404` if the event doesn't exist, or if `venueId` isn't in Venue
    Service's catalogue.
  - `403` if the event isn't assigned to `coordinatorId`.
  - `409` if the venue exists but isn't `Available`, or if it's already
    booked (Approved) for that time window.
  - `422` if the venue's capacity is below this booking's `requiredCapacity`.
    The event's total attendance is deliberately not used for this check.
  - `201` with the persisted booking (`status: "Pending Review"`) once all
    checks pass.
- `GET /events/<eventId>/booking-requests?coordinatorId=<id>` — lists every
  venue booking for the assigned coordinator's event as a separate item,
  enriched with the venue name.
- `PATCH /booking-requests/<id>` — modifies only the selected booking. The
  body uses the same booking fields as creation. Event assignment, venue
  operational status, booking-specific capacity, and conflicts are checked
  again. Success resets that booking to `Pending Review` and clears its prior
  reviewer; cancelled bookings cannot be modified.
- `PATCH /booking-requests/<id>/cancel` — body `{eventId, coordinatorId}`;
  retains only the selected booking with `status: "Cancelled"`. The operation
  is idempotent and does not alter sibling bookings for the event.
- `PATCH /booking-requests/<id>/approve` / `PATCH /booking-requests/<id>/reject`
  — Venue Staff decision. Body must include `{"reviewedBy": "<user id>"}`.
  - `404` if the booking doesn't exist.
  - `409` on approve if another booking was approved for an overlapping time
    since this one was requested (re-checked at decision time), or if the
    booking was cancelled.
  - `200` with the updated booking otherwise.

## Known limitation

No Forum Service call for logging the approval/rejection reason, and no
async notification — both flagged as planned but not built (see `INDEX.md`).
