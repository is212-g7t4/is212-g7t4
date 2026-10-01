# SCRUM-26 Venue Search and Filtering — manual test script

The frontend has no test runner, so the UI acceptance criteria for this story
are verified by hand against `npm run dev`. Fill in the Result and Notes
columns, then attach this file and the screenshots to SCRUM-26.

**Tester:** _______________  **Date:** _______________
**Branch / commit:** `SCRUM-26-venue-search-and-filtering` @ _______________

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
| 1 | Open **Find a venue** from the sidebar | All seven criteria are present; Date, Start time, End time and Expected attendance are marked with a red asterisk | AC1 | | |
| 2 | Click **Search** with every field empty | "Please fill in the required fields: Date, Start time, End time, Expected attendance"; **no** request to `/venue-search` in the Network tab | AC2 | | |
| 3 | Fill only the date, click **Search** | The message now lists only Start time, End time and Expected attendance | AC2 | | |
| 4 | Date 10 Nov 2026, 09:00–12:00, attendance 120, click **Search** | Results appear. Record the `/venue-search` duration from the Network tab — it must be under 3000 ms | AC3 | | ___ ms |
| 5 | Inspect each result card | Each shows name, location, capacity, accessibility, every supported layout, every facility, and an availability badge | AC4 | | |
| 6 | Look at the step 4 result list | Grand Ballroom (Approved booking on 10 Nov 09:00–17:00) and Auditorium (Under Maintenance) are **not** listed | AC3 | | |
| 7 | Search 22 Nov 2026, 10:00–16:00, attendance 100 | Rooftop Garden shows an amber **Pending request** badge; hovering it explains another request is waiting for review | AC4 | | |
| 8 | To the step 4 search add location "Level 12", layout `banquet` and facility `outdoor`, then Search | Only the rooftop venues remain | AC3 | | |
| 9 | Also tick accessibility "Hearing loop" and set attendance to 1000, then Search | "No venues are available for the selected date, time and requirements." | AC5 | | |
| 10 | Click **Clear all** once | Every field is empty, results and messages are gone, and the URL is `/venue-search` with no query string | AC6 | | |
| 11 | Run the step 4 search, click a result card, then press browser Back | The same criteria and the same results come back | Navigation | | |
| 12 | Switch to Venue Staff, Event Organiser and Technical Support in turn, and open `/venue-search` directly | Each sees "Venue search is available to Event Coordinators." and has no "Find a venue" nav item | Role rule | | |
| 13 | Stop Venue Availability Service, then Search again | "Unable to search venues right now." — an error message, no blank page or crash | Failure | | |
| 14 | Restart Venue Availability Service and Search again | Results come back without reloading the page | Recovery | | |

## Screenshots to attach

1. Step 2 — the required-field message with an empty Network tab.
2. Step 4 — results, with the Network tab timing visible.
3. Step 7 — a card with the Pending request badge.
4. Step 9 — the no-matches message.
5. Step 12 — the notice shown to Venue Staff.

## Backend tests (run before the manual pass)

```
cd services/venue-service              && uv run pytest --cov=app --cov-report=term-missing
cd services/venue-availability-service && uv run pytest --cov=app --cov-report=term-missing
cd services/venue-booking-service      && uv run pytest --cov=app --cov-report=term-missing
```
