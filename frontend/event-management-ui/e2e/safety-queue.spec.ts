import { allUsers, asUser, json, makeEvent, mock, mockSafetyQueue, test, expect, users, venues } from './fixtures'

// SCRUM-162: a Safety Officer views the events awaiting an Operational Safety
// Check. Every backend call is mocked (see fixtures.ts), so this needs no
// running services.

const november = makeEvent({
  id: 'evt-060',
  eventName: 'November Expo',
  status: 'Pending Safety Check',
  preferredStartDate: '2026-11-12T09:00:00+08:00',
  preferredEndDate: '2026-11-12T17:00:00+08:00',
  expectedAttendance: '150',
  venues: [{ id: venues[0].id, name: venues[0].name }, { id: venues[1].id, name: venues[1].name }],
})

const december = makeEvent({
  id: 'evt-061',
  eventName: 'December Gala',
  status: 'Pending Safety Check',
  preferredStartDate: '2026-12-05T18:00:00+08:00',
  preferredEndDate: '2026-12-05T22:00:00+08:00',
  roundNumber: 2,
  safetySubmittedAt: '2026-11-03T04:00:00+00:00',
})

test('AC1-AC3: the queue lists pending events nearest first, with venues, dates and a resubmission label', async ({ page, mockApi }) => {
  await mockApi(page)
  await asUser(page, users.safetyOfficer.user_id)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  const queueRequests: string[] = []
  await mockSafetyQueue(page, () => [november, december])
  page.on('request', (request) => {
    if (request.url().includes('/safety-checks/queue')) queueRequests.push(request.url())
  })

  await page.goto('/safety-checks')

  const rows = page.locator('.event-row-card')
  await expect(rows).toHaveCount(2)
  await expect(rows.nth(0)).toContainText('November Expo')
  await expect(rows.nth(0)).toContainText('Grand Hall, Meeting Room · 150 attendees')
  await expect(rows.nth(0)).toContainText('Submitted 1 Nov 2026, 10:30 am')
  await expect(rows.nth(0)).not.toContainText('Resubmission')
  await expect(rows.nth(1)).toContainText('December Gala')
  await expect(rows.nth(1)).toContainText('Resubmission')
  await expect(rows.nth(1)).toContainText('Submitted 3 Nov 2026, 12:00 pm')
  expect(queueRequests.at(-1)).toContain(`safetyOfficerId=${users.safetyOfficer.user_id}`)
})
