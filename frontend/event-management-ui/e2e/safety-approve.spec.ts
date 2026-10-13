import type { Page } from '@playwright/test'
import { allUsers, asUser, json, makeEvent, mock, test, expect, users } from './fixtures'

// SCRUM-150: a Safety Officer approves an event's Operational Safety Check.
// Every backend call is mocked (see fixtures.ts), so this needs no running
// services.

const pending = makeEvent({
  id: 'evt-030',
  eventName: 'Safety Approve Expo',
  status: 'Pending Safety Check',
  actionHistory: [{
    status: 'Pending Safety Check',
    details: 'Submitted for Operational Safety Check (round 1).',
    coordinatorId: users.coordinator.user_id,
    safetyCheckId: 'record-030',
    recordedAt: '2026-11-01T02:30:00+00:00',
  }],
})

const approvedAlready = makeEvent({
  id: 'evt-031',
  eventName: 'Already Approved Expo',
  status: 'Approved',
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

test('AC1, AC2: approving a pending event moves it to Confirmed and records the decision', async ({ page, mockApi }) => {
  const approvals: Record<string, unknown>[] = []
  await openAsSafetyOfficer(page, mockApi, [pending])
  // The page reloads the event after a successful approval, so reads after
  // that return it at its new status.
  await mock(page, 'event', `/events/${pending.id}`, (route) => json(
    route,
    approvals.length === 0
      ? pending
      : { ...pending, status: 'Confirmed' },
  ))
  await mock(page, 'safetyCheck', '/safety-checks/approve', (route) => {
    approvals.push(route.request().postDataJSON())
    return json(route, {
      safetyCheck: { id: 'record-030', roundNumber: 1, status: 'Safety Approved', decidedBy: users.safetyOfficer.user_id, decidedAt: '2026-11-02T03:00:00+00:00', remarks: 'Looks safe.' },
      event: { ...pending, status: 'Confirmed' },
    })
  })

  await page.goto('/safety-checks')
  await expect(page.getByText('Events waiting for an Operational Safety Check decision.')).toBeVisible()

  await page.getByRole('button', { name: /Safety Approve Expo/ }).click()
  await expect(page.getByRole('heading', { name: 'Safety Approve Expo' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Operational Safety Check' })).toBeVisible()

  await page.getByLabel('Remarks').fill('Looks safe.')
  await page.getByRole('button', { name: 'Approve' }).click()
  await expect(page.getByText(/It will move to Confirmed/)).toBeVisible()
  await page.getByRole('button', { name: 'Yes, approve' }).click()

  await expect(page.locator('.status-badge').first()).toContainText('Confirmed')
  expect(approvals.at(-1)).toMatchObject({
    eventId: pending.id,
    safetyOfficerId: users.safetyOfficer.user_id,
    remarks: 'Looks safe.',
  })
})

test('AC3: an Approved event shows no Approve button', async ({ page, mockApi }) => {
  await openAsSafetyOfficer(page, mockApi, [approvedAlready])

  await page.goto(`/events/${approvedAlready.id}`)
  await expect(page.getByRole('heading', { name: 'Already Approved Expo' })).toBeVisible()

  await expect(page.getByRole('heading', { name: 'Operational Safety Check' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Approve' })).toHaveCount(0)
})
