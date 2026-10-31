import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import type { Page, Response } from '@playwright/test'
import { deleteFixtureEvents } from '../../../helpers/cleanup'
import { openAs, users } from '../../../helpers/stack'
import { seedJ5a } from './helpers/seed'

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
test.describe.configure({ mode: 'serial', timeout: 300_000 })

test.describe('J5a Prevent conflicting venue reservations', () => {
  const runId = randomUUID()
  const eventAName = `J5a Event A ${runId}`
  const eventBName = `J5a Event B ${runId}`
  const scope = { eventNames: [eventAName, eventBName], venueNames: [`J5a Venue ${runId}`] }
  let fixture: Awaited<ReturnType<typeof seedJ5a>>

  test.beforeAll(async ({ playwright }) => {
    const api = await playwright.request.newContext()
    try {
      fixture = await seedJ5a(api, runId)
    } finally {
      await api.dispose()
    }
  })

  test.afterAll(async () => { await deleteFixtureEvents(scope) })

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
    let latestResponse: Response | undefined
    const recordResponse = (response: Response) => {
      if (new URL(response.url()).pathname === '/booking-requests'
        && response.request().method() === 'GET') latestResponse = response
    }
    staff.on('response', recordResponse)
    try {
      for (let attempt = 0; attempt < 3; attempt++) {
        if (attempt === 0) await staff.goto('/venue-requests')
        else await staff.getByRole('button', { name: 'Refresh requests' }).click()
        await expect(staff.getByRole('button', { name: 'Refresh requests' })).toBeEnabled()
        const alert = staff.getByRole('alert')
        if (!await alert.isVisible()) break
        const status = latestResponse?.status()
        const failure = `Venue request queue load failed (HTTP ${status ?? 'unknown'}): ${await alert.innerText()}`
        if (status === undefined || ![502, 503, 504].includes(status) || attempt === 2) throw new Error(failure)
        console.warn(`${failure} Retrying through Refresh requests.`)
      }
    } finally {
      staff.off('response', recordResponse)
    }
    const row = staff.getByRole('region', { name: `${eventName} venue requests` })
      .getByRole('row').filter({ hasText: fixture.venueName })
    await expect(row.getByRole('button', { name: 'Review', exact: true })).toBeVisible()
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