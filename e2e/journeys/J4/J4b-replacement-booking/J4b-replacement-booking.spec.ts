import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { deleteFixtureEvents } from '../../../helpers/cleanup'
import { openAs, users } from '../../../helpers/stack'
import {
  approveJ4Replacement, closeJ4Venue, expectPreserved, j4Names, j4Scope, readBookings, seedJ4,
} from '../helpers/seed'
import type { J4Fixture } from '../helpers/seed'

/**
 * SCRUM-258 (E2E Testing J4), path B: recover using a separate replacement booking.
 * Exercises SCRUM-28, 29, 30, 156, 157.
 * Fixture dependencies: SCRUM-8, 11, 19, 159, 170, 171.
 * Requires the real stack, seeded accounts and E2E_PASSWORD (or per-role passwords).
 */
test.describe('J4B Coordinator replaces a closure-rejected booking', () => {
  test.setTimeout(360_000)
  const names = j4Names('b', randomUUID())
  let fixture: J4Fixture

  test.beforeAll(async ({ playwright }) => {
    const api = await playwright.request.newContext()
    try {
      fixture = await seedJ4(api, names)
      await closeJ4Venue(api, fixture)
    } finally { await api.dispose() }
  })
  test.afterAll(async () => { await deleteFixtureEvents(j4Scope(names)) })

  test('approve a free alternative on the same event while preserving the rejection and unaffected arrangements', async ({ browser, request }) => {
    const coordinator = await openAs(browser, users.coordinator)
    const staff = await openAs(browser, users.venueStaff)
    const original = (await readBookings(request, fixture.eventId))
      .find(booking => booking.id === fixture.affectedBookingId)
    expect(original).toMatchObject({ status: 'Rejected', closureRejection: { reason: fixture.reason } })
    let replacementId = ''

    await test.step('Coordinator retains the rejected request and submits a separate booking for a free venue', async () => {
      await coordinator.goto(`/events/${fixture.eventId}`)
      const rejected = coordinator.locator(`#venue-booking-${fixture.affectedBookingId}`)
      await expect(rejected).toContainText(fixture.reason)
      await expect(rejected.getByRole('button', { name: 'Edit booking' })).toHaveCount(0)
      const form = coordinator.locator('form.venue-booking-form')
      await form.getByRole('combobox').selectOption(fixture.alternativeVenueId)
      await form.getByLabel('Booking start').fill(fixture.start)
      await form.getByLabel('Booking end').fill(fixture.end)
      await form.getByLabel('Venue requirements').fill('J4B replacement for the closure-rejected venue.')
      await form.getByRole('button', { name: 'Submit venue booking' }).click()
      await expect(form.getByRole('status')).toContainText(`${fixture.alternativeVenueName} booking request submitted`)
      const bookings = await expectPreserved(request, fixture)
      expect(bookings).toHaveLength(3)
      expect(bookings.find(booking => booking.id === fixture.affectedBookingId)).toEqual(original)
      const replacement = bookings.find(booking => booking.venueId === fixture.alternativeVenueId)
      expect(replacement).toMatchObject({ eventId: fixture.eventId, status: 'Pending Review' })
      if (!replacement) throw new Error('The replacement booking was not persisted.')
      replacementId = replacement.id
      expect(replacementId).not.toBe(fixture.affectedBookingId)
    })

    await test.step('Venue Staff review and approve only the replacement request', async () => {
      await approveJ4Replacement(staff, fixture)
    })

    await test.step('After refresh the same event retains both approvals and the original closure rejection', async () => {
      await coordinator.reload()
      await expect(coordinator.locator(`#venue-booking-${replacementId}`)).toContainText('Approved')
      await expect(coordinator.locator(`#venue-booking-${fixture.keptBookingId}`)).toContainText('Approved')
      await expect(coordinator.locator(`#venue-booking-${fixture.affectedBookingId}`)).toContainText(fixture.reason)
      const bookings = await expectPreserved(request, fixture)
      expect(bookings).toHaveLength(3)
      expect(bookings.find(booking => booking.id === fixture.affectedBookingId)).toEqual(original)
      expect(bookings.find(booking => booking.id === replacementId)).toMatchObject({
        eventId: fixture.eventId, venueId: fixture.alternativeVenueId, status: 'Approved',
      })
    })
  })
})
