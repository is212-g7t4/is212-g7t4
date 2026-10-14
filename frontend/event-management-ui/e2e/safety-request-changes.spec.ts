import type { Page } from '@playwright/test'
import { allUsers, asUser, json, makeEvent, mock, test, expect, users } from './fixtures'

// SCRUM-151: a Safety Officer requests changes to an event's safety
// arrangements. Every backend call is mocked (see fixtures.ts), so this
// needs no running services.

const pending = makeEvent({
  id: 'evt-040',
  eventName: 'Safety Changes Expo',
  status: 'Pending Safety Check',
  actionHistory: [{
    status: 'Pending Safety Check',
    details: 'Submitted for Operational Safety Check (round 1).',
    coordinatorId: users.coordinator.user_id,
    safetyCheckId: 'record-040',
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

test('AC1, AC2: requesting changes on two areas moves the event to Safety Changes Requested', async ({ page, mockApi }) => {
  const requests: Record<string, unknown>[] = []
  await openAsSafetyOfficer(page, mockApi, [pending])
  await mock(page, 'event', `/events/${pending.id}`, (route) => json(
    route,
    requests.length === 0
      ? pending
      : { ...pending, status: 'Safety Changes Requested' },
  ))
  await mock(page, 'safetyCheck', '/safety-checks/request-changes', (route) => {
    requests.push(route.request().postDataJSON())
    return json(route, {
      safetyCheck: { id: 'record-040', roundNumber: 1, status: 'Changes Requested', decidedBy: users.safetyOfficer.user_id, decidedAt: '2026-11-02T03:00:00+00:00', remarks: 'Needs another look.' },
      event: { ...pending, status: 'Safety Changes Requested' },
    })
  })

  await page.goto(`/events/${pending.id}`)
  await expect(page.getByRole('heading', { name: 'Safety Changes Expo' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Operational Safety Check' })).toBeVisible()

  await page.getByRole('button', { name: 'Request changes' }).click()
  await page.getByRole('checkbox', { name: /Venue arrangement/ }).check()
  await page.getByLabel('Change needed for Venue arrangement').fill('Move the stage left of centre.')
  await page.getByRole('checkbox', { name: /Event details/ }).check()
  await page.getByLabel('Change needed for Event details').fill('Fix the clashing start time.')
  await page.getByLabel('Reason').fill('Needs another look.')
  await page.getByRole('button', { name: 'Request changes' }).click()

  await expect(page.locator('.status-badge').first()).toContainText('Safety Changes Requested')
  expect(requests.at(-1)).toMatchObject({
    eventId: pending.id,
    safetyOfficerId: users.safetyOfficer.user_id,
    reason: 'Needs another look.',
    flags: [
      { area: 'venue arrangement', changeRequired: 'Move the stage left of centre.' },
      { area: 'event details', changeRequired: 'Fix the clashing start time.' },
    ],
  })
})

test('AC1: the submit button stays disabled until an area, its change text and a reason are filled', async ({ page, mockApi }) => {
  await openAsSafetyOfficer(page, mockApi, [pending])

  await page.goto(`/events/${pending.id}`)
  await expect(page.getByRole('heading', { name: 'Operational Safety Check' })).toBeVisible()

  await page.getByRole('button', { name: 'Request changes' }).click()
  await expect(page.getByRole('button', { name: 'Request changes' })).toBeDisabled()

  await page.getByRole('checkbox', { name: /Venue arrangement/ }).check()
  await expect(page.getByRole('button', { name: 'Request changes' })).toBeDisabled()

  await page.getByLabel('Change needed for Venue arrangement').fill('Move the stage.')
  await expect(page.getByRole('button', { name: 'Request changes' })).toBeDisabled()

  await page.getByLabel('Reason').fill('Needs another look.')
  await expect(page.getByRole('button', { name: 'Request changes' })).toBeEnabled()
})
