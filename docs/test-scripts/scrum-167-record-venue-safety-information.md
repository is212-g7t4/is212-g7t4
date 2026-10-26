# SCRUM-167 Record Venue Safety Information — manual test script

These are the SCRUM-167 acceptance criteria checked by hand against a running
stack. Attach this file and `scrum-167-screenshots/` to SCRUM-167 once it has
been run.

Automated coverage is separate and runs without the stack:

- Venue Service: `tests/unit/test_venue_safety_information.py` and
  `tests/integration/test_venue_safety_information.py` (real Postgres; the
  only place the role refusal, the stamp and the `User` foreign key are
  proven).
- Safety Check Service: `tests/unit/test_venue_safety_information.py` and
  `tests/integration/test_venue_safety_information.py` (respx stubs).
- Frontend: `venueForm.test.ts`, `AddVenuePage.test.tsx`,
  `VenueDetailPage.test.tsx` (Vitest) and `e2e/venue-safety-information.spec.ts`
  (mocked Playwright).

This script is the end-to-end pass over the real services, including the hop
from Venue Service to the Safety Officer's review, which those cannot replace.

**Tester:** Claude Code for Clarice Lim (the UI steps driven in Chromium by a
Playwright script against the real stack, not clicked by hand)
**Date:** 26 Oct 2026
**Branch / commit:** `SCRUM-167-record-venue-safety-information` @ `1c52656`
plus the uncommitted SCRUM-167 changes
**Result:** 10 / 10 passed

Data used: V = Seminar Room C (`a1706889-…`), E = Heritage Walk Briefing
(`5afe0003-…`, `Pending Safety Check`, Approved booking at V), S = Siti Aminah,
C = Marcus Lim, Safety Officer = Nurul Huda. V's four safety columns were all
`NULL` before the run and were reset to `NULL` afterwards; its profile fields
were not changed.

## Acceptance criteria under test

- **AC1** — Given authorised Venue Staff edit a venue, when they enter
  emergency access details (e.g. exits, assembly point, emergency vehicle
  access) and known restrictions (e.g. noise curfew, no open flames, floor
  load limit), then the details are saved with the venue and shown on its
  details page.
- **AC2** — Given a venue has no safety information recorded, when it is
  viewed, then the fields show "Not provided" rather than appearing blank.
- **AC3** — Given safety information is updated, when it is saved, then the
  editor and timestamp are recorded.
- **AC4** — Given a user who is not Venue Staff, when they attempt to edit
  venue safety information through the UI or API, then the change is
  rejected and the existing values are unchanged.

## Setup

1. Make sure every compose service has a `.env` (see AGENTS.md, *Every
   compose service needs its own `.env` first*), then from the repo root:

   ```
   npm run dev
   ```

2. `docker compose ps` shows every service `Up`; `curl localhost:5006/health`
   and `curl localhost:5012/health` return `{"status":"ok"}`.
3. Pick, in Supabase, a venue **V** whose `emergency_access_details` and
   `known_restrictions` are both `NULL`, and an event **E** in
   `Pending Safety Check` with an Approved booking at V. Note the `user_id`
   of a Venue Staff user **S** and of an Event Coordinator **C**.
4. Keep the browser DevTools Network tab open.

## Steps

| # | Steps | Expected | Criterion | Result (pass/fail) | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | As **Venue Staff** S, open **Venues** → V | A **Safety information** block shows "Emergency access details: Not provided" and "Known restrictions: Not provided"; no "Last updated" line | AC2 | pass | Both "Not provided", no "Last updated" line. `01-not-provided.png` |
| 2 | Click **Edit Venue** | A **Safety Information** section with two empty text areas, "Emergency Access Details" and "Known Restrictions" | AC1 | pass | Both text areas empty. `02-edit-section-empty.png` |
| 3 | Enter emergency access "Exits on north and south walls" (new line) "Assembly point at the front lawn; fire engine access via Gate 2" and restrictions "Noise curfew 10pm; no open flames; floor load limit 500 kg/m²"; **Save Changes** | Network tab: `PUT :5007/venues/<V>` then `PUT :5006/venues/<V>/safety-info` with `X-Dev-Role: Venue Staff`; the details page shows both texts, the line break kept | AC1 | pass | `PUT :5007/venues/<V>` then `PUT :5006/…/safety-info` with `X-Dev-Role: Venue Staff`; line break kept. `03-04-saved-with-stamp.png` |
| 4 | Same page | "Last updated <today, time> by <S's name>" | AC3 | pass | "Last updated 26 Oct 2026, 11:01 am by Siti Aminah". `03-04-saved-with-stamp.png` |
| 5 | In Supabase, read V's row | Both texts saved; `safety_info_updated_by` = S; `safety_info_updated_at` = the save time | AC1, AC3 | pass | Texts match; `safety_info_updated_by` = S; `safety_info_updated_at` = 03:01:37 UTC (11:01 SGT) |
| 6 | Edit V again, change nothing in Safety Information, **Save Changes** | No `safety-info` request in the Network tab; the "Last updated" time is unchanged | AC3 | pass | Waited 61 s before saving: only the `:5007` profile PUT was sent; stamp still 11:01. `06-unchanged-save.png` |
| 7 | Edit V, clear both text areas, **Save Changes** | Both fields read "Not provided"; in Supabase both columns are `NULL` (not empty text); "Last updated" shows the new time | AC2, AC3 | pass | Body `{"emergencyAccessDetails":null,"knownRestrictions":null}`; both columns `IS NULL`; stamp 11:03. `07-cleared.png` |
| 8 | Re-enter the step-3 texts and save. Switch to **Event Coordinator** C and open V | The Safety information block shows both texts; there is no **Edit Venue** button | AC1, AC4 | pass | Marcus Lim sees both texts; 0 Edit Venue buttons. `08-coordinator-view.png` |
| 9 | From a terminal: `curl -si -X PUT localhost:5006/venues/<V>/safety-info -H 'Content-Type: application/json' -H 'X-Dev-User-Id: <C>' -H 'X-Dev-Role: Event Coordinator' -d '{"emergencyAccessDetails":"Changed","knownRestrictions":null}'` | `403` with `"code": "VENUE_STAFF_ONLY"`; in Supabase V's four safety columns are unchanged from step 8 | AC4 | pass | `403 {"code":"VENUE_STAFF_ONLY", …}`; text hash, editor and stamp identical before and after |
| 10 | As the **Safety Officer**, open **Safety checks** → E | The review's venue V shows the step-3 "Emergency access" and "Known venue restrictions" texts | AC1 ("so that") | pass | Review for Seminar Room C shows both texts under "Emergency access" and "Known venue restrictions". `10-safety-officer-review.png` |

## Not covered by this script

- Re-checking events already in or past their safety check when a venue's
  safety information changes. Decided 26 Oct: editing safety information
  changes no event or booking status (SCRUM-153 covers booking changes).
- Authentication. Identity is the `X-Dev-*` headers, as for every other
  staff-only route, until real auth lands.
