# Venue availability

Owns venue booking records **and** the double-booking conflict check
together, in `public."VenueBooking"`. This merges what `INDEX.md`/
`docs/microservices-catalog.md` originally split into two services —
**Booking Conflict Service** (a stateless algorithm) and
**Venue Availabilities Service** (the booking records) — into one atomic.

That split had a structural problem: Booking Conflict Service would need to
check new requests against *existing bookings*, but those are owned by
Venue Availabilities Service, and atomics never call another service (see
`AGENTS.md`). Merging them avoids that, and matches how the equivalent
Equipment domain is already documented (`Equipment Availability` owns both
reservation records and the availability-checking algorithm together).

An atomic — only `venue-booking-service` (composite) calls this.

## 1. Start the service

```
cp .env.example services/venue-availability-service/.env
cd services/venue-availability-service
uv sync
uv run --env-file .env flask --app app run --port 5008
```

Or `docker compose up --build venue-availability-service` / `npm run dev`.

## Endpoints

- `GET /venue-bookings?venueId=&dateFrom=&dateTo=` — calendar read. Returns
  `Pending Review` and `Approved` bookings in the given range (`Rejected`
  bookings are excluded); only `Approved` bookings should be treated as
  blocking by the caller. Omit `venueId` for every venue, which is how
  SCRUM-26's venue search gets the bookings for its window in one call.
  `400` if `dateFrom` or `dateTo` is present but isn't a naive ISO date-time
  (`2026-11-10T09:00:00`; no time-zone offset, since `VenueBooking` stores
  `timestamp without time zone`).
- `POST /venue-bookings` — creates a booking request as `Pending Review`.
  Body: `{"eventId", "venueId", "requestedStartTime", "requestedEndTime", "requestedBy"}`.
  `409` if it overlaps an `Approved` booking for the same venue.
- `PATCH /venue-bookings/<id>/approve` / `PATCH /venue-bookings/<id>/reject`
  — Venue Staff decision. Body: `{"reviewedBy": "<user id>"}`. Approving
  re-checks for conflicts (another booking may have been approved since this
  one was requested) and returns `409` if one now exists.

Overlap is start-inclusive/end-exclusive: `existing_start < new_end AND
existing_end > new_start` (see `docs/supabase-setup.md`).

## Known limitation

No scheduled-maintenance/operational-block support (`Venue.operational_status`
is not a substitute for a dated block) — deferred, per
`docs/supabase-setup.md`.
