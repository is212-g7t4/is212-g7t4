# SCRUM-170 frontend: local startup and verification

## Scope and prerequisites

Continues `scrum-170-backend-review.md` after frontend authorization. The existing venue details page now contains the Venue Staff-only expandable closure form and recorded-closure list. This is **recording only**, not closure enforcement: no booking, hold, event, catalogue status, notification or calendar mutation is added.

Use an explicitly approved database configuration. The commands below load the repository-root `.env`; with the current shared Supabase configuration, saved closures are real shared records. Existing Venue and User rows must exist, and the selected User must have the exact `Venue Staff` role. Do not use synthetic test IDs in a live save. Never commit `.env` or credentials.

Both closure services must explicitly opt in with `VENUE_CLOSURE_DEV_MODE=true`. The UI sends the selected user's UUID as `X-Dev-User-Id` and role as `X-Dev-Role`. These are **spoofable local development headers, not authentication**. Do not expose enabled services publicly.

## Minimal host startup

Start each command in a separate terminal **from the repository root**, using the already-approved repository-root `.env` / DATABASE_URL configuration. Run `uv sync` in each service first if dependencies are not installed. No database configuration is copied by these instructions.

```sh
cd services/user-service
FRONTEND_ORIGIN=http://localhost:5174 \
uv run --env-file ../../.env flask --app app run --host 127.0.0.1 --port 5001
```

```sh
cd services/venue-service
FRONTEND_ORIGIN=http://localhost:5174 \
uv run --env-file ../../.env flask --app app run --host 127.0.0.1 --port 5006
```

```sh
cd services/venue-availability-service
FRONTEND_ORIGIN=http://localhost:5174 VENUE_CLOSURE_DEV_MODE=true \
uv run --env-file ../../.env flask --app app run --host 127.0.0.1 --port 5008
```

```sh
cd services/venue-booking-service
FRONTEND_ORIGIN=http://localhost:5174 VENUE_CLOSURE_DEV_MODE=true \
VENUE_SERVICE_URL=http://127.0.0.1:5006 \
VENUE_AVAILABILITY_SERVICE_URL=http://127.0.0.1:5008 \
uv run --env-file ../../.env flask --app app run --host 127.0.0.1 --port 5007
```

Frontend, also initially from repository root:

```sh
cd frontend/event-management-ui
npm ci
VITE_USER_SERVICE_URL=http://127.0.0.1:5001 \
VITE_VENUE_SERVICE_URL=http://127.0.0.1:5006 \
VITE_VENUE_BOOKING_SERVICE_URL=http://127.0.0.1:5007 \
VITE_VENUE_AVAILABILITY_SERVICE_URL=http://127.0.0.1:5008 \
npm run dev
```

Open `http://localhost:5174/venues`, not an unrelated overview/event route that needs additional services. Vite is strict-port pinned to 5174. Stop only the processes you started with Ctrl-C. The root `npm run dev:frontend` is an alternative frontend command; `npm run dev` at the repository root starts Docker too, so is not the isolated frontend command above.

### Direct endpoints and CORS

There is no gateway or Vite API proxy. Closure POST and GET list go directly to `VITE_VENUE_BOOKING_SERVICE_URL` (fallback `http://localhost:5007`), at `/venue-closures`. The list supplies `venueId`, `limit=50` and, on Load more, the opaque cursor. The composite writes through the availability service. Venue details/catalogue use port 5006; existing hold reads use port 5008; user selection uses port 5001.

Every service's `FRONTEND_ORIGIN` must match the actual browser origin. If overriding Vite's port, change all four service origins too. Closure preflight must permit `Content-Type, X-Dev-User-Id, X-Dev-Role`; both backends already implement this contract. CORS does not replace authentication. A successful curl alone does not prove browser CORS works.

## Manual acceptance path

1. Select an existing **Venue Staff** user with the **Select active user** control in the top bar. User Service must be working: fallback Event Organiser identity will not show the closure panel.
2. From **Venues**, select **View details** for any venue, including On Hold or Maintenance.
3. Expand **Record temporary closure** on the same page. Venue name is read-only; both date inputs are interpreted in Singapore time, regardless of the browser timezone.
4. Enter start, end and reason. A past start is allowed; end must be strictly after start and now. Whitespace-only reasons are rejected; nonblank reasons are trimmed before POST.
5. Save. The button disables duplicate submissions. Only a valid persisted 201 response produces **Closure recorded.** The UI then independently refreshes the real list. List failure is shown separately from save success.
6. Inspect interval, reason, creator, creation time and closure ID. Dates explicitly show SGT. Use **Load more closures** until absent to reach all pages. **Refresh closures** restarts from the first page (keyset reads are not a snapshot).
7. If a response is lost, do not blindly retry: the UI preserves inputs and warns that the save may have committed. Refresh and follow every list page, comparing interval, reason, creator and creation time; reconcile uncertain outcomes with staff. There is no idempotency guarantee or automatic POST retry.
8. Switch venue, selected user or role: pending requests are aborted and stale replies ignored; old drafts/data/errors are removed. Other roles never fetch closure rows. Backend authorization remains independently required.
9. Confirm venue operating status and existing hold/booking/event records did not change. Enforcement belongs to separate tickets.

## Initial frontend verification (before visual refinement)

All commands below ran in `frontend/event-management-ui`, without backend/database access:

| Command | Actual result |
| --- | --- |
| `npm test` | 371 passed across 31 files. |
| `npm run test:coverage` | 371 passed across 31 files. New closure API and panel: 100% statements, branches, functions and lines. Configured coverage scope overall: 98.71% statements, 97.27% branches, 97.15% functions, 98.83% lines; this is not whole-app coverage. |
| `TZ=America/Los_Angeles npm test -- src/features/venue/venueClosures.test.ts src/pages/VenueDetailPage.closures.test.tsx` | 33 passed. |
| `npm run build` | TypeScript and Vite production build passed. |
| `npm run lint` | Passed with no warnings. |
| `npm run test:e2e` | 27 Chromium mocked-API tests passed; the two closure tests use America/Los_Angeles timezone. Unmocked service calls fail tests. |
| `git diff --check` | Passed. |

TDD evidence: observed missing closure API/form failures, 16 API validation/transport/list failures, four pagination/cancellation UI failures, and the polling regression before production fixes. Browser checks caught a textarea implicit-label exact matching issue and the inherited hold-grid layout; explicit reason labeling and scoped closure form layout fixed both. Final screenshots were visually inspected for overlap/readability. Initial build failed because installed dependencies lacked Playwright; `npm ci` restored lockfile dependencies without changing the manifests.

### Acceptance-to-test map

- `src/features/venue/venueClosures.test.ts`: exact body/offsets/headers, ongoing timing, invalid/missing/ordered/past intervals, trimmed reason, controlled 4xx, ambiguous network/server/malformed responses, no automatic retry, cursor encoding, cancellation signal, malformed or foreign-venue records, nullable legacy metadata.
- `src/pages/VenueDetailPage.closures.test.tsx`: inline staff form on Maintenance venue; persistence-gated success; duplicate-submit lock; preserve draft on failure; SGT list display; later pages and refresh; role denial; venue/user/role cancellation and late-response isolation; list failure/retry; nullable metadata; polling refresh and cleanup without draft loss.
- `e2e/venue-closures.spec.ts`: actual Chromium form → mocked POST → read-back list → next page; header/body assertions; non-Singapore display; role change; lost-save warning and input retention; screenshot/layout assertion. This demonstrates frontend behavior with mocked persistence, **not live database persistence**.

Screenshots generated by the browser test (git-ignored):

- `frontend/event-management-ui/test-results/venue-closures-SCRUM-170-r-7037b-GT-in-non-Singapore-browser-chromium/closure-form.png`
- `frontend/event-management-ui/test-results/venue-closures-SCRUM-170-r-7037b-GT-in-non-Singapore-browser-chromium/closure-persisted.png`

## Follow-up verification

After visual refinement and the pre-commit polling fix, 376 frontend tests across 31 files, 29 mocked Chromium E2E tests, build and lint passed. Background refresh failures retain the last successful venue and closure panel, preserving unsaved drafts and in-flight save outcomes while displaying a nonblocking warning; route changes reset detail state. The independent browser regression probe for draft preservation also passed. Desktop/mobile checks cover clearly filled primary buttons, outlined refresh, a grey read-only venue, required-field markers, and no horizontal overflow. These UI checks do not write to Supabase.

Separately, authorized live browser/local-service/shared-Supabase testing passed 18 functional cases with 62 accepted subchecks. Seven owned test closures were reconciled, removed and verified absent; pre-existing records were preserved. The local Word report and detailed evidence are in Downloads (`SCRUM170_Functional_Test_Report.docx` and `SCRUM170_Functional_Test_Evidence/`), not committed to the repository. One invalid harness assertion about request cancellation preventing server persistence was explicitly superseded and corrected.

The metadata NOT NULL migration was applied and independently read back. Production authentication remains outside scope: enabling development headers is not a secure production login. Git push does not enable or remove the development flag. Docker startup is not validated by the host-process tests above.
