import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import type { Page } from '@playwright/test'
import { deleteFixtureEvents } from '../../../helpers/cleanup'
import { authHeaders, openAs, serviceUrl, users } from '../../../helpers/stack'
import { requestVenue, seedJ5c, sgt } from './helpers/seed'

/**
 * J5c — Prevent booking conflicts with tentative venue holds (High; brief demo, detailed cases at integration level)
 *
 * Requires the real stack (`npm run dev`) and the seeded database. Runs for about 8 minutes because it waits for
 * a real hold to expire.
 *
 * Journey ticket: SCRUM-259 (E2E Testing J5)
 *
 * Stories this journey exercises (a change to any of these can break it):
 *   - SCRUM-145/146/147 Tentative venue holds (place, refuse conflicts, expiry, reminder)
 *   - SCRUM-28  Venue Booking Request Submission (coordinator form, Pending Review)
 *   - SCRUM-29  Venue Booking Review and Decision (Venue Staff approval)
 *   - SCRUM-30  Check Venue Availability (active hold reported as a conflict)
 *
 * Stories the fixture setup relies on:
 *   - SCRUM-11  Event Submission Form (event creation)
 *   - SCRUM-159 Assign Coordinator to an Event
 *   - SCRUM-19  Update Event Status (Under Review, required before a venue can be requested)
 *
 * Flow, and how each step is implemented:
 *   1. Venue Staff places a hold on a free venue with an expiry; the venue shows On Hold.
 *   2. A hold with no expiry (form requires one) or overlapping an existing booking is refused.
 *   3. The Coordinator cannot book the held venue for the held interval while the hold is active.
 *   4. The Coordinator sees the correct expiry on the venue details.
 *   5. A hold within 3 days of expiry reminds the Coordinator (venue and expiry); an expired hold does not.
 *   6. After the expiry time the venue shows Available.
 *   7. The Coordinator books the venue as Pending Review and Venue Staff approves it.
 *
 * How the 6-minute expiry works (HOLD_MINUTES = 6):
 *   - Step 1 enters an expiry of "now + 6 minutes" in Singapore time, computed once by sgt(HOLD_MINUTES) at the
 *     start of the test and reused as the expected value in steps 3 and 4. The datetime-local field has minute
 *     precision, so the real hold lasts between 5 and 6 minutes.
 *   - A hold always spans "now" to its expiry, so "the held interval" is the time before expiry: step 3 tries
 *     [now + 1 min, expiry]. Six minutes leaves room for steps 1-3 to finish while the hold is still active.
 *   - Step 6 reloads the venue page every 10 seconds until it shows Available, for up to HOLD_MINUTES + 2 minutes.
 *     This real wait is why the journey takes about 8 minutes and is left out of the CI journeys job.
 *   - The hold's interval is in the past after expiry, so step 7 books a fresh future interval
 *     (now + 10 to now + 70 minutes) on the same venue instead of the original one.
 *   - Expiry is evaluated by time: no record is ever labelled "Expired"; the venue simply returns to Available.
 *   - The reminder in step 5 uses a separate hold on the `reminded` venue expiring in 2 days 23 hours, because
 *     reminders only cover holds expiring within 3 days. It is seeded as a fixture, not waited on.
 */
const HOLD_MINUTES = 6
test.describe.configure({ mode: 'serial', timeout: 900_000 })

test.describe('J5c Prevent booking conflicts with tentative venue holds', () => {
  const runId = randomUUID()
  const eventName = `J5c Event ${runId}`
  const venueNames = {
    held: `J5c Venue held ${runId}`,
    booked: `J5c Venue booked ${runId}`,
    reminded: `J5c Venue reminded ${runId}`,
  }
  const scope = { eventNames: [eventName], venueNames: Object.values(venueNames) }
  let fixture: Awaited<ReturnType<typeof seedJ5c>>

  test.beforeAll(async ({ playwright }) => {
    const api = await playwright.request.newContext()
    try {
      fixture = await seedJ5c(api, runId)
    } finally {
      await api.dispose()
    }
  })

  test.afterAll(async () => { await deleteFixtureEvents(scope) })

  /** Formats a naive SGT timestamp the way the UI does, using the browser's own locale data. */
  const shown = (page: Page, naive: string) => page.evaluate(
    (value) => new Date(value).toLocaleString('en-SG', { dateStyle: 'medium', timeStyle: 'short' }),
    naive,
  )

  test('hold blocks bookings until it expires, then the venue is bookable and approved', async ({ browser, playwright }) => {
    const staff = await openAs(browser, users.venueStaff)
    const coordinator = await openAs(browser, users.coordinator)
    const api = await playwright.request.newContext()
    const heldPath = `/venues/${fixture.heldVenueId}`
    const holdExpiry = sgt(HOLD_MINUTES)

    await test.step('Venue Staff places a hold with an expiry and the venue shows On Hold', async () => {
      await staff.goto(heldPath)
      await staff.getByRole('button', { name: 'Hold', exact: true }).click()
      await staff.getByLabel('Hold expiry date and time').fill(holdExpiry)
      await staff.getByLabel('Event Coordinator to remind (optional)').selectOption(users.coordinator.id)
      await staff.getByRole('button', { name: 'Confirm hold' }).click()
      await expect(staff.locator('.venue-status')).toHaveText('On Hold')
    })

    await test.step('A hold with no expiry, or one overlapping an existing booking, is refused', async () => {
      await staff.goto(`/venues/${fixture.bookedVenueId}`)
      await staff.getByRole('button', { name: 'Hold', exact: true }).click()
      const form = staff.locator('.venue-hold-form')
      await form.getByRole('button', { name: 'Confirm hold' }).click()
      expect(await form.getByLabel('Hold expiry date and time').evaluate((input: HTMLInputElement) => input.validity.valueMissing)).toBe(true)
      await expect(staff.locator('.venue-status')).toHaveText('Available')

      await form.getByLabel('Hold expiry date and time').fill(fixture.bookedEnd)
      await form.getByRole('button', { name: 'Confirm hold' }).click()
      await expect(form.getByRole('alert')).toContainText('This hold overlaps an existing booking or active hold.')
      await expect(staff.locator('.venue-status')).toHaveText('Available')
    })

    await test.step('The coordinator cannot book the held venue for the held interval', async () => {
      const start = sgt(1)
      await coordinator.goto(`/events/${fixture.eventId}`)
      const form = coordinator.locator('form.venue-booking-form')
      await form.getByLabel('Booking start').fill(start)
      await form.getByLabel('Booking end').fill(holdExpiry)
      // Playwright's toBeDisabled ignores a disabled <option>, so assert the attribute.
      await expect(form.getByRole('option', { name: /J5c Venue held .* \(On Hold\)/ })).toHaveAttribute('disabled', '')

      const refused = await requestVenue(api, fixture.eventId, fixture.heldVenueId, start, holdExpiry)
      expect(refused.status()).toBe(409)
      const body = await refused.json()
      expect(body.code).toBe('VENUE_UNAVAILABLE')
      expect(body.conflictTypes).toContain('TENTATIVE_HOLD')
    })

    await test.step('The coordinator sees the hold expiry on the venue details', async () => {
      await coordinator.goto(heldPath)
      await expect(coordinator.locator('.venue-status')).toHaveText('On Hold')
      await expect(coordinator.locator('.event-detail').filter({ hasText: 'Hold expires' }))
        .toContainText(await shown(coordinator, holdExpiry))
    })

    await test.step('A hold within 3 days of expiry reminds the coordinator with venue and expiry', async () => {
      await coordinator.goto(`/events/${fixture.eventId}`)
      const reminder = coordinator.getByRole('alert').filter({ hasText: venueNames.reminded })
      await expect(reminder).toContainText(`expires on ${await shown(coordinator, fixture.reminderExpiry)}`)
    })

    await test.step('After the expiry time the venue is available and the hold sends no reminder', async () => {
      await expect(async () => {
        await coordinator.goto(heldPath)
        await expect(coordinator.locator('.venue-status')).toHaveText('Available', { timeout: 5_000 })
      }).toPass({ timeout: (HOLD_MINUTES + 2) * 60_000, intervals: [10_000] })
      await expect(coordinator.locator('.event-detail').filter({ hasText: 'Hold expires' })).toHaveCount(0)

      const reminders = await api.get(serviceUrl('venueAvailability', '/venue-holds/reminders'), {
        headers: await authHeaders(users.coordinator),
      })
      const venueIds = ((await reminders.json()).reminders as { venueId: string }[]).map((hold) => hold.venueId)
      expect(venueIds).toContain(fixture.remindedVenueId)
      expect(venueIds).not.toContain(fixture.heldVenueId)

      await coordinator.goto(`/events/${fixture.eventId}`)
      await expect(coordinator.getByRole('alert').filter({ hasText: venueNames.reminded })).toBeVisible()
      await expect(coordinator.getByRole('alert').filter({ hasText: venueNames.held })).toHaveCount(0)
    })

    await test.step('The coordinator books the now-free venue, it is Pending Review, and Venue Staff approves it', async () => {
      await coordinator.goto(`/events/${fixture.eventId}`)
      const form = coordinator.locator('form.venue-booking-form')
      await form.getByRole('combobox').selectOption(fixture.heldVenueId)
      await form.getByLabel('Booking start').fill(sgt(10))
      await form.getByLabel('Booking end').fill(sgt(70))
      await form.getByRole('button', { name: 'Submit venue booking' }).click()
      await expect(form.getByText(`${venueNames.held} booking request submitted. Status: Pending Review.`)).toBeVisible()

      await staff.goto('/venue-requests')
      const row = staff.getByRole('region', { name: `${eventName} venue requests` })
        .getByRole('row').filter({ hasText: venueNames.held })
      await row.getByRole('button', { name: 'Review' }).click()
      await staff.getByRole('dialog').getByRole('button', { name: 'Approve', exact: true }).click()
      await expect(staff.getByText('Venue request approved.')).toBeVisible()
      await expect(row).toContainText('Approved')
    })

    await api.dispose()
  })
})
