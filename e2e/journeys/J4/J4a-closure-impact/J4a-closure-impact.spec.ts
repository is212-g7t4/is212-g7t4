import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { deleteFixtureEvents } from '../../../helpers/cleanup'
import { openAs, users } from '../../../helpers/stack'
import { expectPreserved, j4Names, j4Scope, seedJ4 } from '../helpers/seed'
import type { J4Fixture } from '../helpers/seed'

/**
 * SCRUM-258 (E2E Testing J4), path A: a closure affects only its overlapping booking.
 * Exercises SCRUM-156, 170, 171, 173, 174.
 * Fixture dependencies: SCRUM-8, 11, 19, 28, 29, 159.
 * Requires the real stack, seeded accounts and E2E_PASSWORD (or per-role passwords).
 */
test.describe('J4A recover from a venue closure without damaging other arrangements', () => {
  test.setTimeout(360_000)
  const names = j4Names('a', randomUUID())
  let fixture: J4Fixture

  test.beforeAll(async ({ playwright }) => {
    const api = await playwright.request.newContext()
    try { fixture = await seedJ4(api, names) }
    finally { await api.dispose() }
  })
  test.afterAll(async () => { await deleteFixtureEvents(j4Scope(names)) })

  test('reject only the overlapping booking, notify its Coordinator and display closure availability', async ({ browser, request }) => {
    const staff = await openAs(browser, users.venueStaff)
    const coordinator = await openAs(browser, users.coordinator)
    let closureId = ''

    await test.step('Venue Staff preview and confirm a closure affecting exactly one approved request', async () => {
      await staff.goto(`/venues/${fixture.closedVenueId}`)
      await staff.getByRole('button', { name: 'Record temporary closure' }).click()
      const form = staff.getByRole('form', { name: 'Record temporary closure' })
      await form.getByLabel('Closure start (SGT)').fill(fixture.closureStart)
      await form.getByLabel('Closure end (SGT)').fill(fixture.closureEnd)
      await form.getByLabel('Reason', { exact: true }).fill(fixture.reason)
      await form.getByRole('button', { name: 'Preview affected requests' }).click()
      const confirmation = staff.getByRole('region', { name: 'Confirm temporary closure' })
      await expect(confirmation).toContainText('1 booking requests will be rejected.')
      const affected = confirmation.getByRole('list', { name: 'Affected booking requests' }).getByRole('listitem')
      await expect(affected).toHaveCount(1)
      await expect(affected).toContainText(fixture.eventName)
      await expect(affected).toContainText(fixture.affectedBookingId)
      await expect(affected).toContainText('Approved')
      const saved = staff.waitForResponse(response => new URL(response.url()).pathname === '/venue-closures'
        && response.request().method() === 'POST')
      await form.getByRole('button', { name: 'Confirm closure and reject requests' }).click()
      const response = await saved
      expect(response.status(), await response.text()).toBe(201)
      const body = await response.json()
      expect(body.rejectedCount).toBe(1)
      closureId = body.closure.closureId
      await expect(staff.getByRole('status').filter({ hasText: 'Closure recorded.' })).toBeVisible()
    })

    await test.step('Only the overlapping request changes; other bookings and both parent events are unchanged', async () => {
      const bookings = await expectPreserved(request, fixture)
      expect(bookings).toHaveLength(2)
      expect(bookings.find(booking => booking.id === fixture.affectedBookingId)).toMatchObject({
        eventId: fixture.eventId, venueId: fixture.closedVenueId, status: 'Rejected',
        closureRejection: { closureId, reason: fixture.reason },
      })
    })

    await test.step('Coordinator receives a disruption notification and follows its link to the rejection reason', async () => {
      await coordinator.goto('/notifications')
      const notification = coordinator.getByRole('region', { name: 'Notifications inbox' })
        .getByRole('listitem').filter({ hasText: fixture.eventName }).filter({ hasText: fixture.reason })
      await expect(async () => {
        await coordinator.getByRole('button', { name: 'Refresh notifications' }).click()
        await expect(notification).toHaveCount(1, { timeout: 2_000 })
      }).toPass({ timeout: 120_000, intervals: [1_000, 3_000, 5_000] })
      const link = notification.getByRole('link', { name: 'Open notification' })
      await expect(link).toHaveAttribute('href', `/events/${fixture.eventId}?booking=${fixture.affectedBookingId}`)
      await link.click()
      const rejected = coordinator.locator(`#venue-booking-${fixture.affectedBookingId}`)
      await expect(rejected).toHaveClass(/notification-target/)
      await expect(rejected).toContainText('Rejected due to temporary venue closure')
      await expect(rejected).toContainText(fixture.reason)
      await expect(rejected.getByRole('button', { name: 'Edit booking' })).toHaveCount(0)
      await expect(coordinator.locator(`#venue-booking-${fixture.keptBookingId}`)).toContainText('Approved')
    })

    await test.step('Search excludes the closed interval but keeps the free alternative', async () => {
      await coordinator.goto('/venue-search')
      await coordinator.getByLabel('Start date', { exact: false }).fill(fixture.day)
      await coordinator.getByLabel('Start time', { exact: false }).fill('10:30')
      await coordinator.getByLabel('End date', { exact: false }).fill(fixture.day)
      await coordinator.getByLabel('End time', { exact: false }).fill('11:30')
      await coordinator.getByLabel('Expected attendance', { exact: false }).fill('50')
      await coordinator.getByRole('button', { name: 'Search', exact: true }).click()
      await expect(coordinator.getByRole('button', { name: `View details for ${fixture.alternativeVenueName}`, exact: true })).toBeVisible()
      await expect(coordinator.getByRole('button', { name: `View details for ${fixture.closedVenueName}`, exact: true })).toHaveCount(0)
      await coordinator.getByLabel('Start time', { exact: false }).fill('12:00')
      await coordinator.getByLabel('End time', { exact: false }).fill('13:00')
      await coordinator.getByRole('button', { name: 'Search', exact: true }).click()
      await expect(coordinator.getByRole('button', { name: `View details for ${fixture.closedVenueName}`, exact: true })).toBeVisible()
    })

    await test.step('Calendar shows the closed period and its operational reason on that date', async () => {
      await coordinator.goto('/venue-availability')
      await coordinator.locator('.calendar-venue-picker summary').click()
      await coordinator.getByRole('button', { name: 'Deselect all' }).click()
      await coordinator.getByLabel(fixture.closedVenueName, { exact: true }).check()
      await coordinator.locator('.calendar-jump summary').click()
      await coordinator.getByLabel('Anchor date').fill(fixture.day)
      const day = coordinator.getByRole('button', { name: `Open ${fixture.day}`, exact: true })
      await expect(day).toContainText('Closed')
      await day.click()
      const closure = coordinator.locator('.calendar-days .calendar-closed')
      await expect(closure).toHaveCount(1)
      await closure.getByText('Closure details', { exact: true }).click()
      await expect(closure).toContainText(fixture.reason)
      await expect(closure).toContainText(`${fixture.day} 10:30`)
      await expect(closure).toContainText(`${fixture.day} 11:30`)
      await expectPreserved(request, fixture)
    })
  })
})
