# Venue booking

Validates a venue booking request end to end before it's actioned. A
composite — holds no data of its own, calls `event-service` (to confirm the
event exists and is assigned to the requesting coordinator) and
`venue-service` (to confirm the venue is a real catalogue entry, is
operational, and has enough capacity).

## 1. Start the service

Copy `.env.example` to `.env` — the defaults already match the Docker
Compose service names for `EVENT_SERVICE_URL`/`VENUE_SERVICE_URL` (see the
comment in that file for the localhost equivalents if running outside
Docker):

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

- `POST /booking-requests` — validates a venue booking request. Body must
  include `{"eventId": "...", "venueId": "...", "coordinatorId": "..."}`.
  - `404` if the event doesn't exist, or if `venueId` isn't in Venue
    Service's catalogue.
  - `403` if the event isn't assigned to `coordinatorId`.
  - `409` if the venue exists but isn't `Operational`.
  - `422` if the venue's capacity is below the event's expected attendance.
  - `201` with `{"eventId", "venueId", "venueName", "status": "validated"}`
    once all checks pass.

## Known limitation

This only validates suitability — it does **not** check for double-booking
or persist the booking request anywhere. That's the job of Booking Conflict
Service and Venue Availabilities Service, neither of which is built yet (see
`INDEX.md`). Once those exist, this service's `/booking-requests` flow
should also call Booking Conflict Service and write the resulting record to
Venue Availabilities Service before returning `201`.
