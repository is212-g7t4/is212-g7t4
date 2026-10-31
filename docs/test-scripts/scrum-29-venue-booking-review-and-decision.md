# SCRUM-29 Venue Booking Review and Decision — manual test script

> Historical browser evidence: the mocked frontend browser suite was retired.
> Referenced browser specs are archived, not maintained runnable checks;
> unit/component tests and manual real-stack journeys remain separate tiers.

These are the SCRUM-29 acceptance criteria checked by hand against a running
stack. Attach this file and `scrum-29-screenshots/` to SCRUM-29 once it has
been run.

Automated coverage is separate and runs without the stack:

- Venue Availability: `tests/unit/test_scrum29_booking_review_decision.py` and
  `tests/integration/test_booking_review_decision.py` (real Postgres; the
  only place the stored decision and the "decisions are final" rule are
  proven).
- Venue Booking: `tests/unit/test_booking_review_decision.py` and
  `tests/integration/test_booking_review_decision.py` (respx stubs).
- Frontend: `VenueRequestReviewDialog.test.tsx`, `VenueRequestsPage.test.tsx`,
  `VenueBookingsPanel.test.tsx`, `venueBookings.test.ts` (Vitest) and
  `e2e/venue-booking-review.spec.ts` (mocked Playwright).

This script is the end-to-end pass over the real services, which those
cannot replace.

**Tester:** _not yet run_
**Date:** _
**Branch / commit:** `SCRUM-29-venue-booking-review-and-decision` @ _
**Result:** _ / 14 passed

## Acceptance criteria under test

- **AC1** — Venue Staff opening a pending request can view the event timing
  and venue requirements needed to assess it.
- **AC2** — Approving records the decision as approved, and the outcome is
  available to the Event Coordinator.
- **AC3** — Rejecting records the decision as rejected, and the outcome is
  available to the Event Coordinator.
- **AC4** — When rejecting, Venue Staff can give a reason (decided 25 Oct:
  required, 1–500 characters).
- **AC5** — Once decided, the request is no longer presented as awaiting a
  decision (decided 25 Oct: decisions are final).
- **AC6** — The coordinator can view the rejection reason so they can keep
  planning.

## Setup

1. Make sure every compose service has a `.env` (see AGENTS.md, *Every
   compose service needs its own `.env` first*), then from the repo root:

   ```
   npm run dev
   ```

2. `docker compose ps` shows every service `Up`; `curl localhost:5007/health`
   and `curl localhost:5008/health` return `{"status":"ok"}`.
3. Pick, in Supabase, one event assigned to an Event Coordinator: **Event A**
   in `Under Review`, with `expected_attendance`, `venue_requirements` and
   `accessibility_needs` filled in. Note a venue **V** with
   `setup_time_minutes = 30` and `turnaround_time_minutes = 45`, and a second
   venue **W**. Pick an **Event B** in `Pending Safety Check`.
4. As the coordinator, submit for Event A: request **R1** for V,
   10:00–12:00 on a free date; request **R2** for W, same time.
5. Keep the browser DevTools Network tab open.

## Steps

Viewing as **Venue Staff** unless a step says otherwise.

| # | Steps | Expected | Criterion | Result (pass/fail) | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | Open **Venue requests** | Event A's card says "2 awaiting review"; R1 and R2 each offer a **Review** button | AC5 | | |
| 2 | Click **Review** on R1 | A dialog "V for Event A" shows the event status, event dates, expected attendance, event venue requirements and accessibility needs; and the booking's schedule, "Venue occupied 9:30 am – 12:45 pm (includes 30 min setup, 45 min turnaround)", required vs venue capacity, booking requirements and submitted time | AC1 | | |
| 3 | Click **Approve** | Dialog closes; "Venue request approved."; R1's badge reads Approved and its action cell "Approved on <date, time>"; the card says "1 awaiting review" | AC2, AC5 | | |
| 4 | In Supabase, read R1's `VenueBooking` row | `status = 'Approved'`, `reviewed_by` = the staff user, `reviewed_at` = the time of step 3, `rejection_reason` NULL | AC2 | | |
| 5 | Click **View** on R1 | The dialog opens read-only: no Approve/Reject, "Approved on …" and "Already decided" | AC5 | | |
| 6 | Click **Review** on R2, then **Reject** | A "Reject venue request?" dialog naming "W for Event A"; **Confirm rejection** is disabled; typing only spaces keeps it disabled | AC4 | | |
| 7 | Type "Hall is too small for the stage" and confirm | "Venue request rejected."; R2 shows Rejected, "Rejected on <date, time>" and the reason (hover shows it in full) | AC3, AC4, AC5 | | |
| 8 | In Supabase, read R2's row | `status = 'Rejected'`, `rejection_reason` = the text, `reviewed_at` set | AC3, AC4 | | |
| 9 | Set **Show** to **Awaiting review** | Neither R1 nor R2 is listed | AC5 | | |
| 10 | Switch to the **Event Coordinator**, open Event A | R1 shows "Approved by Venue Staff on <date>"; R2 shows a "Rejected by Venue Staff" box with the reason and date, then "Rejected requests are read-only. Use Add venue booking below to request a replacement." | AC2, AC3, AC6 | | |
| 11 | As the coordinator, edit R1 (change the end time) and save | R1 is back to Pending Review with no "Approved by" line; in Supabase `reviewed_by`, `reviewed_at` and `rejection_reason` are NULL | AC5 | | |
| 12 | With R1 Pending Review, open its **Review** dialog in two staff tabs; approve in tab 1, then approve in tab 2 | Tab 2 shows "This venue request is not awaiting staff review. The list has been refreshed." and R1 is listed as Approved | AC5 | | |
| 13 | As the coordinator, submit a request for V on Event B's date; then, as Venue Staff, open it | The dialog is read-only with "Not open for review while the event is Pending Safety Check" | AC1, AC5 | | |
| 14 | `curl -X PATCH localhost:5007/booking-requests/<R1 id>/reject -H 'Content-Type: application/json' -d '{"reviewedBy":"<staff id>"}'` | `401`: the legacy route now needs Venue Staff headers (D7) | AC4 | | |

## Not covered by this script

- Decision alerts or notifications to the coordinator (SCRUM-47).
- The J5a real-stack journey (SCRUM-259).
