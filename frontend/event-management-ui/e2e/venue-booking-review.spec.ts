/**
 * SCRUM-29 Venue Booking Review and Decision (mocked browser).
 *
 * As a Venue Staff member, I want to review and decide on a pending venue booking
 * request, so that I can determine whether the requested venue arrangement can be
 * accepted and provide the Event Coordinator with the outcome.
 *
 * Every backend call is mocked: these prove the UI sends and shows the right
 * things, not the backend rules (those are in each service's tests).
 */
import type { Page } from '@playwright/test'
import { allUsers, asUser, json, makeEvent, mock, test, expect, users, venues } from './fixtures'

const event = makeEvent({ id: 'evt-029', eventName: 'Harbour Lights Gala', status: 'Under Review', expectedAttendance: '150',
  preferredStartDate: '2026-12-01T09:00', preferredEndDate: '2026-12-01T23:00', venueRequirements: 'Stage', accessibilityNeeds: 'Ramp' })
const REASON = 'Ballroom is booked for maintenance that evening.'

const booking = (id: string, venueName: string, status = 'Pending Review', extra: Record<string, unknown> = {}) => ({
  id, eventId: event.id, venueId: venues[0].id, venueName, requestedStartTime: '2026-12-01T18:00:00',
  requestedEndTime: '2026-12-01T22:00:00', requiredCapacity: 150, venueRequirements: 'Stage and dance floor', status,
  requestedBy: users.coordinator.user_id, reviewedBy: null, requestedAt: '2026-11-02T02:00:00+00:00',
  reviewedAt: null as string | null, rejectionReason: null as string | null, safetyFeedback: null, ...extra,
})

async function staffQueue(page: Page, mockApi: (page: Page) => Promise<void>) {
  const state: Record<string, ReturnType<typeof booking>> = {
    'booking-a': booking('booking-a', 'Grand Hall'),
    'booking-b': booking('booking-b', 'Meeting Room'),
  }
  await mockApi(page)
  await asUser(page, users.venueStaff.user_id)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await mock(page, 'venueBooking', '/booking-requests', (route) => json(route, { events: [{
    eventId: event.id, eventName: event.eventName, eventStatus: 'Under Review', coordinatorId: users.coordinator.user_id,
    eventStart: '2026-12-01T09:00:00', eventEnd: '2026-12-01T23:00:00', bookings: Object.values(state),
  }] }))
  for (const id of Object.keys(state)) {
    await mock(page, 'venueBooking', `/booking-requests/${id}`, (route) => json(route, {
      booking: { ...state[id], awaitingReview: true, occupiedFrom: '2026-12-01T17:30:00', occupiedTo: '2026-12-01T22:45:00' },
      event: { id: event.id, eventName: event.eventName, status: 'Under Review', coordinatorId: users.coordinator.user_id,
        preferredStartDate: '2026-12-01T09:00:00', preferredEndDate: '2026-12-01T23:00:00', expectedAttendance: '150',
        venueRequirements: 'Stage', accessibilityNeeds: 'Ramp' },
      venue: { id: venues[0].id, name: state[id].venueName, capacity: 200, status: 'Available', setupTimeMinutes: 30, turnaroundTimeMinutes: 45 },
      canDecide: true, decisionBlockedReason: null,
    }))
    await mock(page, 'venueBooking', `/booking-requests/${id}/review`, (route) => {
      const body = route.request().postDataJSON()
      state[id] = { ...state[id], status: body.status, reviewedBy: body.reviewedBy, reviewedAt: '2026-11-03T02:00:00+00:00',
        rejectionReason: body.rejectionReason ?? null }
      return json(route, state[id])
    })
  }
  return state
}
test('AC1: Venue Staff open a request and see the event timing, attendance and requirements', async ({ page, mockApi }) => {
  await staffQueue(page, mockApi)
  await page.goto('/venue-requests')
  await page.getByRole('row').filter({ hasText: 'Grand Hall' }).getByRole('button', { name: 'Review' }).click()

  const dialog = page.getByRole('dialog', { name: 'Grand Hall for Harbour Lights Gala' })
  await expect(dialog.getByText('Tue, 1 Dec · 9:00 am – 11:00 pm')).toBeVisible()
  await expect(dialog.getByText('Ramp')).toBeVisible()
  await expect(dialog.getByText('Stage', { exact: true })).toBeVisible()
  await expect(dialog.getByText('150 of 200')).toBeVisible()
  await expect(dialog.getByText('Tue, 1 Dec · 5:30 pm – 10:45 pm')).toBeVisible()
  await expect(dialog.getByText('Stage and dance floor')).toBeVisible()
})

test('AC2/AC5: approving records the outcome and the request is no longer awaiting review', async ({ page, mockApi }) => {
  await staffQueue(page, mockApi)
  await page.goto('/venue-requests')
  await expect(page.getByText('2 awaiting review')).toBeVisible()
  const row = page.getByRole('row').filter({ hasText: 'Grand Hall' })
  await row.getByRole('button', { name: 'Review' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Approve', exact: true }).click()

  await expect(page.getByRole('status')).toHaveText('Venue request approved.')
  await expect(row.locator('.status-badge')).toHaveText('Approved')
  await expect(row.getByText('Approved on 3 Nov 2026, 10:00 am')).toBeVisible()
  await expect(row.getByRole('button', { name: 'Review' })).toHaveCount(0)
  await expect(page.getByText('1 awaiting review')).toBeVisible()
})

test('AC3/AC4/AC5: rejecting needs a reason, which is recorded with the outcome', async ({ page, mockApi }) => {
  const state = await staffQueue(page, mockApi)
  await page.goto('/venue-requests')
  const row = page.getByRole('row').filter({ hasText: 'Meeting Room' })
  await row.getByRole('button', { name: 'Review' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Reject', exact: true }).click()

  const confirm = page.getByRole('button', { name: 'Confirm rejection' })
  await expect(confirm).toBeDisabled()
  await page.getByLabel(/Reason for rejection/).fill(REASON)
  await confirm.click()

  await expect(row.locator('.status-badge')).toHaveText('Rejected')
  await expect(row.getByText('Rejected on 3 Nov 2026, 10:00 am')).toBeVisible()
  await expect(row.getByTitle(REASON)).toBeVisible()
  expect(state['booking-b'].rejectionReason).toBe(REASON)
})

test('AC6: the Event Coordinator sees the rejection reason and can request a replacement', async ({ page, mockApi }) => {
  await mockApi(page)
  await asUser(page, users.coordinator.user_id)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await mock(page, 'event', '/events', (route) => json(route, { events: [event] }))
  await mock(page, 'event', `/events/${event.id}`, (route) => json(route, event))
  await mock(page, 'venue', '/venues', (route) => json(route, { venues }))
  await mock(page, 'venueBooking', `/events/${event.id}/booking-requests`, (route) => json(route, { bookings: [
    booking('booking-b', 'Meeting Room', 'Rejected', { reviewedBy: users.venueStaff.user_id,
      reviewedAt: '2026-11-03T02:00:00+00:00', rejectionReason: REASON, closureRejection: null }),
  ] }))

  await page.goto('/my-events')
  await page.getByRole('button', { name: /Harbour Lights Gala/ }).click()

  const card = page.locator('article').filter({ hasText: 'Meeting Room' })
  await expect(card.getByText('Rejected by Venue Staff')).toBeVisible()
  await expect(card.getByText(REASON)).toBeVisible()
  await expect(card.getByText('3 Nov 2026, 10:00 SGT')).toBeVisible()
  await expect(card.getByText('Rejected requests are read-only. Use Add venue booking below to request a replacement.')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Add venue booking' })).toBeVisible()
})
