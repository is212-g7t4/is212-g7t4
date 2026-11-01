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
 * A hold always spans "now" to its expiry, so "the held interval" is the stretch before expiry. That interval is
 * in the past once the hold expires, so step 7 books a fresh future interval on the same venue.
 * Expiry is evaluated by time: no record is ever labelled "Expired"; the venue simply returns to Available.
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
