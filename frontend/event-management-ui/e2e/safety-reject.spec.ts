import type { Page } from '@playwright/test'
import { allUsers, asUser, json, makeEvent, mock, test, expect, users } from './fixtures'

// SCRUM-151: a Safety Officer rejects an event's Operational Safety Check.
// Every backend call is mocked (see fixtures.ts), so this needs no running
// services.

const pending = makeEvent({
  id: 'evt-041',
  eventName: 'Safety Reject Expo',
  status: 'Pending Safety Check',
  actionHistory: [{
    status: 'Pending Safety Check',
    details: 'Submitted for Operational Safety Check (round 1).',
    coordinatorId: users.coordinator.user_id,
    safetyCheckId: 'record-041',
    recordedAt: '2026-11-01T02:30:00+00:00',
  }],
})

type MockApi = (page: Page) => Promise<void>

async function openAsSafetyOfficer(page: Page, mockApi: MockApi, events: Record<string, unknown>[]) {
  await mockApi(page)
  await asUser(page, users.safetyOfficer.user_id)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await mock(page, 'event', '/events', (route) => json(route, { events }))
  for (const event of events) {
    await mock(page, 'event', `/events/${event.id}`, (route) => json(route, event))
  }
}

test('AC3, AC4, AC5: rejecting with a reason and confirming cancels the event', async ({ page, mockApi }) => {
  const rejections: Record<string, unknown>[] = []
  await openAsSafetyOfficer(page, mockApi, [pending])
  await mock(page, 'event', `/events/${pending.id}`, (route) => json(
    route,
    rejections.length === 0
      ? pending
      : { ...pending, status: 'Cancelled' },
  ))
  await mock(page, 'safetyCheck', '/safety-checks/reject', (route) => {
    rejections.push(route.request().postDataJSON())
    return json(route, {
      safetyCheck: { id: 'record-041', roundNumber: 1, status: 'Safety Rejected', decidedBy: users.safetyOfficer.user_id, decidedAt: '2026-11-02T03:00:00+00:00', remarks: 'Unsafe egress plan.' },
      event: { ...pending, status: 'Cancelled' },
      release: { venueBookingsReleased: ['booking-evt-041'], venueBookingsNotReleased: [], equipment: 'Released.' },
    })
  })

  await page.goto(`/events/${pending.id}`)
  await expect(page.getByRole('heading', { name: 'Safety Reject Expo' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Operational Safety Check' })).toBeVisible()

  await page.getByRole('button', { name: 'Reject' }).click()
  await page.getByLabel('Reason').fill('Unsafe egress plan.')
  await page.getByRole('button', { name: 'Reject' }).click()
  await expect(page.getByText(/Reject and cancel this event\?/)).toBeVisible()
  await page.getByRole('button', { name: 'Yes, reject and cancel' }).click()

  await expect(page.locator('.status-badge').first()).toContainText('Cancelled')
  expect(rejections.at(-1)).toMatchObject({
    eventId: pending.id,
    safetyOfficerId: users.safetyOfficer.user_id,
    reason: 'Unsafe egress plan.',
    confirmed: true,
  })
})

test('AC3: the Reject button stays disabled until a reason is entered', async ({ page, mockApi }) => {
  await openAsSafetyOfficer(page, mockApi, [pending])

  await page.goto(`/events/${pending.id}`)
  await expect(page.getByRole('heading', { name: 'Operational Safety Check' })).toBeVisible()

  await page.getByRole('button', { name: 'Reject' }).click()
  await expect(page.getByRole('button', { name: 'Reject' })).toBeDisabled()

  await page.getByLabel('Reason').fill('Unsafe egress plan.')
  await expect(page.getByRole('button', { name: 'Reject' })).toBeEnabled()
})
