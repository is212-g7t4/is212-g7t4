# Venue Service (atomic)

The venue catalogue. It owns lookups and Venue Staff profile creation/editing
against `public."Venue"`, including each venue's setup and turnaround minutes
and its safety information (SCRUM-167).
It contains no booking logic (Venue Availability Service owns that). The
frontend calls it directly because Venue Service owns this catalogue concern,
and `venue-booking-service` calls it when validating a booking request.

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
  catalogue cards, the venue calendar and venue search. Optional
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
    "status": "Available",
    "setupTimeMinutes": 30,
    "turnaroundTimeMinutes": 45,
    "emergencyAccessDetails": "Exits on north and south walls; assembly point at the front lawn",
    "knownRestrictions": "Noise curfew 10pm; no open flames",
    "safetyInfoUpdatedBy": "5b1f0c2e-7d3a-4c1e-9f6b-2a8d4e0c1b37",
    "safetyInfoUpdatedAt": "2030-01-15T10:30:00+08:00"
  }
}
```

`GET /venues` returns the same objects under a `venues` array. The four
safety fields are `null` until Venue Staff record something; Safety Check
Service reads them from the catalogue list for the Safety Officer's review.

- `PUT /venues/<venueId>/safety-info` — SCRUM-167 Record Venue Safety
  Information. Venue Staff only. Replaces both texts and stamps the editor and
  the database's `now()`.

  Header: `Authorization: Bearer <token>` (SCRUM-8). The editor and role come
  from the signed-in user's token.

  Body (both keys required; send `null` to clear one):

  ```json
  { "emergencyAccessDetails": "string or null", "knownRestrictions": "string or null" }
  ```

  Text is trimmed; blank text is stored as `NULL` (so the UI shows "Not
  provided"); at most 2000 characters each.

  | Status | When |
  | --- | --- |
  | `200 { venue }` | saved. If neither value changed, nothing is written and the existing stamp is kept |
  | `400 { message, errors }` | not a JSON object, a key missing, a value not text, or over 2000 characters |
  | `401 { message }` | no valid sign-in token |
  | `403 { code: "VENUE_STAFF_ONLY" }` | any role other than Venue Staff |
  | `403 { code: "UNKNOWN_EDITOR" }` | the editor id is not a `User` row (the `safety_info_updated_by` foreign key refuses it) |
  | `404` | no such venue |
  | `503` | `DATABASE_URL` unset or the database unreachable |

  Two staff saving at once: last write wins, and the stamp names the last
  writer. The update is a single statement, so there is no read-modify-write
  race. `POST /venues` and `PUT /venues/<id>` (the profile routes, which have
  no role check) ignore these keys, so they can't be used to bypass this one.

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

Integration tests (real Flask app against a throwaway `postgres:17.6` loaded
with the full migration chain; Docker must be running):

```
uv run pytest -m integration --no-cov
```

`tests/unit/test_venue_details.py` covers AC1 and the failure cases with
`psycopg2.connect` mocked; `tests/unit/test_venue_search_filters.py` covers the
SCRUM-26 filter parameters above; `tests/unit/test_seed_data.py` checks that
`scripts/seed_venues.py` writes rows in the shape above. Shared payloads and row
builders live in `tests/unit/factories.py`.
`tests/unit/test_venue_safety_information.py` and
`tests/integration/test_venue_safety_information.py` cover SCRUM-167.

## Seeding

`scripts/seed_venues.py` upserts the catalogue by `venue_name`. It holds the
same 9 venues that are in live Supabase, so running it against the live
database changes nothing and a fresh database gets the same catalogue.
