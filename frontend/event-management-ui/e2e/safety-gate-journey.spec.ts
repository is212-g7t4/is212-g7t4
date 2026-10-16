import { allUsers, asUser, json, makeEvent, mock, test, expect, users, venues } from './fixtures'

// SCRUM-152: ties the gate (PR #38, safety-gate.spec.ts) and the approval
// route (SCRUM-150, PR #54, safety-approve.spec.ts) into one journey, so the
// PR shows this story's whole arc: a coordinator can't skip ahead, and only
// the Safety Officer's approval moves the event to Confirmed.

const pending = makeEvent({
  id: 'evt-050',
  eventName: 'Safety Journey Expo',
  status: 'Pending Safety Check',
  actionHistory: [{
    status: 'Pending Safety Check',
    details: 'Submitted for Operational Safety Check (round 1).',
    coordinatorId: users.coordinator.user_id,
    safetyCheckId: 'record-050',
    recordedAt: '2026-11-01T02:30:00+00:00',
  }],
})

test('SCRUM-152: a coordinator is blocked until the Safety Officer approves, then Confirmed opens up', async ({ page, mockApi }) => {
  const approvals: Record<string, unknown>[] = []
  let current: Record<string, unknown> = pending

  await mockApi(page)
  await asUser(page, users.coordinator.user_id)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await mock(page, 'venue', '/venues', (route) => json(route, { venues }))
  await mock(page, 'venueBooking', `/events/${pending.id}/booking-requests`, (route) => json(route, { bookings: [] }))
  await mock(page, 'event', '/events', (route) => json(route, { events: [current] }))
  await mock(page, 'event', `/events/${pending.id}`, (route) => json(route, current))

  // 1. As the assigned coordinator: no Confirmed option, told to wait.
  await page.goto('/my-events')
  await page.getByRole('button', { name: /Safety Journey Expo/ }).click()
  await expect(page.getByRole('heading', { name: 'Safety Journey Expo' })).toBeVisible()
  await expect(page.getByLabel('Status').getByRole('option', { name: 'Confirmed' })).toHaveCount(0)
  await expect(page.getByRole('note')).toContainText("This event is waiting for the Safety Officer's decision.")

  // 2. Switch to the Safety Officer: open the same event from Safety checks, approve.
  await mock(page, 'safetyCheck', '/safety-checks/approve', (route) => {
    approvals.push(route.request().postDataJSON())
    current = { ...pending, status: 'Confirmed' }
    return json(route, {
      safetyCheck: {
        id: 'record-050', roundNumber: 1, status: 'Safety Approved',
        decidedBy: users.safetyOfficer.user_id, decidedAt: '2026-11-02T03:00:00+00:00',
        remarks: 'Looks safe.',
      },
      event: current,
    })
  })
  // A full navigation would re-run the init script that sets the active
  // user, reverting back to the coordinator, so switch and move around
  // in-app instead of page.goto.
  await page.getByLabel('Select active user').selectOption({ label: 'Nurul Huda — Safety Officer' })
  await page.getByRole('button', { name: 'Safety checks' }).click()
  await expect(page.getByText('Events waiting for an Operational Safety Check decision.')).toBeVisible()
  await page.getByRole('button', { name: /Safety Journey Expo/ }).click()
  await expect(page.getByRole('heading', { name: 'Operational Safety Check' })).toBeVisible()
  await page.getByLabel('Remarks').fill('Looks safe.')
  await page.getByRole('button', { name: 'Approve' }).click()
  await expect(page.getByText(/It will move to Confirmed/)).toBeVisible()
  await page.getByRole('button', { name: 'Yes, approve' }).click()
  await expect(page.locator('.status-badge').first()).toContainText('Confirmed')
  expect(approvals.at(-1)).toMatchObject({
    eventId: pending.id,
    safetyOfficerId: users.safetyOfficer.user_id,
  })

  // 3. Switch back to the coordinator: Confirmed, and the safety note is gone.
  await page.getByLabel('Select active user').selectOption({ label: 'Carl Ng — Event Coordinator' })
  await page.getByRole('button', { name: 'Events', exact: true }).click()
  await page.getByRole('button', { name: /Safety Journey Expo/ }).click()
  await expect(page.getByRole('heading', { name: 'Safety Journey Expo' })).toBeVisible()
  await expect(page.locator('.status-badge').first()).toContainText('Confirmed')
  await expect(page.getByRole('note')).toHaveCount(0)
})
