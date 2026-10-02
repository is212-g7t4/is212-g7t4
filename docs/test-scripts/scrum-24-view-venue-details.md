# SCRUM-24 View Venue Details — manual test script

This script predates the frontend test setup (Vitest and Playwright e2e now
exist), so the UI acceptance criteria for this story are verified by hand
against `npm run dev`. Fill in the Result and Notes
columns, then attach this file and the screenshots to SCRUM-24.

**Tester:** _______________  **Date:** _______________
**Branch / commit:** `SCRUM-24-view-venue-details` @ _______________

## Acceptance criteria under test

- **AC1** — A user can view a venue's characteristics: location, capacity,
  facilities, accessibility, supported room layouts and operating
  information.
- **AC2** — Event Coordinators see venue details read-only; they get no Add
  or Edit venue controls.
- **Role rule** — Only Event Coordinators and Venue Staff can view venues.

## Setup

1. Start Venue Service:

   ```
   cd services/venue-service
   cp ../../.env .env          # once, if you haven't already
   uv sync
   uv run --env-file .env flask --app app run --port 5006
   ```

2. Confirm it answers: `curl http://localhost:5006/health` → `{"status":"ok"}`.
3. Start User Service on port 5001 (the "Viewing as" switcher reads from it).
4. Start the SPA:

   ```
   cd frontend/event-management-ui
   npm install
   npm run dev
   ```

5. Note a real venue id for the URL-based steps:

   ```
   curl -s http://localhost:5006/venues | python3 -m json.tool | head -20
   ```

Switch roles with the **Viewing as** dropdown in the top bar.

## Steps

| # | Steps (Viewing as …) | Expected | Criterion | Result (P/F) | Notes |
|---|---|---|---|---|---|
| 1 | **Event Coordinator**: click **Venues** in the sidebar | The catalogue shows one **card** per venue (9 with current data), not a table. Each card has the name, a status badge, location, capacity, facility chips and a "View details →" link. A "Last updated …" line is shown. | AC1 | | |
| 2 | **Event Coordinator**: click the **Grand Ballroom** card | Navigates to `/venues/<id>`. The detail page shows Location, Capacity (500 people), Accessibility, Facilities, Supported layouts and Operating status. Page title reads "Venue details". | AC1 | | |
| 3 | **Event Coordinator**: inspect the detail page and the catalogue closely | No **Add venue** or **Edit venue** control anywhere, no input fields, no save button. The only buttons are **← Back to venue catalogue** and **Refresh**. | AC2 | | |
| 4 | **Venue Staff**: repeat steps 1 and 2 | Identical cards and identical read-only detail page. No Add or Edit controls (none exist yet — SCRUM-22/SCRUM-23 will add them, gated by `canManageVenues`). | AC1 | | |
| 5 | **Event Organiser**, then **Technical Support**: paste `/venues` and then `/venues/<id>` into the address bar and reload | Both show the notice "The Venue Catalogue is visible to Event Coordinators and Venue Staff." No venue data is rendered, and the **Venues** nav item is absent from the sidebar. | Role rule | | |
| 6 | **Event Coordinator**: open the **Auditorium** (Under Maintenance) and **Conference Room A** (Booked) | Each page loads normally and the status badge shows that exact status. A non-Available venue is still fully viewable. | AC1, boundary | | |
| 7 | **Event Coordinator**: open `/venues/00000000-0000-0000-0000-000000000000` | A clear "Venue not found." message, with the Back button still available. No blank page or console crash. | Failure | | |
| 8 | Stop Venue Service (Ctrl-C), then reload a detail page | An error message is shown in place of the card; the app does not crash. Restarting the service and clicking **Refresh** recovers the page. | Failure | | |
| 9 | From a detail page, press the browser **Back** button | Returns to the venue catalogue with the cards intact, and the **Venues** nav item stays highlighted throughout. | Navigation | | |

## Screenshots to attach

1. Catalogue card grid as Event Coordinator (step 1).
2. Grand Ballroom detail page (step 2).
3. Role notice as Event Organiser (step 5).
4. "Venue not found." state (step 7).

## Result

**Overall:** Pass / Fail — _______________

**Defects raised:** _______________
