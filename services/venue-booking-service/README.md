# Venue booking

Processes a venue booking request end to end. A composite — holds no data of
its own, calls `event-service` (to confirm the event exists and is assigned
to the requesting coordinator), `venue-service` (to confirm the venue is a
real catalogue entry, is operational, and has enough capacity), and
`venue-availability-service` (to persist the booking and check for
double-booking — see that service's README for the merged
Venue Availability + Booking Conflict design).

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

- `POST /booking-requests` — submits a venue booking request. Body must
  include `{"eventId": "...", "venueId": "...", "coordinatorId": "..."}`;
  the event's `preferredStartDate`/`preferredEndDate` are used as the
  requested booking window.
  - `404` if the event doesn't exist, or if `venueId` isn't in Venue
    Service's catalogue.
  - `403` if the event isn't assigned to `coordinatorId`.
  - `409` if the venue exists but isn't `Operational`, or if it's already
    booked (Approved) for that time window.
  - `422` if the venue's capacity is below the event's expected attendance.
  - `201` with the persisted booking (`status: "Pending Review"`) once all
    checks pass.
- `PATCH /booking-requests/<id>/approve` / `PATCH /booking-requests/<id>/reject`
  — Venue Staff decision. Body must include `{"reviewedBy": "<user id>"}`.
  - `404` if the booking doesn't exist.
  - `409` on approve if another booking was approved for an overlapping time
    since this one was requested (re-checked at decision time).
  - `200` with the updated booking otherwise.

## Known limitation

No Forum Service call for logging the approval/rejection reason, and no
async notification — both flagged as planned but not built (see `INDEX.md`).
