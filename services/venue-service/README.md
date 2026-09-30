# Venue Service (atomic)

The venue catalogue. Read-only lookups against `public."Venue"` — no add,
edit or booking logic (SCRUM-22, SCRUM-23 and the Venue Availability Service
own those). Called directly by the frontend for a "simple read" (per
`AGENTS.md`: the UI may call an owning atomic directly without a composite in
between), and by `venue-booking-service` when it validates a booking request.

Being an atomic, it calls no other service.

## 1. Start the service

From the repository root, copy the existing database configuration:

```
cp .env services/venue-service/.env
```

Then run:

```
cd services/venue-service
uv sync
uv run --env-file .env flask --app app run --port 5006
```

Alternatively, after creating `services/venue-service/.env`, run
`docker compose up --build venue-service` from the repository root.

## Endpoints

- `GET /venues` — the whole catalogue, ordered by name. Used by the venue
  catalogue cards and by `VenueSelect` on the event request form.
- `GET /venues/<venueId>` — one venue's full profile (SCRUM-24 View Venue
  Details). `404` if the id doesn't match a row, or isn't a UUID; `503` if
  the database is unreachable or `DATABASE_URL` is unset.

Both endpoints share `serialize()` in `app/models.py`, so a venue looks the
same either way:

```json
{
  "venue": {
    "id": "8381b11e-aaae-4d58-bdba-2607e9e2bde2",
    "name": "Grand Ballroom",
    "location": "Level 3, Main Tower",
    "capacity": 500,
    "facilities": ["av_system", "stage", "wifi"],
    "accessibility": "Wheelchair accessible, elevator access",
    "supportedLayouts": ["theatre", "banquet", "classroom"],
    "status": "Available"
  }
}
```

`GET /venues` returns the same objects under a `venues` array.

## Data notes

- `operational_status` is one of `Available`, `Under Maintenance` or
  `Booked`. Venue Booking Service only accepts `Available`; every status is
  still viewable here.
- `facilities` is stored as a jsonb object of booleans in live rows
  (`{"wifi": true, "kitchen": false}`) but as an array in older seed data.
  `serialize()` accepts both and always sends a sorted list of names, keeping
  only the enabled ones.
- `supported_layouts` is a jsonb array of lowercase names.
- Missing values are sent as `null` (capacity), `""` (text) or `[]` (lists)
  so the UI can render "Not specified".

## Tests

```
uv run pytest --cov=app --cov-report=term-missing
```

`tests/test_venue_details.py` covers AC1 and the failure cases with
`psycopg2.connect` mocked; `tests/test_seed_data.py` checks that
`scripts/seed_venues.py` writes rows in the shape above.

## Seeding

`scripts/seed_venues.py` upserts the catalogue by `venue_name`. It holds the
same 9 venues that are in live Supabase, so running it against the live
database changes nothing and a fresh database gets the same catalogue.
