import { allUsers, asUser, json, makeEvent, mock, test, expect, users } from './fixtures'

const coordinators = [users.lead, users.coordinator].map((user) => ({ ...user, contact_details: '+65 0000 0000' }))

test.beforeEach(async ({ page, mockApi }) => {
  await mockApi(page)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await mock(page, 'assignment', '/coordinators', (route) => json(route, { coordinators }))
})

test('coordinator approves an assigned request', async ({ page }) => {
  let query: URLSearchParams | undefined
  let approveBody: unknown
  await asUser(page, users.coordinator.user_id)
  await mock(page, 'event', '/events/submitted', (route) => {
    query = new URL(route.request().url()).searchParams
    return json(route, { events: [makeEvent()] })
  })
  await mock(page, 'event', '/events/evt-001/approve', (route) => {
    approveBody = route.request().postDataJSON()
    return json(route, makeEvent({ status: 'Approved', decision: { status: 'Approved', coordinatorId: users.coordinator.user_id, decidedAt: '2026-11-02T03:00:00+00:00', reason: null } }))
  })
  await page.goto('/requests/review')

  await expect(page.getByRole('heading', { name: 'Tech Conference' })).toBeVisible()
  expect(query?.get('coordinatorId')).toBe(users.coordinator.user_id)
  expect(query?.has('viewerRole')).toBe(false)

  await page.getByRole('button', { name: 'Approve Request' }).click()
  await expect(page.getByRole('dialog', { name: 'Event Request Approved' })).toContainText('Tech Conference was approved')
  expect(approveBody).toEqual({ coordinatorId: users.coordinator.user_id })
  await page.getByRole('button', { name: 'OK' }).click()
  await expect(page.getByText('No submitted event requests yet.')).toBeVisible()
})

test('rejection needs a reason', async ({ page }) => {
  let rejectBody: unknown
  await asUser(page, users.coordinator.user_id)
  await mock(page, 'event', '/events/submitted', (route) => json(route, { events: [makeEvent()] }))
  await mock(page, 'event', '/events/evt-001/reject', (route) => {
    rejectBody = route.request().postDataJSON()
    return json(route, makeEvent({ status: 'Rejected', decision: { status: 'Rejected', coordinatorId: users.coordinator.user_id, decidedAt: '2026-11-02T03:00:00+00:00', reason: 'Venue clash' } }))
  })
  await page.goto('/requests/review')

  await page.getByRole('button', { name: 'Reject Request' }).click()
  const dialog = page.getByRole('dialog', { name: 'Reject event request?' })
  const confirm = dialog.getByRole('button', { name: 'Confirm rejection' })
  await expect(confirm).toBeDisabled()
  await dialog.getByLabel('Reason for rejection').fill('Venue clash')
  await confirm.click()

  await expect(page.getByRole('dialog', { name: 'Event Request Rejected' })).toContainText('Venue clash')
  expect(rejectBody).toEqual({ coordinatorId: users.coordinator.user_id, reason: 'Venue clash' })
})

test('lead sees the unassigned queue and an assigned event leaves it', async ({ page }) => {
  let queueQuery: URLSearchParams | undefined
  let assignBody: unknown
  await asUser(page, users.lead.user_id)
  await mock(page, 'assignment', '/queue', (route) => {
    queueQuery = new URL(route.request().url()).searchParams
    return json(route, { events: [makeEvent({ coordinatorId: null, organiserId: users.organiser.user_id })] })
  })
  await mock(page, 'assignment', `/events/evt-001/assign-coordinator/${users.coordinator.user_id}`, (route) => {
    assignBody = route.request().postDataJSON()
    return json(route, { eventId: 'evt-001', assignedCoordinatorId: users.coordinator.user_id })
  })
  await page.goto('/requests/queue')

  const row = page.getByRole('row', { name: /Tech Conference/ })
  await expect(row).toContainText(users.organiser.username)
  await expect(row).toContainText('100')
  expect(queueQuery?.get('actingUserId')).toBe(users.lead.user_id)

  await row.getByLabel('Coordinator').selectOption(users.coordinator.user_id)
  await row.getByRole('button', { name: 'Assign' }).click()

  await expect(page.getByRole('status')).toContainText(`Tech Conference was assigned to ${users.coordinator.username}`)
  await expect(page.getByText('No requests are waiting for a coordinator.')).toBeVisible()
  expect(assignBody).toEqual({ actingUserId: users.lead.user_id })
})

test('coordinator cannot see the unassigned queue', async ({ page }) => {
  await asUser(page, users.coordinator.user_id)
  await page.goto('/requests/queue')
  await expect(page.getByText('The unassigned request queue is visible only to the Event Coordinator Lead.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Unassigned requests' })).toHaveCount(0)
})

test('organiser cannot see the unassigned queue', async ({ page }) => {
  await asUser(page, users.organiser.user_id)
  await page.goto('/requests/queue')
  await expect(page.getByText('The unassigned request queue is visible only to the Event Coordinator Lead.')).toBeVisible()
})

test('organiser cannot see the review queue', async ({ page }) => {
  await asUser(page, users.organiser.user_id)
  await page.goto('/requests/review')
  await expect(page.getByText('Submitted event requests are visible to Event Coordinators.')).toBeVisible()
})

test('lead moves between the Events tabs', async ({ page }) => {
  await asUser(page, users.lead.user_id)
  await mock(page, 'assignment', '/queue', (route) => json(route, { events: [] }))
  let reviewQuery: URLSearchParams | undefined
  await mock(page, 'event', '/events/submitted', (route) => {
    reviewQuery = new URL(route.request().url()).searchParams
    return json(route, { events: [] })
  })
  await page.goto('/')

  await page.getByRole('button', { name: 'Events', exact: true }).click()
  await expect(page).toHaveURL(/\/requests\/queue$/)
  await expect(page.getByRole('tab', { name: 'Unassigned requests' })).toHaveAttribute('aria-selected', 'true')

  await page.getByRole('tab', { name: 'Request review' }).click()
  await expect(page).toHaveURL(/\/requests\/review$/)
  await expect(page.getByText('No submitted event requests yet.')).toBeVisible()
  expect(reviewQuery?.get('viewerRole')).toBe('Event Coordinator Lead')
  expect(reviewQuery?.has('isManager')).toBe(false)
})
