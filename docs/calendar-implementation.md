# SCRUM-25 — frontend implementation and review

This is the **frontend continuation**, after the backend review checkpoint. The historical
`services/venue-availability-service/BACKEND_REVIEW.md` is intentionally preserved;
its “frontend deferred” statements describe that earlier checkpoint, not this deliverable.
No backend source/contract, live data, schema, commit or push was changed by this phase.
`git fetch origin main` confirmed `219d63a` (PR #18, Venue Details); no reset/rebase/stash
or merge was used against the existing uncommitted work.

> **Current acceptance revision (October 1, 2026):** AC3 is **visual blocking only**.
> Approved, Pending and Pending Review ranges are all inspectable. Inspection independently
> fetches the requested dates (including outside the grid), never reserves time, and never
> relies on the visible cached dataset. Earlier RED/GREEN and browser evidence concerning
> disabled overlap/window restriction is historical and **superseded**, not current guidance.
> See section 11 for the current contract, tests, and verification.

## 1. Establish the boundary and test runner

**Why:** calendar reads belong to the existing Availability atomic; venue choices belong
to Venue Service. Reusing `fetchVenues()` avoids a second catalogue or invented data.
The request-only `VenueSelect` suitability/status filters are deliberately **not reused**.

Read AGENTS, architecture/index, current route/switcher/catalogue code, backend README,
BACKEND_REVIEW, calendar response code and live-test safeguards first. Added Vitest 4,
React Testing Library, jest-dom, user-event and jsdom as development dependencies.
The lockfile records the resolved versions; no calendar/date runtime dependency was added.
Existing Vite 8 / React 19 build remains intact. `vitest.config.ts` selects jsdom and
`src/test/setup.ts` cleans up rendered trees after each test.

Official references consulted: https://vitest.dev/guide/ and
https://react.dev/reference/react/useEffect (including the effect-cleanup stale-response
pattern). Testing Library documentation retrieval was blocked by HTTP error; installed
package peer compatibility and actual tests/build were checked instead. On this host,
Node 26.8.1, Vitest 4.1.11, React 19.3.0, Vite 8.3.0 were executed successfully.
`npm install` reported zero vulnerabilities. Package-intelligence lookups emitted timeout
warnings (not a clean security audit); the optional fsevents install script was not approved.

## 2. Make Singapore time explicit

**Files:** `src/features/calendar/dates.ts`, `dates.test.ts`.

**Input → output:** an instant becomes a Singapore date using `Intl` with
`timeZone: 'Asia/Singapore'`; a date and view become half-open date boundaries.
UTC date arithmetic is used *only as calendar arithmetic*, never as the meaning of a
user's local date/time. A week starts Monday. A month displays exactly six weeks,
which fits the backend's 42-day maximum. Month navigation clamps January 31 to February's
last day. Toggling views keeps the anchor rather than replacing it with the grid start.

Native datetime controls are explicitly labelled SGT. Text entered there is interpreted
as Singapore time by appending `+08:00`, not parsed as browser-local time. Minute or
second text is accepted, with no booking-duration business rule. Controls have second
precision; sub-second inspection is not offered. Invalid dates are rejected rather than
letting JavaScript silently roll February 30 into March. Half-open overlap means a range
starting at an approved booking's end is allowed.

## 3. Enforce a fail-closed API boundary

**Files:** `src/features/calendar/api.ts`, `api.test.ts`.

The selected venue, date bounds and selected user are passed to a GET-only adapter.
`URLSearchParams` encodes the plus in SGT offsets correctly. Headers are exactly
`X-Dev-User-Id` and `X-Dev-Role`. The expected envelope is `{ bookings: [...] }`, with
booking/event/venue IDs, nullable requester/reviewer, status, times and `blocksSelection`.

HTTP/network/non-JSON failures reject. Unknown status, nonboolean or inconsistent
blocking flag, invalid IDs, another venue, malformed/non-SGT/rolled-over/reversed times,
malformed metadata and duplicate booking identity reject the **entire** snapshot.
There is no “drop bad rows and show the rest as free” fallback. Grid and inspection reads
have separate loading/error states. Neither describes a failed read as an empty result.

## 4. Keep calendar permission separate from catalogue permission

**Files:** `features/calendar/permissions.ts`, `types.ts`, `App.tsx`,
`components/Navigation.tsx`, `App.calendar.test.tsx`.

`/venue-availability` is a direct route in the existing custom router, with a dedicated
sidebar item. Event Coordinator, Venue Staff and Technical Support can inspect. The
backend's `Technical Support Staff` alias is also accepted by the calendar predicate.
Catalogue permissions remain unchanged: Technical Support does not acquire catalogue access.

Added `Attendee` to the frontend Role union, **not** to the live database. Both Attendee
and Event Organiser are denied on the direct route and have no calendar navigation item.
The real User Service switcher supplies identity; changing user remounts the calendar so
old identity data cannot leak through the new view. Missing identity fails closed too.

**This is DEV simulation, not authentication.** Headers are spoofable. The backend must
be started with `CALENDAR_DEV_MODE=true`; no production authorization is claimed.

## 5. Render one venue and inspect ranges accessibly

**Files:** `pages/VenueCalendarPage.tsx`, `features/calendar/calendar.css`, page tests.

Default view is Month, with Day/Week/Month, Previous/Next/Today, a collapsed Jump to date control and Refresh.
The dropdown uses real Venue Service results, including venues that would not be
requestable by booking-form rules. There is no venue search/filter or booking submission.

Month cells contain status markers and open Day on activation; this is navigation, not
selection of a whole day. Day/week display dated booking panels with full start/end
seconds. Approved is visually distinct and labelled **Unavailable**. Pending and Pending
Review both use **Pending confirmation**. All ranges remain inspectable; text accompanies colors.

Keyboard-operable labelled start/end controls replace dragging. Enter any positive range
within supported years and activate **Inspect range**. Overlapping any booking does not
disable inspection. Missing fields and invalid order produce explicit errors on submission.
An independent, GET-only fetch covers the requested range, even outside the visible window,
and returns overlap counts and intervals with “not a reservation”. Navigation, venue/view
changes and Refresh clear prior inspection; input edits invalidate in-flight results.

Each successful snapshot is tied to its venue/window/revision key. Old promises are
ignored on effect cleanup; a late success/error cannot replace the current request.
Catalogue outage/empty/invalid data is handled explicitly with Retry venues. Availability
outage is retried with Refresh. Two narrowly documented lint suppressions cover resetting
network-result state at request start; all other effects/dependencies are lint-clean.

## 6. Incremental TDD evidence (actual executions)

All commands below ran from `frontend/event-management-ui`; each implementation slice
was followed by its named test command. The following are observed results, not example output.
Initial imports for new modules necessarily failed discovery before those modules existed;
subsequent RED cycles were assertion failures. Additional coverage cases characterize
already-working behavior and are **not** mislabelled as new RED cycles.

| Slice / command suffix after `npm test --` | Observed RED | Observed GREEN |
|---|---|---|
| `src/features/calendar/dates.test.ts` | missing module | 1 passed (SGT/Monday week) |
| same, add day/month | expected day, received week | 2 passed |
| same, navigation/overlap/input | navigateDate missing | 3 passed |
| `src/features/calendar/permissions.test.ts` | missing module | 8 role cases passed |
| `src/features/calendar/api.test.ts` | missing module | 1 header/query case passed |
| same, fail-closed contract | 10 failed, 1 passed | 11 passed |
| `src/pages/VenueCalendarPage.test.tsx` | missing page | 3 passed |
| same, view/navigation | Month button absent | 4 passed |
| same, selection/loading/stale | 4 failed, 4 passed | 8 passed |
| same, catalogue retry/month markers | 2 failed, 8 passed | 10 passed |
| `src/App.calendar.test.tsx` | after test storage setup fix: 5 route/nav failures | 5 passed |
| dates, seconds precision | expected SGT seconds, received null | 4 passed |
| page, malformed catalogue | null row crashed rendering (1 failure) | 12 passed |
| API duplicate/metadata cases | 3 failed, 17 passed | 20 passed |

The first runner invocation failed because the script edit was refused by the file-write
safety check; it was corrected with a targeted patch. Node 26's global localStorage was
unavailable in jsdom tests, so route tests use an explicit in-memory stub; production
storage behavior was not changed. Those setup failures are not feature RED evidence.

## 7. Verification and acceptance mapping

Final recorded frontend run after independent-review corrections: **83 passed across 5 files**.
Calendar-scoped V8 coverage: **100% statements (184/184), branches (193/193),
functions (58/58), lines (166/166)**.
Scope is the new calendar modules and calendar page, not the whole pre-existing SPA.
Route/nav behavior is tested but existing App/Navigation coverage is not included in that
calendar metric. `npm run build` and `npm run lint` passed (no lint warnings).
A separate `TZ=America/Los_Angeles npm test` run passed all 83 tests; this verifies time
behavior is not accidentally Singapore-host-only. Keyboard activation of month/day
drilldown and labelled second-precision inputs is also covered. `git diff --check` passed.

Backend regression was actually rerun: `uv run pytest --cov=app --cov-branch
--cov-report=term-missing -q` → **120 passed, 1 skipped**, **100%** coverage (194 statements,
58 branches). The skip is the opt-in live smoke, not a failing test. Backend files remain
untouched by the frontend phase.

| AC / concern | Tests / implementation |
|---|---|
| AC1 dates, times, venue statuses for internal users | page all-three-role display tests; API status/time validation; selected-venue fetch tests |
| AC2 toggle day/week/month | dates tests; page default/view/navigation tests and month drilldown |
| AC3 visual indicators only; all ranges inspectable | independent range-fetch, approved/pending/outside-grid positive tests; exact overlap/dedup/API consistency retained |
| AC4 internal roles / external denial | permission matrix; real App direct-route/sidebar tests for five Role values |
| Unknown availability never treated free | malformed API/catalogue tests; isolated loading/error states; stale success/failure/unmount tests |
| Singapore time | date/input/query tests and non-SG host timezone run |

### Historical browser integration (overlap prohibition superseded by section 11)

Started local User (:5001), Venue (:5006), Availability (:5008), Vite (:5173); health checks
all returned 200. Flask processes used `PGOPTIONS='-c default_transaction_read_only=on'`.
No create/update/delete request or seed was made. Browser verified:

- real users and nine real venues loaded; current empty week rendered;
- Innovation Lab, **2026-10-20 09:00–13:00 SGT**, Approved marker; 09:30–10:30 inspection disabled;
- Conference Room A, **2026-10-15 08:00–10:00 SGT**, Pending marker; 08:30–09:30 inspect enabled,
  with “Pending requests overlap” and “not a reservation” summary;
- Month marker displayed in October 15 cell, clicking it selected Day;
- real Technical Support user saw calendar but no catalogue navigation;
- switching to real Event Organiser showed permission error and removed calendar;
- console reported **zero JavaScript errors**.

Visual review caught a six-plus-one week wrapping layout; adjusted week to seven columns
with horizontal overflow on narrow screens. Month uses seven columns; Day uses full width.
Native inputs retain OS locale presentation (e.g. DD/MM/YYYY) but are labelled SGT and
interpreted as SGT regardless of browser timezone. Attendee denial is isolated-test-only:
there was no live Attendee user and none was inserted. Mobile/touch and screen-reader
end-to-end audits were not performed.

**Observed setup issue:** opening `http://127.0.0.1:5173` while Availability's exact
`FRONTEND_ORIGIN` is `http://localhost:5173` blocks its CORS response. This correctly showed
unknown availability/disabled controls. Opening **http://localhost:5173** fixed the test;
backend CORS contract was not changed. No remaining functional blocker was found in the
scoped walkthrough.

## 8. Exact local prerequisites and commands

Run from repository root unless a subshell changes directory. The existing root `.env`
is present. At verification, User, Venue, Event and Availability service-local `.env` files
were absent. **Do not print or overwrite root `.env`**; it supplies server-only DATABASE_URL.
Full Compose can fail validation on missing unrelated env files, so use standalone commands.
No database URL/key belongs in a VITE variable. Install Node compatible with locked Vite and
Vitest (this run used Node 26), Python 3.12+ and uv. Each Flask command runs in its own terminal.

```sh
npm install
(cd frontend/event-management-ui && npm ci)
(cd services/user-service && uv sync --locked)
(cd services/venue-service && uv sync --locked)
(cd services/venue-availability-service && uv sync --locked)

# Terminal 1
(cd services/user-service && PGOPTIONS='-c default_transaction_read_only=on' uv run --env-file ../../.env flask --app app run --host 127.0.0.1 --port 5001)
# Terminal 2
(cd services/venue-service && PGOPTIONS='-c default_transaction_read_only=on' uv run --env-file ../../.env flask --app app run --host 127.0.0.1 --port 5006)
# Terminal 3: DEV opt-in is mandatory, and read-only DB mode prevents accidental writes.
(cd services/venue-availability-service && PGOPTIONS='-c default_transaction_read_only=on' CALENDAR_DEV_MODE=true uv run --env-file ../../.env flask --app app run --host 127.0.0.1 --port 5008)
# Terminal 4 (root script starts only frontend)
npm run dev:frontend
```

Open **http://localhost:5173/venue-availability**, not the 127.0.0.1 spelling unless every
service is explicitly configured for that exact origin. Confirm Vite actually uses 5173;
if it chooses another port, fix the port/origin mismatch rather than changing permissions.
Optional frontend URLs in a private `.env.local` in the UI directory:
`VITE_USER_SERVICE_URL`, `VITE_VENUE_SERVICE_URL`, `VITE_VENUE_AVAILABILITY_SERVICE_URL`.
Defaults are `http://localhost:5001`, `:5006`, `:5008` respectively.

```sh
(cd frontend/event-management-ui && npm test)
(cd frontend/event-management-ui && npm run test:coverage)
(cd frontend/event-management-ui && TZ=America/Los_Angeles npm test)
(cd frontend/event-management-ui && npm run build && npm run lint)
(cd services/venue-availability-service && uv run pytest --cov=app --cov-branch --cov-report=term-missing -q)
```

### Manual review walkthrough (existing data, read-only)

1. Choose any existing Event Coordinator. Open calendar; default Month and venue appear.
2. Select Innovation Lab, set Anchor date to **2026-10-20**, choose Day. Approved 09:00–13:00
   is labelled Unavailable. Open **Inspect time range**. Inspect 09:30–10:30: succeeds with
   one unavailable overlap. Inspect 13:00–13:01: succeeds with no overlapping records.
3. Choose Conference Room A, **2026-10-15**. Pending 08:00–10:00 remains selectable;
   inspect 08:30–09:30 and verify the no-reservation explanation.
4. Toggle Month then activate October 15. Day reopens without assuming whole-day availability.
5. Inspect a range outside the grid without navigating. Then change date/venue/view or
   Refresh: prior inspection disappears. A failed read shows an error, never empty availability;
   retry inspection separately from grid Refresh.
6. Choose Technical Support, then Venue Staff: both inspect; Technical Support still cannot
   open catalogue via its sidebar. Choose Event Organiser: direct route denies permission.
7. To test Attendee without modifying DB, run the isolated route/permission tests above.

Existing read-only SQL discovery also found Grand Ballroom Approved **2026-11-10 09:00–17:00**,
Rooftop Garden Pending **2026-11-22 10:00–16:00**, Auditorium Pending **2026-12-01 08:00–20:00**,
and Conference Room A Rejected **2026-09-30 09:00–12:00** (correctly excluded).
These are observations, not seeded by this implementation, and may later change.

## 9. Historical independent-review corrections (selection prohibition now superseded)

Only the calendar date/API/page files, their tests, and this document changed in this
correction pass. Existing uncommitted backend/frontend work was preserved; no commit,
push, service startup, backend contract change, or database write was performed.

### Exact API precision, not JavaScript milliseconds

1. Added page regression `microsecond approved tail blocks second-precision inspection`.
   Ran `npm test -- src/pages/VenueCalendarPage.test.tsx -t "microsecond approved"`:
   **RED**, Inspect range was incorrectly enabled when Approved ended at
   `2026-10-01T10:00:00.000001+08:00` and inspection began at `10:00:00`.
2. Added shared `timestampMicros` conversion in `dates.ts`: validate calendar fields,
   explicit ISO offsets and up to six fractional digits, then combine whole-second epoch
   milliseconds with the exact padded fraction using BigInt. Overlap now compares exact
   microseconds, without rounding either endpoint. Reran the page regression: **GREEN**.
3. Added API regression `valid sub-millisecond API interval preserves microseconds`.
   Ran `npm test -- src/features/calendar/api.test.ts -t "sub-millisecond"`: **RED**,
   valid `.000001` to `.000999` was rejected as an invalid availability response.
   Reused the exact parser for API timestamp validity and ordering: API suite **GREEN**.
   The API still requires the backend's seconds-bearing `+08:00` format; generic offset
   support in the pure helper does not loosen that contract.
4. Added characterization cases for equal/reversed microsecond ranges, exact adjacency,
   equivalent positive/negative offsets, pre-epoch fractions, invalid offsets/calendar
   fields and excess precision. Native inspection controls remain second-precision.

### Controlled anchor bounds

1. Added `unsupported anchor is rejected without replacing the safe window` and ran
   `npm test -- src/pages/VenueCalendarPage.test.tsx -t "unsupported anchor"`:
   **RED**, entering `10000-01-01` threw `RangeError: Invalid time value` during rendering.
2. Added documented supported anchors **0002-01-01 through 9998-12-31**, inclusive.
   Reserving one year at either end keeps Monday padding, the six-week month grid and
   exclusive API end bounds inside backend years 0001–9999, without limiting ordinary
   dates. Validation rejects malformed/rolled-over dates before changing the anchor.
   Invalid input shows an alert and retains the previous safe window. Invalid initial
   anchors show the alert and fall back to today's Singapore date.
3. Native date min/max, disabled Previous/Next at boundaries and disabled out-of-range
   month drilldown cells prevent crossing the supported range. The reproduction is
   **GREEN**. Added boundary tests for every view, initial fallback/recovery, four-digit
   generated windows, and early-year leap-day navigation.

### Request-lifecycle regressions and final verification

Added late-success and late-failure cases for both identity switching and venue A→B→A
(the first and current A have the same request key). They pass with existing cleanup;
no request-lifecycle refactor was needed. These and the additional boundary/precision
characterizations are not claimed as new failing-before-fix cycles. One initial fallback
recovery test attempted to change the input to today's already-selected date, so React
correctly emitted no change; the test was corrected to use the explicit Today action.

Actual final correction-pass commands from `frontend/event-management-ui`:

- `npm test`: **83 passed, 5 files**.
- `npm run test:coverage`: **83 passed**; calendar scope **100%** statements **184/184**,
  branches **193/193**, functions **58/58**, lines **166/166**.
- `TZ=America/Los_Angeles npm test`: **83 passed, 5 files**.
- `npm run build`: TypeScript and Vite production build passed.
- `npm run lint`: passed without reported warnings/errors.

Prior backend and live-browser evidence above remains historical; neither was rerun
for these isolated frontend corrections. No database access was needed.

## File map / review order

All `src/` paths below are under `frontend/event-management-ui/`.

1. `features/calendar/dates.ts` + tests — pure SGT/window/navigation/overlap rules.
2. `features/calendar/api.ts` + tests — GET/header contract and fail-closed validation.
3. `features/calendar/permissions.ts` + tests — independent internal-role predicate.
4. `pages/VenueCalendarPage.tsx` + tests — fetch lifecycle, view and read-only inspection.
5. `features/calendar/calendar.css` — scoped responsive/accessible presentation.
6. `App.tsx`, `components/Navigation.tsx`, `types.ts`, `App.calendar.test.tsx` — route,
   sidebar, switcher integration and Attendee type/denial.
7. `vitest.config.ts`, `src/test/setup.ts`, `package.json`, `package-lock.json`, `.gitignore`
   — reproducible test setup; coverage/build output excluded from git.
8. This document — steps/reasons/acceptance mapping/runbook and actual evidence.

## Deliberate limits

No production deployment, authentication, venue search/filter, booking submission,
maintenance/operational blocks, live DB writes or concurrency guarantees. Operational
blocks remain next sprint. A venue's catalogue operational status is not translated into
calendar blocking periods. Refresh is manual; there is no subscription/polling promise.
The UI uses a compact date-grid/day-agenda rather than a drag/time-grid library, so exact
selection is through native keyboard controls. This keeps scope and runtime dependencies
small and does not invent a booking policy.


## 10. Calendar visual redesign — October 1, 2026

### Scope and design

Preserved the pre-existing SCRUM-25 working tree. No merge/reset/stash, backend edit,
DB mutation, dependency addition, external font, commit or push. SHA-256 comparison
of all 25 captured Availability service files (excluding virtualenv, caches and generated
coverage) confirms identical content after regression tests. Date/API/permission modules
were not changed: microsecond overlap, anchor limits, SGT, fail-closed response validation,
and request-key/cleanup stale protection are retained.

The screenshot brief drives the presentation: light backdrop, rounded white grid,
hairline seven-column boundaries, centered small weekday/date labels, muted adjacent-month
dates, a blue today circle and discreet Approved/Pending pills. Existing sidebar/topbar
remain in place. Browser tab, sidebar, topbar and page region use **Venue availability
calendar**. Only the calendar route receives the new layout class/topbar spacing.

Month is now the default. The six-week/42-day contract is deliberately unchanged.
Today and previous/next arrows sit beside the month/year on the left; venue and segmented
Day/Week/Month controls sit on the right. Jump to date is a native details disclosure.
Read-only timezone/status legend remains compact. Instructions, DEV identity explanation,
window bounds and second-precision range inputs live in an explicitly opened, scrollable
nonmodal inspector drawer. Opening it overlays rather than reflows the calendar. Close
inspector dismisses it. That checkpoint validated only the grid snapshot; section 11 supersedes this restriction.

Each month cell displays at most one booking pill and an exact **+N more** count. Activating
that cell (including its overflow text) opens Day with all entries, rather than silently
hiding bookings. Day/week agendas remain scrollable and show full SGT timestamps. At narrow
widths the calendar keeps 100px columns with horizontal scrolling inside its container,
not unreadably compressed cells or page-wide horizontal overflow.

### Historical regression-first evidence (section 11 supersedes selection restrictions)

- Changed the default-view test from Week to Month and its expected 42-day window:
  observed RED (`aria-pressed=false`), then GREEN after changing only the default.
- Updated route/sidebar assertions to require Calendar and added document-title assertion:
  observed RED for old heading and old/empty tab title, then GREEN.
- Added explicit inspector open/inspect/close test: observed RED (toggle absent), then
  GREEN. Existing overlap/stale/loading/range tests now explicitly open the inspector;
  their safety assertions were retained, not deleted.
- Added busy-cell test with five approved entries: observed RED (no `+4 more`), then GREEN;
  confirms one preview pill and all five entries after Day drilldown.
- Added week-agenda characterization covering seven columns and pending semantics.
- Real Chromium empty-month layout assertion caught document height **780px** in a 768px
  viewport. Reserved space for empty-state text in the grid height calculation; rerun
  returned **768px**. This is a real browser-found/fixed layout regression.

### Actual final verification

- `npm test`: **86 passed**, 5 files.
- `npm run test:coverage`: **86 passed**; calendar-scoped **100%** statements **189/189**,
  branches **199/199**, functions **61/61**, lines **168/168**. Scope remains calendar
  modules/page, not the entire app. App route/nav/tab-title tests are additional.
- `TZ=America/Los_Angeles npm test`: **86 passed**, 5 files.
- `npm run build`: TypeScript + Vite production build passed.
- `npm run lint`: passed, no warnings/errors reported.
- Availability regression: `uv run pytest --cov=app --cov-branch --cov-report=term-missing -q`
  → **120 passed, 1 skipped**, **100%**, 194 statements / 58 branches. Opt-in live test
  remains skipped; browser integration used actual GET reads separately.

### Historical browser review and layout evidence (overlap prohibition superseded)

Existing 5001/5006/5008 processes could not be confirmed read-only, so they were not used
for the acceptance run or restarted. Started isolated User **5101**, Venue **5106**,
Availability **5108**, Vite **5175**, with the same documented root `.env`, explicit
`PGOPTIONS='-c default_transaction_read_only=on'`, `FRONTEND_ORIGIN=http://localhost:5175`,
and Availability `CALENDAR_DEV_MODE=true`. Vite URL overrides targeted these three services.
Health checks returned 200. No credentials were printed and no DB writes/seed calls were made.
The temporary services were stopped after verification; existing processes were preserved.

Real Chromium/Playwright loaded actual users and venues. Confirmed Conference Room A's
October 15 pending entry supports inspection and reports non-reservation, Innovation Lab's
October 20 Approved overlap disables inspection, month date drilldown, seven-day week,
Technical Support identity reset to default Month and Event Organiser denial. **Zero page
JavaScript errors**. Initial browser harness issues (native options are attached, not visible;
exact venue label needed explicit aria-label; waiting for asynchronous week replacement)
were corrected before recording successful evidence.

| Viewport | Document height | Month dates | Grid top → bottom | Cell dimensions |
|---|---:|---:|---|---|
| 1366 × 768 | 768 | 42 | 238 → 726px | ~152.57 × 81.33px |
| 1440 × 900 | 900 | 42 | 238 → 858px | ~163.14 × 103.33px |

All six rows fit without page scrolling at both desktop sizes, including the empty month
at 1366×768. Seven equal columns differ only by browser subpixel rounding. At 390px width,
body width is **390px**, scroll container client width **296px**, calendar scroll width
**700px**; horizontal overflow is contained and dates stay legible. Mobile naturally scrolls
vertically. No claim of a full screen-reader/touch-device audit.

Screenshots, visually inspected, live outside the repository under
`/Users/daphnetok/.hermes/cache/scratch/calendar-redesign/`:

- `month-1366x768.png`, `month-1440x900.png` — pending month, full grid.
- `inspector-1440x900.png` — open drawer and successful pending inspection.
- `approved-month-1366x768.png` — actual Approved marker.
- `week-1366x768.png` — seven-day agenda.
- `month-mobile-390x844.png` — contained mobile scrolling.
- `verify.py` — executed read-only browser review harness (Playwright supplied through
  `uv run --with playwright`, not added to the app's dependencies).

Review manually: open the calendar as staff; confirm Month, all dates and Calendar labels;
select a venue; use Jump to date; open/close Inspect time range; verify pending/approved
behavior; activate date or +N more to open Day; switch Week; narrow viewport and scroll
within the grid. Current independent inspection uses its own loading/error state; neither
view infers free time from an unavailable snapshot.


## 11. Revised acceptance: inspection is read-only, not booking selection

**Presentation superseded by section 12:** the text-only drawer result described and pictured
here is historical. Independent reads and safety rules remain; successful results now replace
the main calendar with selected-date-only Week/Month calendars.

### Current scope

- **AC1:** all three views label Approved as **Unavailable**, and Pending / Pending Review
  as **Pending confirmation**. Every month preview includes start–end SGT time; multi-day
  intervals include both dates. Day/week and inspector details retain full dated seconds.
  The 42-cell, Monday-first, viewport-fit month, one preview and exact +N more drilldown remain.
- **AC2:** Week has Mon–Sun dated headers; Day includes the actual full weekday.
- **AC3:** “blocked” means **visually blocked only**, not unselectable. Inspecting approved,
  pending, free or outside-visible-window ranges succeeds after a successful independent read.
  No selection restriction is inferred from `blocksSelection`. No booking is created/reserved.
- **AC4 unchanged:** the existing DEV user switcher, headers, allowed internal roles,
  direct-route denial and separate catalogue permission remain; this is not production auth.
- Inspector and Jump to date retain accessible native controls with clearer labels, helper
  text, spacing, focus states and a primary inspect action. Submit stays enabled for missing
  or reversed inputs, showing `Start date/time is required`, `End date/time is required`,
  `End date/time must be after start date/time`, or controlled invalid-date feedback.

### Independent range read and safety

Inspection uses the selected venue and identity and leaves the grid anchor unchanged.
It fetches complete date envelopes through the existing validated GET adapter, then applies
exact microsecond half-open overlap to the requested second-precision range. Cached grid
records are never used for inspection. A midnight end does not add the following day.
The API remains capped at **42 days per request**. Longer ranges within supported dates
**0002-01-01 through 9998-12-31** use sequential, at-most-42-day requests with no parallel
fan-out. Stable IDs deduplicate spanning bookings; differing fields for a repeated ID reject
the entire inspection rather than silently choosing a version. Any chunk failure rejects
all results: no partial counts/details and no inference of free time. Very long spans can
be slow; no overall product duration limit was introduced. Reads are snapshots, not an
atomic multi-request database transaction or a concurrency guarantee.

An incrementing request generation invalidates results on input edits, venue/identity,
navigation/view, refresh, and unmount. Stale success/failure cannot overwrite a newer range
(including A→B→A). Stale chunks stop before another request. Grid loading/errors and inspector
loading/errors are isolated; a successful independent retry can be shown even if the grid
read failed. Editing clears old results/errors/loading and permits a replacement request.

Removed/replaced obsolete tests expecting approved overlap, microsecond approved tails,
or outside-grid ranges to disable inspection. Positive tests now count and display them.
**Retained unchanged:** pure interval/microsecond utility tests, API status/blocksSelection
consistency and fail-closed validation, backend read cap and all booking-write conflict rules.
Operational/maintenance blocks remain deferred. No dependencies, env/Compose settings,
backend source, live data, production auth, commits or pushes changed in this revision.

### Actual incremental evidence

Baseline `npm test`: **86 passed**. Incremental assertion RED→GREEN runs:

1. Microsecond approved-tail inspection: no status (disabled old button) → one unavailable.
2. Outside-grid request: no status (old window restriction) → correct independent query/count.
3. Missing/reversed fields: generic message → explicit required/order messages.
4. Long range: one oversized query → sequential 42-day chunks with spanning-ID deduplication.
5. Conflicting duplicate across chunks: no error → entire inspection rejected.
6. All-view labels/week headings: old Pending text → new label/time and dated weekday headers.
7. Overnight month interval: missing full dates → both dates displayed.

Additional characterization verifies stale success/failure and range A→B→A, venue/identity/
unmount, midnight envelopes, independent retry, no partial chunk results, invalid years,
all three API statuses across all views and inspection. Existing busy more-count, keyboard,
role, catalogue/API and exact microsecond tests remain.

### Live browser and visual verification

Started isolated User :5101, Venue :5106, Availability :5108 and Vite :5175, with root env
read privately, explicit `PGOPTIONS='-c default_transaction_read_only=on'`, matching
`FRONTEND_ORIGIN=http://localhost:5175`, and existing DEV mode. Health checks all 200.
No existing service was restarted. Browser observed **zero page errors and zero non-GET/
OPTIONS requests**. Real records verified:

- Conference Room A October 15, 08:00–10:00: Pending confirmation with complete month interval;
  required-field errors, then successful one-pending inspection.
- Grand Ballroom November 10, 09:00–17:00: approved inspection 10:00–11:00 succeeds while
  the grid stays on October 1 (outside the grid end November 9).
- Grand Ballroom September 1–December 1: three real sequential chunks, complete one-unavailable
  result; never a partial result.
- Innovation Lab October 20, 09:00–13:00: Unavailable month label, Tuesday Day header,
  Mon–Sun Week headers. Technical Support switch and Event Organiser denial remain.

| Desktop viewport | Document height | Dates | Grid top–bottom | Column widths |
|---|---:|---:|---|---|
| 1366×768 | 768 | 42 | 238–726px | 152.5625–152.578125px |
| 1440×900 | 900 | 42 | 238–858px | 163.140625px |

Empty and populated month fit without page scrolling. Screenshots were visually inspected:
label/time pills wrap rather than hiding the interval; labelled date/time fields and Jump
popover are complete and legible. Inspector scrolls internally on smaller heights.
Artifacts outside Git: `/Users/daphnetok/.hermes/cache/scratch/calendar-ac-revision/`:
`verify.py`, `month-1366x768.png`, `month-1440x900.png`, `jump-to-date.png`,
`inspector-pending.png`, `inspector-approved-outside-grid.png`, `inspector-multichunk.png`,
`approved-month.png`, `week.png`. Native picker presentation depends on OS/browser locale;
times are always interpreted as SGT. No full mobile/touch/screen-reader audit is claimed.
The four isolated verification processes were stopped afterward; existing services were preserved.

### Final executed checks for this revision

- `npm run test:coverage`: **105 passed, 5 files**; calendar-scoped coverage **100%**:
  statements **233/233**, branches **211/211**, functions **68/68**, lines **200/200**.
  Scope remains calendar modules/page, not the entire pre-existing SPA.
- `TZ=America/Los_Angeles npm test`: **105 passed**, 5 files.
- `npm run build`: TypeScript and Vite production build passed.
- `npm run lint`: passed, no reported warnings/errors.
- Availability `uv run pytest --cov=app --cov-branch --cov-report=term-missing -q`:
  **120 passed, 1 skipped**, **100%** (194 statements, 58 branches). The opt-in live pytest
  remains skipped; actual read-only browser/API checks are recorded separately above.
- `git diff --check`: passed. Only this document, `VenueCalendarPage.tsx`, its test file,
  and `features/calendar/calendar.css` were edited in the repository during this revision.
  All pre-existing uncommitted work was preserved. No commit or push.

## 12. Clarified inspector RESULT calendar — October 1, 2026

The inspector is a query form, not the result surface. Successful Inspect range closes the
form and replaces the normal calendar with a full-width **Inspected range · Week/Month**
calendar, exact requested SGT start/end header and overlap counts. The old summary is retained
only as supplementary accessible status, never as the sole result. The normal current-month
grid/agenda and its empty/loading message are not rendered alongside results. Normal browse
controls remain explicit exits and are not marked selected while showing an inspected result.

### Exact semantics

- **Week** when elapsed end minus start is **<= 7 * 24 hours**, otherwise **Month**.
  Inputs are interpreted in SGT, independent of host timezone. A seven-day nonmidnight range
  can intersect eight dates: all eight remain visible in a wrapping, maximum-seven-column
  week layout. Short weeks expand selected columns to use available width.
- Start is inclusive and end exclusive. An end at midnight excludes that date; an end after
  midnight includes it. Only intersecting dates receive cells. Month mode has separate named
  month sections, Monday-first weekday alignment and blank spacers, never adjacent date cells.
- Occupied intervals are clipped to both the requested interval and the displayed day.
  Full dated timestamps retain API microseconds; a clipping note identifies shortened
  intervals. Approved is **Unavailable**, Pending/Pending Review is **Pending confirmation**.
  All booked ranges remain inspectable; inspection never reserves time.
- Independent exact-range date-envelope reads still use sequential <=42-day chunks,
  stable-ID deduplication and exact microsecond half-open filtering. Result pagination
  makes **no requests** and never fetches unrelated dates. Errors reject the complete read.
- **Back to calendar** clears inspection, restores Month on the previous browse anchor and
  preserves the venue. Edits, navigation/mode, refresh, venue/identity and unmount invalidate
  pending results via the existing generation guard. Independent inspection can succeed
  despite a failed normal-grid read; that failure remains explicitly reported.
- Up to twelve month sections scroll naturally. Longer results use explicitly labelled
  twelve-month pages with a visible `Months X–Y of N` count and Earlier/Later controls.
  Only the current page's dates/DOM are allocated (at most twelve months), not every day of
  a potentially millennia-long range. All selected dates remain reachable. Complete fetches
  still finish before any result is displayed; exceptionally long requests can be slow and
  stored booking rows are not capped. Multi-chunk reads are not an atomic snapshot.

### Regression-first implementation and checks

1. Added component test requiring outside-view selected-only Week region and return control;
   observed RED (region absent; old 42-date grid plus text-only drawer), then GREEN.
2. Added exact seven-day/one-second-over threshold, exclusive-midnight and multi-month tests;
   observed RED for missing Month results, then GREEN with aligned separate month sections.
3. Added visible Approved/Pending clipped timestamps, retained microseconds and automatic
   drawer dismissal; observed RED for absent interval labels, then GREEN.
4. Added bounded long-range pagination test; observed RED (26 sections instead of 12), then
   GREEN with all final dates reachable and exclusive endpoint excluded.
5. Browser review found short Week columns used only two-sevenths of the available width.
   Added failing width/normal-view-selection regression, expanded columns, reran GREEN and
   recaptured screenshots. Existing text-only-result assertions were updated, not safety tests.

Final actual commands:

- `npm run test:coverage`: **111 passed, 6 files**. Calendar scope (including new
  InspectionCalendar.tsx) **100%** statements **272/272**, branches **255/255**, functions
  **81/81**, lines **232/232**. This is not whole-SPA coverage; no exclusions added.
- `TZ=America/Los_Angeles npm test`: **111 passed**, 6 files.
- `npm run build`: TypeScript/Vite production build passed; `npm run lint`: passed.
- Availability `uv run pytest --cov=app --cov-branch --cov-report=term-missing -q`:
  **120 passed, 1 skipped**, **100%** (194 statements / 58 branches). Opt-in live pytest skipped.
- Existing independent fetch/chunk failures, missing-field/order validation, stale response,
  identity/venue reset, microsecond tail, permission and normal Month/Week/Day tests pass.

### Actual read-only browser verification

Isolated User :5201, Venue :5206, Availability :5208 and Vite :5275 all returned healthy.
Service processes used root env privately, `PGOPTIONS='-c default_transaction_read_only=on'`,
matching frontend origin and DEV mode. Real data only: no fixtures/credentials invented, no
service/backend/auth edits or DB writes. All four temporary process groups stopped in finally.
Existing processes were preserved. Chromium at 1440×900 verified **1144px-wide** results:

- Grand Ballroom **November 10 10:00–November 12 00:00, 2026**: Week with only Nov 10/11,
  one Unavailable interval clipped to Nov 10 10:00–17:00, while browse anchor stayed Oct 1.
- Grand Ballroom **November 25 09:00–December 5 00:00, 2026**: Month with only Nov 25–30
  and Dec 1–4, separate aligned sections, no December 5 or unrelated current-month grid.
- Conference Room A **October 15 08:30–09:30, 2026**: one full-width Week date, Pending
  confirmation clipped to that exact interval. Return and venue reset restore 42-date Month.
- **Zero page JavaScript errors; zero non-GET/OPTIONS requests.** Each inspection generated
  only its selected date-envelope query. No write/seed request was made.

Artifacts outside Git: `/Users/daphnetok/.hermes/cache/scratch/calendar-inspection-result/`:
`verify.py`, `verification.log`, `week-outside-view.png`,
`month-multiple-outside-view.png`, `week-pending.png`. Screenshots visually inspected; the
final short Week uses full-width columns rather than the initial narrow-column layout.
No full mobile/touch/screen-reader audit or enormous live-range load test is claimed.

Files changed in this pass: page + page tests, calendar CSS, this document; added
`features/calendar/InspectionCalendar.tsx` and its test. No dependencies, backend/auth,
Compose/env, commits or pushes changed. Pre-existing uncommitted work preserved.

## 13. Combined venue selection and weekday strips — October 1, 2026

### Current behavior (supersedes the single-venue selector above)

- A native disclosure contains labelled checkboxes for multiple venues. Its summary shows
  selected count and names; the expanded list remains keyboard usable. The first catalogue
  venue remains the initial single selection. Removing every selection shows **Choose at
  least one venue**, removes obsolete results/errors and disables inspection. There is no
  fallback to all venues and no availability request for an empty set.
- Normal Month/Week/Day combine only selected venues. Every displayed booking identifies
  its venue by name. Month retains one compact preview, exact combined **+N more**, and Day
  drilldown with every entry. Return from inspection preserves the selected set.
- Inspection independently reads every selected venue for its selected date envelope,
  including ranges outside the browse window. All selected names appear in the result
  summary. Every response still passes the existing **single-venue** validator: another
  selected venue's record is not accepted inside the wrong response. Status/blocking,
  timestamps, microseconds, duplicate validation and backend permissions are unchanged.
- Normal reads aggregate per-venue requests and publish only after all succeed. Inspection
  reads venues/chunks sequentially, each chunk at most 42 days. Deduplication and React keys
  are composite **venue ID + booking ID**, retaining equal booking IDs in different venues.
  Any failed venue/chunk rejects the complete result; no partial availability is published.
- AbortController signals reach the GET adapter. Selected-set/window/identity changes abort
  obsolete grid reads. Inspection edits, venue/identity changes, navigation, refresh and
  unmount abort its transport and invalidate its generation. Generation/active guards also
  reject stale success/failure when a mock or transport ignores abort; no obsolete next
  chunk or next venue is started.
- Week results now have a separate centered, small uppercase weekday strip and date-only
  body headings. Labels follow actual selected dates, not a forced Monday start. Eight
  intersecting dates wrap as seven plus one with a matching strip for each group. Normal
  Week/Day use the same separated treatment. Existing <=7 elapsed days Week, >7 days Month,
  midnight-exclusive boundaries, microsecond clipping, selected-only month cells and
  twelve-month result pagination are preserved.

### Incremental regression evidence

Baseline: **111 passed in 6 files** before edits. Observed failing tests before implementing:

1. Selected Week strip/date separation (missing strip), then GREEN.
2. Add/remove multiple native checkbox selections including zero and named same-ID entries
   (checkbox absent), then GREEN.
3. Independent multi-venue outside-view inspection (one unavailable instead of two), then GREEN.
4. Obsolete multi-venue chain cancellation (AbortSignal missing), then GREEN.
5. Normal Week/Day strips and eight-date wrapping (strips missing/misaligned), then GREEN.
6. Zero selection clears obsolete grid error (old alert retained), then GREEN.

Additional characterization covers both venue failures, selected-set A+B→A→A+B stale success
and failure, inspection set-change cancellation, selected-only requests, native keyboard
activation, multi-venue chunk boundaries/deduplication, wrong-venue UUID rejection, combined
month overflow and complete drilldown. Old single-select interaction tests were migrated to
checkboxes without removing their identity/stale/permissions/microsecond assertions.

### Final executed checks

- `npm run test:coverage`: **128 passed, 6 files**. Calendar-scoped coverage **100%**:
  statements **292/292**, branches **266/266**, functions **90/90**, lines **243/243**.
  No coverage exclusions added; this remains calendar scope, not the whole SPA.
- `TZ=America/Los_Angeles npm test`: **128 passed, 6 files**.
- `npm run build`: TypeScript + Vite production build passed.
- `npm run lint`: passed with no reported warnings/errors.
- Availability `uv run pytest --cov=app --cov-branch --cov-report=term-missing -q`:
  **120 passed, 1 skipped**, **100%** (194 statements / 58 branches). Opt-in live pytest
  remains skipped; real browser/API reads are separately verified below.
- `git diff --check`: passed. No commits/pushes, merge/fetch, backend edits, catalogue/auth
  permission changes or live writes. All pre-existing dirty work was preserved.

### Actual read-only Chromium verification

Isolated User :5201, Venue :5206, Availability :5208 and Vite :5275 used existing root env,
`PGOPTIONS='-c default_transaction_read_only=on'`, exact matching frontend origin and DEV
mode. All health checks returned 200. The harness stopped only its four temporary process
 groups in finally; existing processes were not touched. There were **zero page JavaScript
errors and zero non-GET/OPTIONS browser requests**. No fake browser responses or data seeds.

- Conference Room A + Innovation Lab October month shows both named venues; all 42 dates fit.
- October 15 08:30–October 21 00:00 inspection: only Oct 15–20, strip **THU FRI SAT SUN MON TUE**,
  one pending Conference Room A interval and one unavailable Innovation Lab interval.
- Grand Ballroom + Rooftop Garden November 10 10:00–November 23 00:00 inspection while browse
  anchor remains October 1: only Nov 10–22, one named unavailable and one named pending record.
  Each inspection issued exactly one selected-envelope GET per selected venue in these cases.
- Return preserves selection; zero-selection prompt/disabled inspection verified. Native
  disclosure Enter and checkbox Space activation verified in real Chromium.
- Empty February month fits 1366×768; normal Week displays its separate weekday strip.

| Desktop viewport | Document height | Dates | Grid top–bottom | Seven column widths |
|---|---:|---:|---|---|
| 1366×768 | 768 | 42 | 242–730px | 152.5625–152.578125px |
| 1440×900 | 900 | 42 | 242–862px | 163.140625px |

Screenshots visually inspected. Evidence outside Git:
`/Users/daphnetok/.hermes/cache/scratch/calendar-multi-venue/`:
`verify.py`, `verification.log`, `month-1366x768.png`, `month-1440x900.png`,
`week-multi-venue.png`, `month-outside-view-multi-venue.png`,
`empty-month-1366x768.png`, `venue-checkbox-picker.png`, `normal-week.png`.

Changed repository paths in this pass: `docs/calendar-implementation.md`;
`frontend/event-management-ui/src/pages/VenueCalendarPage.tsx` and its test;
`src/features/calendar/InspectionCalendar.tsx` and its test, `api.ts` and its test,
`calendar.css` (all latter src paths under the same frontend). Updated the reusable
`singapore-calendar-frontend` skill outside the repository.

Limits: selected-venue/chunk reads are not an atomic database snapshot; very long ranges
still require complete sequential reads before results, with no new product duration cap.
No full mobile/touch/screen-reader audit or large-catalogue load benchmark is claimed.



## 14. Bulk venue controls and final acceptance audit — October 1, 2026

This section is the current verification checkpoint; earlier numeric results and single-venue /
blocked-selection descriptions are historical, superseded by sections 11–14.

### Bulk actions and regression evidence

The venue checkbox disclosure now contains accessible native **Select all** and **Deselect all**
`type="button"` controls. Select all is disabled when all catalogue venues are selected (including
an empty catalogue); Deselect all is disabled at zero. Disabled actions issue no requests.
Both buttons use the same `changeVenues` path as checkboxes: clear inputs/results/errors, abort
obsolete grid/inspection transport, invalidate inspection generations, and update the selected
set without closing the disclosure. Zero selection remains explicit, never defaults to all,
issues no availability requests, and disables inspection and its fields.

TDD: the new single/partial/none → all and all → none interaction test first failed because
Select all did not exist, then passed after the minimal shared-handler implementation. Five
additional regression cases characterize both actions cancelling grid and sequential inspection
reads, ignoring late results and preventing later chunks, clearing completed inspection and
inputs, and empty-catalogue disabled states. Six new cases bring the suite from 128 to 134.
No existing assertion was removed or weakened.

### Full test audit and current matrix

Read all six frontend test files and all five backend test modules plus fixtures and source.
No stale assertions still forbid Approved overlap or require inspection inside the browse
window. Positive approved/microsecond-tail and outside-window tests are retained. Current labels
are Unavailable and Pending confirmation. Remaining single-venue adapter tests are intentional:
each response must match its requested venue even when multiple venues are selected. Initial
single selection is also intentional, not a single-venue-only product assumption. Renamed one
misleading page-test title to explicitly describe independent inspection remaining enabled
while stale grid rows are ignored; its assertions were already correct and are unchanged.
Retained exact half-open/microsecond utilities, API validation, SQL overlap/status predicates,
42-day **per-request** limits, and all booking-write/approval conflict regression tests.

| Frontend file (under `frontend/event-management-ui/src/`) | Passed | Categories |
|---|---:|---|
| `pages/VenueCalendarPage.test.tsx` | 70 | Month default; Day/Week/Month navigation and bounds; bulk and individual multi-select; zero/empty catalogue; all three staff roles; external denial; labels/overnight times; overflow/day drilldown; native controls and keyboard; independent ranges; sequential 42-day chunks; deduplication; aggregate failure; stale transport/generation cancellation; resets; selected-only results, threshold, clipping and return |
| `features/calendar/api.test.ts` | 25 | GET identity/SGT query, AbortSignal, HTTP/network/non-JSON failures, complete response validation, foreign venues, UUIDs, status/blocking consistency, duplicates/metadata, microseconds |
| `features/calendar/dates.test.ts` | 23 | SGT independent of host TZ, Monday windows, month-end/leap/year navigation, native input seconds, invalid dates, four-digit supported bounds, exact offset/microsecond half-open overlap |
| `features/calendar/permissions.test.ts` | 8 | Internal roles and Technical Support Staff alias allowed; external/unknown/empty denied |
| `features/calendar/InspectionCalendar.test.tsx` | 3 | Separate ordered weekday strip, eight-date seven-plus-one wrapping, bounded twelve-month pagination with all dates reachable |
| `App.calendar.test.tsx` | 5 | Each business role's direct route/navigation and calendar document title |
| **Total** | **134** | **6 files, no skips or failures** |

| Backend file (under `services/venue-availability-service/tests/`) | Passed | Skipped | Categories |
|---|---:|---:|---|
| `test_calendar.py` | 78 | 0 | DEV gate/identity/roles, query validation, exact parameter multiplicity, offset→SGT conversion, interval/cap, visible ranges, status/time serialization, half-open overlap, fail-closed malformed rows, CORS and sanitized database failures |
| `test_calendar_sql.py` | 18 | 0 | Actual read predicate against in-memory SQLite: statuses, overlap, malformed/NULL candidates, venue isolation, excluded cancelled data; not a PostgreSQL driver test |
| `test_bookings.py` | 9 | 0 | Health, GET, create/approve/reject, existing overlap conflicts and 404/order behavior |
| `test_write_regressions.py` | 15 | 0 | Unchanged write/decision validation, DB-unconfigured behavior, naive timestamp/Pending Review output, no DEV gate on existing writes, Approved-only conflict SQL |
| `test_live_calendar.py` | 0 | 1 | Explicit opt-in read-only PostgreSQL smoke, skipped in normal suite |
| **Total** | **120** | **1** | **No failures** |

Actual verification commands/results:

- `npm run test:coverage`: **134 passed**, 6 files; **100% statements 295/295,
  branches 266/266, functions 93/93, lines 245/245**. Scope is calendar feature modules
  and VenueCalendarPage, excluding test files; not whole-SPA coverage. No exclusions added.
- `TZ=America/Los_Angeles npm test`: **134 passed**, 6 files.
- `npm run build`: TypeScript + Vite production build passed. `npm run lint`: passed.
- Additional JSON-report run after the test-title correction: **134 passed**, no failures.
- `uv run pytest --cov=app --cov-branch --cov-report=term-missing ... -q`:
  **120 passed, 1 skipped**, **100%**, 194 statements / 58 branches, no missing/partial branches.
  Per source: `app/__init__.py` 106 statements / 32 branches; `app/calendar.py` 12 / 4;
  `app/models.py` 76 / 22. This covers the availability service app, not other services.
- `git diff --check`: passed.

### Read-only browser evidence and caveat

Read the prior `scratch/calendar-multi-venue/verify.py` before adapting it to `verify-bulk.py`.
Started isolated User :5201, Venue :5206, Availability :5208, Vite :5275 with existing root env,
explicit `PGOPTIONS='-c default_transaction_read_only=on'`, matching frontend origin, DEV mode;
all four health checks passed. No production auth changes, data seeds or live writes.

Real Chromium verified all **9** live catalogue checkboxes selected by keyboard Enter on Select
all, Space on Deselect all, zero-selection prompt/disabled inspection, **zero requests while
empty**, reselection, disabled states, and disclosure remaining open. Screenshot confirms both
buttons legible inside the scrollable picker. It reran actual named two-venue Week and outside-
view Month inspections: each returned one unavailable and one pending interval and exactly
one selected-envelope GET per venue. Week dates Oct 15–20; Month dates Nov 10–22. Return,
normal weekday strips, checkbox keyboard interaction and empty-month fit also passed.
Populated 42-date grid fits 1366×768 (242–730px) and 1440×900 (242–862px); document heights
match viewport heights. **Zero page JavaScript errors and zero non-GET/OPTIONS requests.**
All four owned temporary process groups stopped in `finally`; existing services untouched.

The first attempt passed bulk actions but the old harness then rapidly unticked seven venues,
triggering many overlapping aggregate reads and live HTTP 503 responses. The UI correctly
failed closed. The harness was changed to Deselect all once, then select the desired venues
while waiting for each read; the entire rerun passed. The cause of those transient 503s was
not established; do not claim server load/cancellation capacity has been proven. Browser
AbortController cancellation does not guarantee cancellation of already-running server SQL.

Evidence outside Git under `/Users/daphnetok/.hermes/cache/scratch/calendar-multi-venue/`:
`verify-bulk.py`, `verification-bulk.log`, `bulk-venue-picker.png`, refreshed Week/Month/layout
screenshots; `frontend-final.json`, `backend-final.xml`, `backend-coverage-final.json`.

### Current AC assessment / complete PR inventory

- **AC1 — met in the accepted DEV scope:** Event Coordinator, Venue Staff and Technical Support
  can view dates, SGT times, booking status and venue names. Read endpoint is bounded,
  parameterized and service-owned; requires one venue UUID and exactly one pair of valid
  ordered bounds, at most 42 days. Explicit offsets normalize to SGT; naive read inputs are
  interpreted as SGT. Responses include Approved/Pending/Pending Review with +08:00 timestamps
  and blocksSelection; Rejected/Cancelled are excluded. Malformed candidates and database
  errors fail closed with no partial availability. Frontend validates the entire envelope.
- **AC2 — met:** default Month, explicit Day/Week/Month toggles, Today/previous/next/jump,
  Monday-first six-week month, separated weekday strips, one preview with exact +N more and
  complete Day drilldown. Multi-venue checkbox and bulk selection combine named entries.
- **AC3 — met under clarified visual-only meaning:** unavailable booking cards/pills are
  visually distinct and carry start/end times; pending is distinct and non-reserving.
  This is **not a proportional hourly shaded time grid**. All valid ranges, including
  Approved overlaps, remain inspectable. There is no disabled-selection acceptance criterion.
  Selected-range results use Week for <=7 elapsed days, otherwise separate aligned Month
  sections, only intersecting dates, midnight-exclusive end, exact range/day clipping including
  microseconds, and explicit twelve-month pages for long results. No booking is modified.
- **AC4 — met only as the previously accepted DEV simulation:** hidden external navigation
  plus direct-route permission errors and backend 403 for Event Organiser/Attendee; missing
  identity 401, DEV mode disabled by default/503, exact allowed-role matching and CORS origin.
  `X-Dev-User-Id` / `X-Dev-Role` are **spoofable client headers**, not authenticated identity.
  This does not deliver production authorization; no production-auth work is claimed.

Other retained safety/UX: catalogue retry/empty/malformed feedback; zero selection; independent
grid/inspection loading and retry; no stale success/failure after selection, input, navigation,
refresh, identity or unmount; transport abort plus generation guards; per-venue response
validation; sequential <=42-day inspection chunks; venue+booking-ID deduplication; conflicting
duplicates or any venue/chunk failure reject everything; Back to calendar preserves the set
and browse anchor. Multi-request reads are not atomic snapshots; very long ranges have no new
product duration cap and finish reading before results. Maintenance blocks, production auth,
full touch/screen-reader audit and large-catalogue capacity testing remain out of scope.

This pass modified only `VenueCalendarPage.tsx`, `VenueCalendarPage.test.tsx` and this document.
All earlier uncommitted frontend/backend/config/documentation work was preserved. No commits,
pushes, merges, live database writes or changes to backend write-conflict semantics.
