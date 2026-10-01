# SCRUM-26 Venue Search and Filtering — manual test script

The frontend has no test runner, so the UI acceptance criteria for this story
are verified against `npm run dev`. The steps below are written to be
followed by hand, and are also scripted with Playwright so the pass can be
repeated — see the two `.mjs` files beside this one. Attach this file and
`scrum-26-screenshots/` to SCRUM-26.

**Tester:** Clarice Lim (driven with Playwright — see
`scrum-26-venue-search.spec.mjs` beside this file)
**Date:** 1 Oct 2026
**Branch / commit:** `SCRUM-26-venue-search-and-filtering` @ `58645ad`+
**Result: 14/14 passed**, against live Supabase data with all four services
and `npm run dev` running locally. Screenshots are in
`scrum-26-screenshots/`.

Re-run it with the three venue services, User Service and the Vite dev
server up:

```
node docs/test-scripts/scrum-26-venue-search.spec.mjs
# then stop venue-availability-service and run step 13 on its own:
node docs/test-scripts/scrum-26-venue-search-step13.spec.mjs
```

## Acceptance criteria under test

- **AC1** — The search offers date and time, expected attendance, location,
  minimum capacity, accessibility requirements, supported layout and required
  facilities. Date, time and expected attendance are required.
- **AC2** — Searching without the required criteria shows a message naming
  them, and sends nothing.
- **AC3** — Results are the venues matching all active criteria, returned
  within 3 seconds.
- **AC4** — Each result shows the venue's details and its availability for
  the requested time.
- **AC5** — When nothing matches, a clear "no venues are available" message
  is shown.
- **AC6** — All filters can be cleared in one click.
- **Role rule** — The page is for Event Coordinators.

## Setup

1. Start the three venue services, each with a `.env` copied from the
   repository root (`cp .env services/<service>/.env`) and
   `FRONTEND_ORIGIN=http://localhost:5174`:

   ```
   cd services/venue-service              && uv run --env-file .env flask --app app run --port 5006
   cd services/venue-booking-service      && uv run --env-file .env flask --app app run --port 5007
   cd services/venue-availability-service && uv run --env-file .env flask --app app run --port 5008
   ```

   Running `venue-booking-service` outside Docker needs the localhost
   downstream URLs from the comment in its `.env.example`:
   `VENUE_SERVICE_URL=http://localhost:5006` and
   `VENUE_AVAILABILITY_SERVICE_URL=http://localhost:5008`.

2. Confirm each answers `/health` with `{"status":"ok"}`.
3. Start User Service on port 5001 (the "Viewing as" switcher reads from it).
4. Start the SPA:

   ```
   cd frontend/event-management-ui
   npm install
   npm run dev
   ```

5. Open the browser DevTools Network tab and keep it open — steps 2 and 4
   depend on it.

## Steps

Viewing as an **Event Coordinator** unless a step says otherwise.

| # | Steps | Expected | Criterion | Result (pass/fail) | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | Open **Find a venue** from the sidebar | All seven criteria are present; Date, Start time, End time and Expected attendance are marked with a red asterisk | AC1 | pass | All nine controls present; exactly four asterisks |
| 2 | Click **Search** with every field empty | "Please fill in the required fields: Date, Start time, End time, Expected attendance"; **no** request to `/venue-search` in the Network tab | AC2 | pass | Message listed all four; 0 requests to `/venue-search` |
| 3 | Fill only the date, click **Search** | The message now lists only Start time, End time and Expected attendance | AC2 | pass | Message dropped Date, kept the other three; 0 requests |
| 4 | Date 10 Nov 2026, 09:00–12:00, attendance 120, click **Search** | Results appear. Record the `/venue-search` duration from the Network tab — it must be under 3000 ms | AC3 | pass | 3 results in **727 ms** |
| 5 | Inspect each result card | Each shows name, location, capacity, accessibility, every supported layout, every facility, and an availability badge | AC4 | pass | Name, location, capacity, accessibility, labelled Layouts/Facilities chips, badge |
| 6 | Look at the step 4 result list | Grand Ballroom (Approved booking on 10 Nov 09:00–17:00) and Auditorium (Under Maintenance) are **not** listed | AC3 | pass | Neither listed |
| 7 | Search 22 Nov 2026, 10:00–16:00, attendance 100 | Rooftop Garden shows an amber **Pending request** badge; hovering it explains another request is waiting for review | AC4 | pass | Amber *Pending request* badge, sorted last; tooltip present |
| 8 | To the step 4 search add location "Level 12", layout `banquet` and facility `outdoor`, then Search | Only the rooftop venues remain | AC3 | pass | Rooftop Garden and Rooftop Terrace only |
| 9 | Also tick accessibility "Hearing loop" and set attendance to 1000, then Search | "No venues are available for the selected date, time and requirements." | AC5 | pass | AC5 message shown |
| 10 | Click **Clear all** once | Every field is empty, results and messages are gone, and the URL is `/venue-search` with no query string | AC6 | pass | All inputs empty, 0 checkboxes, layout reset, URL `/venue-search` |
| 11 | Run the step 4 search, click a result card, then press browser Back | The same criteria and the same results come back | Navigation | pass | Detail page opened; Back restored the date and the same 3 results |
| 12 | Switch to Venue Staff, Event Organiser and Technical Support in turn, and open `/venue-search` directly | Each sees "Venue search is available to Event Coordinators." and has no "Find a venue" nav item | Role rule | pass | All three roles: notice shown, 0 nav items |
| 13 | Stop Venue Availability Service, then Search again | "Unable to search venues right now." — an error message, no blank page or crash | Failure | pass | HTTP 502 -> "Unable to search venues right now."; form still usable, 0 JS errors |
| 14 | Restart Venue Availability Service and Search again | Results come back without reloading the page | Recovery | pass | 3 results, no reload |

## Screenshots

In `scrum-26-screenshots/`, captured during the run recorded above:

| File | Step |
| --- | --- |
| `01-form.png` | 1 — the empty form |
| `02-required-message.png` | 2 — the required-field message |
| `04-results.png` | 4 — results |
| `07-pending-badge.png` | 7 — the Pending request badge |
| `08-filtered.png` | 8 — the narrowed search |
| `09-no-matches.png` | 9 — the no-matches message |
| `10-cleared.png` | 10 — after Clear all |
| `11-back.png` | 11 — after browser Back |
| `12-venue-staff-notice.png` | 12 — the notice shown to Venue Staff |
| `13-downstream-error.png` | 13 — Venue Availability down |
| `14-recovered.png` | 14 — after the restart |

## Backend tests (run before the manual pass)

```
cd services/venue-service              && uv run pytest --cov=app --cov-report=term-missing
cd services/venue-availability-service && uv run pytest --cov=app --cov-report=term-missing
cd services/venue-booking-service      && uv run pytest --cov=app --cov-report=term-missing
```
