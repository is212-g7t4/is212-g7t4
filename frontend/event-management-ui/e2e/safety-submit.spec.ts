import type { Page } from '@playwright/test'
import { allUsers, asUser, json, makeEvent, mock, mockSafetyReadiness, test, expect, users, venues } from './fixtures'

// SCRUM-149: an Event Coordinator submits their Approved event for its
// Operational Safety Check. Every backend call is mocked (see fixtures.ts), so
// this needs no running services.

const approved = makeEvent({ id: 'evt-020', eventName: 'Safety Submit Expo', status: 'Approved' })
const pending = makeEvent({
  id: 'evt-021',
  eventName: 'Safety Submitted Expo',
  status: 'Pending Safety Check',
  actionHistory: [{
    status: 'Pending Safety Check',
    details: 'Submitted for Operational Safety Check (round 1).',
    coordinatorId: users.coordinator.user_id,
    recordedAt: '2026-11-01T02:30:00+00:00',
  }],
})

const outstanding = [
  {
    type: 'venue', id: 'booking-020', status: 'Pending Review',
    label: 'Booking 1 Dec 2026 09:00–17:00 (100 people)',
    reason: 'Waiting for Venue Staff approval.',
  },
]

type MockApi = (page: Page) => Promise<void>

async function openEvent(page: Page, mockApi: MockApi, event: Record<string, unknown>) {
  await mockApi(page)
  await asUser(page, users.coordinator.user_id)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await mock(page, 'venue', '/venues', (route) => json(route, { venues }))
  await mock(page, 'event', '/events', (route) => json(route, { events: [event] }))
  await mock(page, 'event', `/events/${event.id}`, (route) => json(route, event))
  await mock(page, 'venueBooking', `/events/${event.id}/booking-requests`, (route) => json(route, { bookings: [] }))
  if (event.status === 'Approved') {
    await mock(page, 'attendeeRegistration', `/events/${event.id}/registrations`, (route) => json(route, { registrations: [] }))
  }
}

test('AC2: outstanding arrangements are listed and the submit button is disabled', async ({ page, mockApi }) => {
  await openEvent(page, mockApi, approved)
  await mockSafetyReadiness(page, { ready: false, outstanding })
  await page.goto('/my-events')

  await page.getByRole('button', { name: /Safety Submit Expo/ }).click()
  await expect(page.getByRole('heading', { name: 'Safety Submit Expo' })).toBeVisible()

  await expect(page.getByRole('heading', { name: 'Before you can submit for a safety check' })).toBeVisible()
  await expect(page.getByText('Booking 1 Dec 2026 09:00–17:00 (100 people)')).toBeVisible()
  await expect(page.getByText('Waiting for Venue Staff approval.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Submit for safety check' })).toBeDisabled()
})

test('AC1, AC3: a ready event is submitted with notes and becomes Pending Safety Check', async ({ page, mockApi }) => {
  const submitted: Record<string, unknown>[] = []
  await openEvent(page, mockApi, approved)
  await mockSafetyReadiness(page)
  // The page reloads the event after a successful submission, so reads after
  // that return it at its new status.
  await mock(page, 'event', `/events/${approved.id}`, (route) => json(
    route,
    submitted.length === 0
      ? approved
      : { ...approved, status: 'Pending Safety Check', actionHistory: pending.actionHistory },
  ))
  await mock(page, 'safetyCheck', '/safety-checks', (route) => {
    submitted.push(route.request().postDataJSON())
    return json(route, {
      safetyCheck: { id: 'record-020', roundNumber: 1, status: 'Pending', submittedAt: '2026-11-01T02:30:00+00:00' },
      event: { ...approved, status: 'Pending Safety Check' },
    }, 201)
  })
  await page.goto('/my-events')

  await page.getByRole('button', { name: /Safety Submit Expo/ }).click()
  await expect(page.getByRole('heading', { name: 'Submit for safety check' })).toBeVisible()

  await page.getByLabel('Equipment placement notes').fill('Speakers either side of the stage.')
  await page.getByLabel('Expected crowd movement notes').fill('Entry through Door A, exit through Doors B and C.')
  await page.getByRole('button', { name: 'Submit for safety check' }).click()

  await expect(page.locator('.status-badge').first()).toContainText('Pending Safety Check')
  expect(submitted.at(-1)).toMatchObject({
    eventId: approved.id,
    coordinatorId: users.coordinator.user_id,
    equipmentPlacementNotes: 'Speakers either side of the stage.',
    crowdMovementNotes: 'Entry through Door A, exit through Doors B and C.',
  })
})

test('AC4: an event already waiting shows when it was submitted, with no submit button', async ({ page, mockApi }) => {
  await openEvent(page, mockApi, pending)
  await page.goto('/my-events')

  await page.getByRole('button', { name: /Safety Submitted Expo/ }).click()
  await expect(page.getByRole('heading', { name: 'Safety Submitted Expo' })).toBeVisible()

  await expect(page.getByText(/Submitted for safety check on/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Submit for safety check' })).toHaveCount(0)
})
