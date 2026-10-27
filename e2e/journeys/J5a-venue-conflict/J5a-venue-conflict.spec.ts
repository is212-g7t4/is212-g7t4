import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'
import { openAs, users } from '../helpers/stack'
import { seedJ5a } from '../helpers/j5a'
import { deleteFixtureEvents } from '../helpers/cleanup'

/**
 * J5a — Prevent conflicting venue reservations (High; brief demo, detailed cases at integration level)
 *
 * Requires the real stack (`npm run dev`) and the seeded database.
 *
 * Journey ticket: SCRUM-259 (E2E Testing J5)
 *
 * Stories this journey exercises (a change to any of these can break it):
 *   - SCRUM-28  Venue Booking Request Submission (coordinator form, Pending Review)
 *   - SCRUM-29  Venue Booking Review and Decision (Venue Staff approval)
 *   - SCRUM-30  Check Venue Availability (conflict reported, request not submitted)
 *   - SCRUM-154 Configure Venue Buffer Times (setup/turnaround counted in the check)
 *
 * Stories the fixture setup relies on:
 *   - SCRUM-11  Event Submission Form (event creation)
 *   - SCRUM-159 Assign Coordinator to an Event
 *   - SCRUM-19  Update Event Status (Under Review, required before Venue Staff can decide)
 *
 * Not exercised here (integration level): SCRUM-155 legacy conflicts preserved after a buffer change,
 * SCRUM-145/146/147 tentative holds and their expiry, SCRUM-156 multiple venues per event.
 *
 * Buffers are 60 min setup and 60 min turnaround. Event A is approved 10:00-12:00, so it blocks 09:00-13:00,
 * and a new booking also needs its own buffers clear: it must start at 14:00 or later.
 */
test.describe.configure({ mode: 'serial' })

test.describe('J5a Prevent conflicting venue reservations', () => {
  const runId = Date.now().toString(36)
  const eventAName = `J5a Event A ${runId}`
  const eventBName = `J5a Event B ${runId}`
  let fixture: Awaited<ReturnType<typeof seedJ5a>>

  test.beforeAll(async ({ playwright }) => {
    // Clear leftovers from interrupted runs so they cannot hold the venue or slow the page.
    await deleteFixtureEvents()
    const api = await playwright.request.newContext()
    fixture = await seedJ5a(api, runId)
    await api.dispose()
  })

  test.afterAll(deleteFixtureEvents)

  async function submitBooking(page: Page, eventId: string, startTime: string, endTime: string) {
    await page.goto(`/events/${eventId}`)
    const form = page.locator('form.venue-booking-form')
    await form.getByRole('combobox').selectOption(fixture.venueId)
    await form.getByLabel('Booking start').fill(`${fixture.day}T${startTime}`)
    await form.getByLabel('Booking end').fill(`${fixture.day}T${endTime}`)
    await form.getByRole('button', { name: 'Submit venue booking' }).click()
    return form
  }

  async function approveAsStaff(staff: Page, eventName: string) {
    await staff.goto('/venue-requests')
    const row = staff.getByRole('region', { name: `${eventName} venue requests` })
      .getByRole('row').filter({ hasText: fixture.venueName })
    await row.getByRole('button', { name: 'Review' }).click()
    await staff.getByRole('dialog').getByRole('button', { name: 'Approve', exact: true }).click()
    await expect(staff.getByText('Venue request approved.')).toBeVisible()
    await expect(row).toContainText('Approved')
  }

  test('buffer-only conflict is blocked, then a clear interval is approved', async ({ browser }) => {
    const coordinator = await openAs(browser, users.coordinator)
    const staff = await openAs(browser, users.venueStaff)

    await test.step('Venue has buffers; coordinator books Event A and Venue Staff approves it', async () => {
      const form = await submitBooking(coordinator, fixture.eventAId, '10:00', '12:00')
      await expect(form.getByText(`${fixture.venueName} booking request submitted. Status: Pending Review.`)).toBeVisible()
      await approveAsStaff(staff, eventAName)
    })

    await test.step('Event B requests an interval whose own buffers overlap Event A (30 min after it ends)', async () => {
      await submitBooking(coordinator, fixture.eventBId, '12:30', '13:30')
    })

    await test.step('The conflict is reported and no request is created', async () => {
      await expect(coordinator.getByRole('alert')).toContainText('Request not submitted. An approved booking overlaps this time.')
      await expect(coordinator.getByText('No venue booking requests yet.')).toBeVisible()
    })

    await test.step('Event B submits a new interval that clears Event A and both buffers', async () => {
      const form = await submitBooking(coordinator, fixture.eventBId, '14:00', '16:00')
      await expect(form.getByText(`${fixture.venueName} booking request submitted. Status: Pending Review.`)).toBeVisible()
      await expect(coordinator.locator('.venue-booking-item')).toContainText('Pending Review')
    })

    await test.step('Venue Staff approves the Event B request', async () => {
      await approveAsStaff(staff, eventBName)
    })
  })
})
