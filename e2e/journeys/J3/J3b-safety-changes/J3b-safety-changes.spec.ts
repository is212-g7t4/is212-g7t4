import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { deleteFixtureEvents } from '../../../helpers/cleanup'
import { authHeaders, openAs, randomWindow, serviceUrl, users } from '../../../helpers/stack'
import {
  approveVenueRequestAsStaff,
  createJ3ReadyEvent,
  createJ3Venue,
  openJ3SafetyEvent,
  submitJ3SafetyCheck,
  TABLE_NAME,
} from '../helpers/seed'

/**
 * J3B — Revise one flagged arrangement, preserve the unflagged one, and pass a new review round.
 *
 * Requires the real stack (`npm run dev`), the seeded Supabase accounts and
 * `E2E_PASSWORD` (or per-role password variables) set.
 *
 * Journey ticket: SCRUM-257 (E2E Testing J3).
 *
 * Stories this journey exercises:
 *   - SCRUM-151 Reject or Request Changes to Safety Arrangements
 *   - SCRUM-164 Revise Arrangements and Resubmit for Safety Check
 *   - SCRUM-150 Approve Operational Safety Check
 *
 * Stories the fixture setup relies on:
 *   - SCRUM-8   seeded user accounts for role-based sign-in
 *   - SCRUM-11  Event Submission Form (event creation through the service API)
 *   - SCRUM-28/29 Venue Booking Request and Review
 *   - SCRUM-31/32/33 Equipment Catalogue, Request and Review
 *   - SCRUM-149 Submit Event for Operational Safety Check
 *   - SCRUM-159 Assign Coordinator to an Event
 */
test.describe.configure({ mode: 'serial', timeout: 360_000 })

test.describe('J3B revise flagged arrangements and resubmit', () => {
  const runId = randomUUID()
  const eventName = `J3b Event ${runId}`
  const venueName = `J3b Venue ${runId}`
  const scope = { eventNames: [eventName], venueNames: [venueName] }
  const window = randomWindow()
  let fixture: { eventId: string; bookingId: string }
  let venueId = ''
  let canCleanup = false

  test.beforeAll(async ({ playwright }) => {
    canCleanup = true
    const api = await playwright.request.newContext()
    try {
      venueId = await createJ3Venue(api, venueName)
      fixture = await createJ3ReadyEvent(api, eventName, venueId, window)
      await submitJ3SafetyCheck(api, fixture.eventId)
    } finally {
      await api.dispose()
    }
  })

  test.afterAll(async () => {
    if (canCleanup) await deleteFixtureEvents(scope)
  })

  test('one flagged venue returns for review; approved equipment remains confirmed through round two', async ({ browser, request }) => {
    const officer = await openAs(browser, users.safetyOfficer)
    const coordinator = await openAs(browser, users.coordinator)
    const venueStaff = await openAs(browser, users.venueStaff)
    const technicalSupport = await openAs(browser, users.techSupport)
    const changeReason = 'The current exit route is too narrow for safe evacuation.'
    const requestedChange = 'Widen the west exit route and keep the doorway clear.'

    await test.step('Safety Officer flags only the venue arrangement and records the reason', async () => {
      await openJ3SafetyEvent(officer, eventName)
      await officer.getByRole('button', { name: 'Request changes', exact: true }).click()
      await officer.getByLabel('Venue arrangement').check()
      await officer.getByLabel('Change needed for Venue arrangement').fill(requestedChange)
      await officer.getByLabel('Reason').fill(changeReason)
      const changesResponse = officer.waitForResponse((response) =>
        new URL(response.url()).pathname === '/safety-checks/request-changes'
        && response.request().method() === 'POST')
      await officer.getByRole('button', { name: 'Request changes', exact: true }).click()
      const response = await changesResponse
      expect(response.status(), await response.text()).toBe(200)
      await expect(officer.locator('.event-card-header .status-badge').first()).toHaveText('Safety Changes Requested')
    })

    await test.step('Coordinator sees the feedback; the flagged booking returns to planning while equipment remains approved', async () => {
      await coordinator.goto(`/events/${fixture.eventId}`)
      const feedback = coordinator.getByRole('region', { name: 'Safety Officer feedback' })
      await expect(feedback).toContainText('Changes Requested')
      await expect(feedback).toContainText(changeReason)
      await expect(feedback).toContainText(requestedChange)
      await expect(feedback).toContainText('Venue arrangement')

      const booking = coordinator.locator('.venue-booking-item').filter({ hasText: venueName })
      await expect(booking).toContainText('Pending Review')
      await booking.getByRole('button', { name: 'Edit booking' }).click()
      const bookingForm = coordinator.locator('form.venue-booking-form')
      await bookingForm.getByLabel('Venue requirements').fill('J3B revision: keep the west exit route unobstructed.')
      await bookingForm.getByRole('button', { name: 'Save venue booking' }).click()
      await expect(bookingForm.getByRole('status')).toContainText('booking updated and returned to pending review')

      await technicalSupport.goto('/equipment-requests')
      const equipment = technicalSupport.getByRole('region', { name: `${eventName} equipment requests` })
        .getByRole('row').filter({ hasText: TABLE_NAME })
      await expect(equipment).toContainText('Approved')
    })

    await test.step('Venue Staff review the revised booking; only then can the Coordinator resubmit', async () => {
      await approveVenueRequestAsStaff(venueStaff, eventName, venueName)
      await coordinator.reload()
      await expect(coordinator.getByRole('button', { name: 'Resubmit Safety Check' })).toBeEnabled()
      await coordinator.getByRole('button', { name: 'Resubmit Safety Check' }).click()
      await expect(coordinator.locator('.event-card-header .status-badge').first()).toHaveText('Pending Safety Check')
    })

    await test.step('Safety Officer sees the preserved round-one feedback and approves round two', async () => {
      await openJ3SafetyEvent(officer, eventName)
      await expect(officer.getByRole('heading', { name: 'Round 1 · Changes Requested' })).toBeVisible()
      await expect(officer.getByText(changeReason, { exact: true })).toBeVisible()
      await expect(officer.getByText(requestedChange, { exact: true })).toBeVisible()
      await officer.getByRole('button', { name: 'Approve', exact: true }).click()
      await officer.getByRole('button', { name: 'Yes, approve' }).click()
      await expect(officer.locator('.event-card-header .status-badge').first()).toHaveText('Confirmed')

      const rounds = await request.get(
        serviceUrl('safety', `/safety-checks/feedback?eventId=${fixture.eventId}&coordinatorId=${users.coordinator.id}`),
        { headers: await authHeaders(users.coordinator) },
      )
      expect(rounds.status()).toBe(200)
      const history = (await rounds.json()).safetyChecks
      expect(history).toHaveLength(2)
      expect(history).toEqual(expect.arrayContaining([
        expect.objectContaining({ roundNumber: 1, status: 'Changes Requested' }),
        expect.objectContaining({ roundNumber: 2, status: 'Safety Approved' }),
      ]))
    })
  })
})
