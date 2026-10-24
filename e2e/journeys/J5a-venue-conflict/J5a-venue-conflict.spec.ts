import { test } from '@playwright/test'

/**
 * J5a — Prevent conflicting venue reservations (High; brief demo, detailed cases at integration level)
 *
 * PLACEHOLDER: blocked on SCRUM-28 and SCRUM-29, which are still To Do in Jira.
 * Remove `test.fixme` and fill in the steps once they land.
 *
 * Journey ticket: SCRUM-259 (E2E Testing J5)
 *
 * Stories this journey depends on:
 *   - SCRUM-28  Venue Booking Request Submission (blocker, To Do)
 *   - SCRUM-29  Venue Booking Review and Decision, i.e. Venue Staff approval (blocker, To Do)
 *   - SCRUM-156 Book Multiple Venues for an Event
 *   - SCRUM-30  Check Venue Availability (conflict reporting)
 *   - SCRUM-154 Configure Venue Buffer Times (setup/turnaround)
 *   - SCRUM-155 Identify Legacy Scheduling Conflicts
 *   - SCRUM-145 Tentative Venue Hold
 *   - SCRUM-146 Tentative Venue Holds Expire
 *   - SCRUM-147 Tentative Venue View Expiry
 *
 * Covers: E2E-B1, B2a, B2b, B4a, B4b, B5a, B5b, B6, D3.
 */
test.describe('J5a Prevent conflicting venue reservations', () => {
  test.fixme('conflicting request is blocked, then a free alternative is approved', async () => {
    // 1. Event books a venue with active setup buffers.
    // 2. Another event requests the same venue inside the occupied interval or buffer window.
    // 3. Request is rejected or the slot is excluded in the UI.
    // 4. User picks a free alternative interval.
    // 5. Replacement request succeeds and Venue Staff approves it.
  })
})
