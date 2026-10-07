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
  catalogue cards and by `VenueSelect` on the event request form. Optional
  filter parameters (SCRUM-26) narrow it to the venues meeting an event's
  requirements — this service's suitability-check computation:

  | Parameter | Repeatable | Matching rule |
  | --- | --- | --- |
  | `minCapacity` | no | `max_capacity >= minCapacity`. A venue with no capacity is excluded, since it can't be confirmed to fit |
  | `location` | no | case-insensitive "contains", so `Main Tower` matches `Level 3, Main Tower` |
  | `layout` | no | `supported_layouts` contains the value |
  | `facility` | yes | the venue has **every** facility given |
  | `accessibility` | yes | **every** key given matches the venue's accessibility text |

  Blank values count as not set, so `GET /venues` with no parameters is
  exactly the full catalogue as before. `400` if `minCapacity` is not a whole
  number of at least 1, or if an `accessibility` key is unknown.

  Accessibility is free text in the database, so each key maps to the phrases
  the live rows use (matched case-insensitively; any one phrase is enough):

  | Key | Label | Matches text containing |
  | --- | --- | --- |
  | `wheelchair` | Wheelchair accessible | "wheelchair" |
  | `lift` | Lift or elevator access | "lift", "elevator" |
  | `step_free` | Step-free entrance | "level entrance", "no stairs" |
  | `hearing_loop` | Hearing loop | "hearing loop" |
  | `accessible_washroom` | Accessible washroom | "accessible washroom" |

  The filter runs in Python (`matches()` in `app/models.py`) rather than SQL:
  the catalogue is small, and the rule stays readable and testable without a
  database.
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
uv run pytest
```

All pytest and coverage settings, including the coverage floor, live in
`pyproject.toml`, so this needs no flags.

`tests/unit/test_venue_details.py` covers AC1 and the failure cases with
`psycopg2.connect` mocked; `tests/unit/test_venue_search_filters.py` covers the
SCRUM-26 filter parameters above; `tests/unit/test_seed_data.py` checks that
`scripts/seed_venues.py` writes rows in the shape above. Shared payloads and row
builders live in `tests/unit/factories.py`.

## Seeding

`scripts/seed_venues.py` upserts the catalogue by `venue_name`. It holds the
same 9 venues that are in live Supabase, so running it against the live
database changes nothing and a fresh database gets the same catalogue.
