# SCRUM-28 Venue Booking Request Submission — manual test script

These are the SCRUM-28 acceptance criteria checked by hand against a running
stack. Attach this file and `scrum-28-screenshots/` to SCRUM-28 once it has
been run.

Automated coverage is separate and runs without the stack:

- Venue Availability: `tests/unit/test_booking_request_submission.py` and
  `tests/integration/test_booking_request_submission.py` (real Postgres; the
  only place the AC6 overlap rule is proven).
- Venue Booking: `tests/unit/test_booking_request_submission.py` and
  `tests/integration/test_booking_request_submission.py` (respx stubs).
- Frontend: `VenueBookingsPanel.test.tsx`, `VenueRequestsPage.test.tsx`,
  `venueBookings.test.ts` (Vitest) and `e2e/venue-booking-submission.spec.ts`
  (mocked Playwright).

This script is the end-to-end pass over the real services, which those
cannot replace.

**Tester:** _not yet run_
**Date:** _
**Branch / commit:** `SCRUM-28-venue-booking-request-submission` @ _
**Result:** _ / 12 passed

## Acceptance criteria under test

- **AC1** — When entering a venue booking request, the coordinator can
  provide the event timing and venue requirements Venue Staff need.
- **AC2** — Once submitted, the request is recorded and made available to
  Venue Staff for review.
- **AC3** — Venue Staff can view the event the request relates to, with the
  event timing and venue requirements.
- **AC4** — A request with no booking decision yet is identifiable as
  awaiting Venue Staff review.
- **AC5** — The request stays associated with its event.
- **AC6** — The same venue requested or booked for another event at a
  non-overlapping time is accepted for review as normal.
- **Gate (decided 25 Oct)** — New requests are accepted only while the event
  is Submitted, Under Review, Approved or Safety Changes Requested.

## Setup

1. Make sure every compose service has a `.env` (see AGENTS.md, *Every
   compose service needs its own `.env` first*), then from the repo root:

   ```
   npm run dev
   ```

2. `docker compose ps` shows every service `Up`; `curl localhost:5007/health`
   and `curl localhost:5008/health` return `{"status":"ok"}`.
3. Pick, in Supabase, two events assigned to the same Event Coordinator:
   **Event A** in `Under Review` and **Event B** in `Under Review`, plus one
   **Event C** in `Pending Safety Check`. Note a venue **V** with
   `setup_time_minutes = 30` and `turnaround_time_minutes = 45`.
4. Keep the browser DevTools Network tab open.

## Steps

Viewing as the **Event Coordinator** assigned to Events A–C unless a step
says otherwise.

| # | Steps | Expected | Criterion | Result (pass/fail) | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | Open Event A from **My events** and scroll to **Venue bookings** | The **Add venue booking** form shows Venue, Booking start/end (prefilled from the event dates), required capacity (prefilled from expected attendance) and Venue requirements | AC1 | | |
| 2 | Choose venue V, set 10:00–12:00 on a free date, capacity within V's capacity, requirements "Stage", and submit | "V booking request submitted. Status: Pending Review."; the booking appears in the list with a Pending Review badge | AC2 | | |
| 3 | In Supabase, read the new `VenueBooking` row | `status = 'Pending Review'`, `event_id` = Event A, `requested_at` set to the submission time | AC2, AC5 | | |
| 4 | Switch to **Venue Staff**, open **Venue requests** | Event A's card shows its name, status, coordinator and "Event: <event dates>"; the booking row shows V, 10:00–12:00, the capacity, "Stage" and "Submitted <time>" | AC3, AC5 | | |
| 5 | Same page | The booking's badge reads **Awaiting review**, the card says "1 awaiting review", and a **Review** button is offered (SCRUM-29 moved Approve / Reject into its dialog) | AC4 | | |
| 6 | Set **Show** to **Awaiting review** | Only awaiting requests are listed; the Network tab shows `?status=Pending` | AC4 | | |
| 7 | As Venue Staff, click **Review** on the step-2 booking and **Approve** it | Badge changes to Approved; the awaiting count disappears for Event A | AC4 | | |
| 8 | As the coordinator, open Event B and request V on the same date **13:15–15:00** | Accepted: "… submitted. Status: Pending Review." (12:00 end + 45 min turnaround + 30 min setup) | AC6 | | |
| 9 | Request V for Event B on the same date **13:14–15:00** | Refused: "Request not submitted. An approved booking overlaps this time. …"; no new row in Supabase | AC6 | | |
| 10 | On a new date, submit V 10:00–12:00 for Event A and leave it **Pending Review**; then request V for Event B at 10:30–11:30 that date | Accepted: a request that has only been *requested* (not approved) by another event never blocks | AC6 | | |
| 11 | Open Event C (`Pending Safety Check`) | Existing bookings are listed; instead of the form: "New venue requests can be submitted while the event is Submitted, Under Review, Approved or Safety Changes Requested." | Gate | | |
| 12 | With Event A's page open in one tab, move Event A to `Pending Safety Check` in Supabase, then submit a new request from that tab | The server's message is shown (not a venue conflict); the page re-reads the event and shows the step-11 note | Gate | | |

## Part B — changing a booking of a Confirmed event (decided 25 Oct)

Editing or cancelling a venue booking of a `Confirmed` event withdraws its
safety approval and sends it back to `Approved`. This chain spans Venue
Booking → Safety Check → Safety Check Record + Event, so it can only be proven
against the running stack; each service's own tests cover its part.

Setup: an **Event D** in `Confirmed` with one Approved booking, assigned to
the same coordinator, whose latest `SafetyCheck` round is `Safety Approved`.

| # | Steps | Expected | Result (pass/fail) | Notes |
| --- | --- | --- | --- | --- |
| B1 | Open Event D, click **Edit booking**, change the end time, click **Save venue booking** | A dialog: "Changing this booking withdraws the event's safety approval. …"; nothing is saved yet | | |
| B2 | Click **Cancel** in the dialog | Dialog closes; booking and event unchanged | | |
| B3 | Save again and confirm **Save and withdraw approval** | "… updated and returned to pending review. The event's safety approval was withdrawn and it is back to Approved."; the event badge reads Approved | | |
| B4 | In Supabase | The `SafetyCheck` round is `Approval Withdrawn` with `withdrawal_reason` set and **no** new round; the booking is `Pending Review` with a fresh `requested_at`; the event's history has the withdrawal entry | | |
| B5 | As Venue Staff, open **Venue requests** | The edited booking is listed under Event D as Awaiting review | | |
| B6 | Approve it as Venue Staff, then as the coordinator submit Event D for its safety check | Accepted; a new round N+1 opens and the event is `Pending Safety Check` | | |
| B7 | With Event D `Pending Safety Check`, open it | Edit / Cancel are disabled with "Venue bookings can't be edited or cancelled while the event is Pending Safety Check." | | |
| B8 | On another Confirmed event, edit a booking to overlap an Approved booking of a different event and confirm | "Request not submitted. An approved booking overlaps this time. …"; the event is still **Confirmed** and its round still `Safety Approved` (the withdrawal was restored) | | |

## Not covered by this script

- The submission notification to Venue Staff (SCRUM-47).
- Approve/reject decisions and their outcome for the coordinator beyond
  step 7 (SCRUM-29).
