import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { deleteFixtureEvents } from '../../../helpers/cleanup'
import {
  authHeaders,
  createUnderReviewEvent,
  openAs,
  randomWindow,
  requestEquipment,
  serviceUrl,
  users,
} from '../../../helpers/stack'
import {
  approveVenueRequestAsStaff,
  createJ3Booking,
  createJ3Venue,
  openJ3SafetyEvent,
  TABLE_ID,
} from '../helpers/seed'

/**
 * J3A — Block premature safety review and confirm the normal path recovers.
 *
 * Requires the real stack (`npm run dev`), the seeded Supabase accounts and
 * `E2E_PASSWORD` (or per-role password variables) set.
 *
 * Journey ticket: SCRUM-257 (E2E Testing J3).
 *
 * Stories this journey exercises:
 *   - SCRUM-149 Submit Event for Operational Safety Check
 *   - SCRUM-152 Block Preparation Until Safety Approval
 *   - SCRUM-19  Update Event Status
 *
 * Stories the fixture setup relies on:
 *   - SCRUM-8   seeded user accounts for role-based sign-in
 *   - SCRUM-11  Event Submission Form (event creation through the service API)
 *   - SCRUM-159 Assign Coordinator to an Event
 *   - SCRUM-28/29 Venue Booking Request and Review
 *   - SCRUM-32/33/34 Equipment Request and Review (a rejected request is non-blocking)
 */
test.describe.configure({ mode: 'serial', timeout: 240_000 })

test.describe('J3A pending arrangements block premature safety review', () => {
  const runId = randomUUID()
  const eventName = `J3a Event ${runId}`
  const venueName = `J3a Venue ${runId}`
  const scope = { eventNames: [eventName], venueNames: [venueName] }
  const window = randomWindow()
  let eventId = ''
  let venueId = ''
  let bookingId = ''
  let canCleanup = false

  test.beforeAll(async ({ playwright }) => {
    canCleanup = true
    const api = await playwright.request.newContext()
    try {
      venueId = await createJ3Venue(api, venueName)
      eventId = await createUnderReviewEvent(api, eventName, window)
      bookingId = await createJ3Booking(api, eventId, venueId, window)
      await requestEquipment(api, eventId, TABLE_ID, 1)
    } finally {
      await api.dispose()
    }
  })

  test.afterAll(async () => {
    if (canCleanup) await deleteFixtureEvents(scope)
  })

  test('pending arrangements block submission; once resolved the event reaches Confirmed through safety approval', async ({ browser, request }) => {
    const coordinator = await openAs(browser, users.coordinator)
    const venueStaff = await openAs(browser, users.venueStaff)
    const officer = await openAs(browser, users.safetyOfficer)

    await test.step('Coordinator approves the event but a pending venue request blocks safety submission', async () => {
      await coordinator.goto(`/events/${eventId}`)
      await coordinator.getByLabel('Status').selectOption('Approved')
      await coordinator.getByLabel('Action details').fill('J3A planning review completed.')
      await coordinator.getByRole('button', { name: 'Save progress' }).click()
      await expect(coordinator.locator('.event-card-header .status-badge').first()).toHaveText('Approved')

      await expect(coordinator.getByRole('heading', { name: 'Before you can submit for a safety check' })).toBeVisible()
      await expect(coordinator.getByText(venueName, { exact: true })).toBeVisible()
      await expect(coordinator.getByRole('button', { name: 'Submit for safety check' })).toBeDisabled()

      const premature = await request.post(serviceUrl('safety', '/safety-checks'), {
        headers: await authHeaders(users.coordinator),
        data: { eventId, equipmentPlacementNotes: 'Must not create a review round.' },
      })
      expect(premature.status()).toBe(422)
      const readiness = await premature.json()
      expect(readiness.code).toBe('ARRANGEMENTS_OUTSTANDING')
      expect(readiness.outstanding).toEqual(expect.arrayContaining([
        expect.objectContaining({ type: 'venue', id: bookingId, status: 'Pending Review' }),
        expect.objectContaining({ type: 'equipment', status: 'Pending' }),
      ]))

      const preparation = await request.patch(serviceUrl('event', `/events/${eventId}/progress`), {
        headers: await authHeaders(users.coordinator),
        data: { status: 'Confirmed', actionDetails: 'Attempt to bypass safety approval.' },
      })
      expect(preparation.status()).toBe(409)
      expect(await preparation.json()).toMatchObject({ code: 'SAFETY_APPROVAL_REQUIRED' })
      await expect(coordinator.locator('.event-card-header .status-badge').first()).toHaveText('Approved')
    })

    await test.step('A rejected equipment request is non-blocking under SCRUM-149; Venue Staff approve the required venue', async () => {
      const rejectedEquipment = await request.patch(
        serviceUrl('reservation', `/equipment-reservations/events/${eventId}`),
        {
          headers: await authHeaders(users.techSupport),
          data: { status: 'Rejected', rejectionReason: 'Not required for this fixture.' },
        },
      )
      expect(rejectedEquipment.ok(), `reject equipment request: ${rejectedEquipment.status()} ${await rejectedEquipment.text()}`).toBe(true)

      await approveVenueRequestAsStaff(venueStaff, eventName, venueName)
    })

    await test.step('Coordinator submits the now-ready event, and the Safety Officer approves it', async () => {
      await coordinator.reload()
      await expect(coordinator.getByRole('button', { name: 'Submit for safety check' })).toBeEnabled()
      await coordinator.getByLabel('Equipment placement notes').fill('No equipment is required for this event.')
      await coordinator.getByRole('button', { name: 'Submit for safety check' }).click()
      await expect(coordinator.locator('.event-card-header .status-badge').first()).toHaveText('Pending Safety Check')

      await openJ3SafetyEvent(officer, eventName)
      await officer.getByRole('button', { name: 'Approve', exact: true }).click()
      await officer.getByRole('button', { name: 'Yes, approve' }).click()
      await expect(officer.locator('.event-card-header .status-badge').first()).toHaveText('Confirmed')

      const finalEvent = await request.get(
        serviceUrl('event', `/events/${eventId}?coordinatorId=${users.coordinator.id}`),
        { headers: await authHeaders(users.coordinator) },
      )
      expect(finalEvent.status()).toBe(200)
      expect(await finalEvent.json()).toMatchObject({ status: 'Confirmed', coordinatorId: users.coordinator.id })
    })
  })
})
