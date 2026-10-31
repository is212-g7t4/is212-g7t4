import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { deleteFixtureEvents } from '../../../helpers/cleanup'
import { authHeaders, createUnderReviewEvent, openAs, randomWindow, requestEquipment, serviceUrl, users } from '../../../helpers/stack'
import {
  approveJ3Booking,
  approveJ3Event,
  bookingServiceUrl,
  createJ3Booking,
  createJ3Venue,
  equipmentRequestServiceUrl,
  openJ3SafetyEvent,
  submitJ3SafetyCheck,
  TABLE_ID,
  TABLE_NAME,
  TABLE_STOCK,
} from '../helpers/seed'

/**
 * J3C — Reject an unsafe event, release its reservations, and retain its history.
 *
 * Requires the real stack (`npm run dev`), the seeded Supabase accounts and
 * `E2E_PASSWORD` (or per-role password variables) set.
 *
 * Journey ticket: SCRUM-257 (E2E Testing J3).
 *
 * Stories this journey exercises:
 *   - SCRUM-151 Reject or Request Changes to Safety Arrangements
 *
 * Stories the fixture setup relies on:
 *   - SCRUM-8   seeded user accounts for role-based sign-in
 *   - SCRUM-11  Event Submission Form (event creation through the service API)
 *   - SCRUM-28/29 Venue Booking Request and Review
 *   - SCRUM-31/32/33/34 Equipment Catalogue, Request, Review and Availability
 *   - SCRUM-149 Submit Event for Operational Safety Check
 *   - SCRUM-159 Assign Coordinator to an Event
 */
test.describe.configure({ mode: 'serial', timeout: 360_000 })

test.describe('J3C safety rejection cancels the event and releases its resources', () => {
  const runId = randomUUID()
  const rejectedName = `J3c Event rejected ${runId}`
  const nextName = `J3c Event next ${runId}`
  const venueName = `J3c Venue ${runId}`
  const scope = { eventNames: [rejectedName, nextName], venueNames: [venueName] }
  const window = randomWindow()
  let rejectedEventId = ''
  let nextEventId = ''
  let venueId = ''
  let originalBookingId = ''
  let canCleanup = false

  test.beforeAll(async ({ playwright }) => {
    canCleanup = true
    const api = await playwright.request.newContext()
    try {
      venueId = await createJ3Venue(api, venueName)
      rejectedEventId = await createUnderReviewEvent(api, rejectedName, window)
      nextEventId = await createUnderReviewEvent(api, nextName, window)
      originalBookingId = await createJ3Booking(api, rejectedEventId, venueId, window)
      await approveJ3Booking(api, originalBookingId)
      await requestEquipment(api, rejectedEventId, TABLE_ID, 40)
      const approvedEquipment = await api.patch(
        serviceUrl('reservation', `/equipment-reservations/events/${rejectedEventId}`),
        { headers: await authHeaders(users.techSupport), data: { status: 'Approved' } },
      )
      expect(approvedEquipment.ok(), `approve original equipment: ${approvedEquipment.status()} ${await approvedEquipment.text()}`).toBe(true)
      await requestEquipment(api, nextEventId, TABLE_ID, 20)
      await approveJ3Event(api, rejectedEventId)
      await submitJ3SafetyCheck(api, rejectedEventId)
    } finally {
      await api.dispose()
    }
  })

  test.afterAll(async () => {
    if (canCleanup) await deleteFixtureEvents(scope)
  })

  test('Safety Officer rejection cancels permanently and lets another event reserve the released venue and equipment', async ({ browser, request }) => {
    const coordinator = await openAs(browser, users.coordinator)
    const officer = await openAs(browser, users.safetyOfficer)
    const technicalSupport = await openAs(browser, users.techSupport)
    const rejectionReason = 'Emergency egress cannot be made safe for this event.'

    await test.step('Before rejection, the approved venue and equipment reservation block the next event', async () => {
      await coordinator.goto(`/events/${nextEventId}`)
      const form = coordinator.locator('form.venue-booking-form')
      await form.getByRole('combobox').selectOption(venueId)
      await form.getByLabel('Booking start').fill(window.start)
      await form.getByLabel('Booking end').fill(window.end)
      await form.getByRole('button', { name: 'Submit venue booking' }).click()
      await expect(coordinator.getByRole('alert')).toContainText('An approved booking overlaps this time.')
      await expect(coordinator.getByText('No venue booking requests yet.')).toBeVisible()

      await technicalSupport.goto('/equipment-requests')
      const nextEquipment = technicalSupport.getByRole('region', { name: `${nextName} equipment requests` })
        .getByRole('row').filter({ hasText: TABLE_NAME })
      await expect(nextEquipment).toContainText('Pending')
      await expect(nextEquipment).toContainText('Insufficient')
      await expect(nextEquipment.getByRole('button', { name: 'Approve', exact: true })).toBeDisabled()
      await expect(nextEquipment).toContainText(String(TABLE_STOCK - 40))
    })

    await test.step('Safety Officer rejects with a reason and the event is permanently Cancelled', async () => {
      await openJ3SafetyEvent(officer, rejectedName)
      await officer.getByRole('button', { name: 'Reject', exact: true }).click()
      const dialog = officer.getByRole('dialog', { name: 'Reject and cancel this event?' })
      await dialog.getByLabel('Reason for rejection').fill(rejectionReason)
      await dialog.getByRole('button', { name: 'Confirm rejection' }).click()
      await expect(officer.getByRole('heading', { name: rejectedName })).toBeVisible()
      await expect(officer.locator('.event-card-header .status-badge').first()).toHaveText('Cancelled')

      const eventRead = await request.get(
        serviceUrl('event', `/events/${rejectedEventId}?coordinatorId=${users.coordinator.id}`),
        { headers: await authHeaders(users.coordinator) },
      )
      expect(eventRead.status()).toBe(200)
      const cancelled = await eventRead.json()
      expect(cancelled.status).toBe('Cancelled')
      expect(cancelled.actionHistory).toEqual(expect.arrayContaining([
        expect.objectContaining({ status: 'Cancelled', remarks: rejectionReason }),
      ]))

      const safetyHistory = await request.get(
        serviceUrl('safety', `/safety-checks/feedback?eventId=${rejectedEventId}&coordinatorId=${users.coordinator.id}`),
        { headers: await authHeaders(users.coordinator) },
      )
      expect(safetyHistory.status()).toBe(200)
      expect(await safetyHistory.json()).toMatchObject({
        safetyChecks: [{ status: 'Safety Rejected', remarks: rejectionReason }],
      })

      const venueHistory = await request.get(
        bookingServiceUrl(`/events/${rejectedEventId}/booking-requests?coordinatorId=${users.coordinator.id}`),
        { headers: await authHeaders(users.coordinator) },
      )
      expect(venueHistory.status()).toBe(200)
      expect(await venueHistory.json()).toMatchObject({
        bookings: [{ id: originalBookingId, status: 'Cancelled', venueName }],
      })

      const progress = await request.patch(serviceUrl('event', `/events/${rejectedEventId}/progress`), {
        headers: await authHeaders(users.coordinator),
        data: { status: 'Confirmed', actionDetails: 'Attempt to progress a rejected event.' },
      })
      expect(progress.status()).toBe(409)
      expect(await progress.json()).toMatchObject({ code: 'SAFETY_APPROVAL_REQUIRED' })

      const resubmit = await request.post(serviceUrl('safety', '/safety-checks/resubmit'), {
        headers: await authHeaders(users.coordinator),
        data: { eventId: rejectedEventId, equipmentPlacementNotes: 'Attempt to reopen a rejected event.' },
      })
      expect(resubmit.status()).toBe(409)
      expect(await resubmit.json()).toMatchObject({
        code: 'EVENT_NOT_READY_FOR_SAFETY_CHECK',
        currentStatus: 'Cancelled',
      })
    })

    await test.step('The next event can now obtain the released venue and equipment', async () => {
      await coordinator.goto(`/events/${nextEventId}`)
      const form = coordinator.locator('form.venue-booking-form')
      await form.getByRole('combobox').selectOption(venueId)
      await form.getByLabel('Booking start').fill(window.start)
      await form.getByLabel('Booking end').fill(window.end)
      await form.getByRole('button', { name: 'Submit venue booking' }).click()
      await expect(form.getByRole('status')).toContainText(`${venueName} booking request submitted`)
      const nextBookings = await request.get(
        bookingServiceUrl(`/events/${nextEventId}/booking-requests?coordinatorId=${users.coordinator.id}`),
        { headers: await authHeaders(users.coordinator) },
      )
      expect(nextBookings.status()).toBe(200)
      expect(await nextBookings.json()).toMatchObject({
        bookings: [expect.objectContaining({ venueId, status: 'Pending Review' })],
      })

      await technicalSupport.goto('/equipment-requests')
      const nextEquipment = technicalSupport.getByRole('region', { name: `${nextName} equipment requests` })
        .getByRole('row').filter({ hasText: TABLE_NAME })
      await expect(nextEquipment).not.toContainText('Insufficient')
      await expect(nextEquipment.getByRole('button', { name: 'Approve', exact: true })).toBeEnabled()
      await nextEquipment.getByRole('button', { name: 'Approve', exact: true }).click()
      await expect(nextEquipment).toContainText('Approved')

      const retainedEquipment = await request.get(
        equipmentRequestServiceUrl(`/equipment-requests?eventId=${rejectedEventId}`),
        { headers: await authHeaders(users.techSupport) },
      )
      expect(retainedEquipment.status()).toBe(200)
      expect(await retainedEquipment.json()).toMatchObject({
        requests: [expect.objectContaining({ status: 'Approved' })],
      })
    })
  })
})
