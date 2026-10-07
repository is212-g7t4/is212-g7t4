import { allUsers, asUser, json, makeEvent, mock, test, expect, users, venues } from './fixtures'

const approved = makeEvent({ id: 'evt-002', eventName: 'Hack Night', status: 'Approved', expectedAttendance: '50' })
const registrations = [
  { registration_id: 'r1', event_id: 'evt-002', attendee_id: 'a1', registration_date: '2026-11-03T02:00:00+00:00', status: 'Confirmed', attendee_name: 'Ann Lee', attendee_email: 'ann@example.com', attendee_organization: 'Org X' },
  { registration_id: 'r2', event_id: 'evt-002', attendee_id: 'a2', registration_date: null, status: 'Cancelled', attendee_name: 'Bob Ng', attendee_email: 'bob@example.com', attendee_organization: null },
]

test('coordinator filters events and opens one with registrations', async ({ page, mockApi }) => {
  const queries: URLSearchParams[] = []
  await mockApi(page)
  await asUser(page, users.coordinator.user_id)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await mock(page, 'venue', '/venues', (route) => json(route, { venues }))
  await mock(page, 'event', '/events', (route) => {
    const params = new URL(route.request().url()).searchParams
    queries.push(params)
    return json(route, { events: params.get('status') === 'Approved' ? [approved] : [makeEvent(), approved] })
  })
  await mock(page, 'event', '/events/evt-002', (route) => json(route, approved))
  await mock(page, 'registration', '/registrations', (route) => {
    expect(new URL(route.request().url()).searchParams.get('eventId')).toBe('evt-002')
    return json(route, { registrations })
  })
  await page.goto('/my-events')

  await expect(page.getByRole('button', { name: /Tech Conference/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /Hack Night/ })).toBeVisible()

  await page.getByLabel('Status').selectOption('Approved')
  await page.getByRole('button', { name: 'Apply filters' }).click()
  await expect(page.getByRole('button', { name: /Tech Conference/ })).toHaveCount(0)
  expect(queries.at(-1)?.get('status')).toBe('Approved')

  await page.getByRole('button', { name: /Hack Night/ }).click()
  await expect(page.getByRole('button', { name: 'Back to My events' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Hack Night' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Registrations' })).toBeVisible()
  await expect(page.getByRole('table')).toContainText('Ann Lee')
  await expect(page.getByRole('table')).toContainText('Bob Ng')
  // Capacity 50, one Confirmed registration -> 49 spots left (cancelled ones don't count).
  await expect(page.getByText('Total registrations').locator('..')).toContainText('2')
  await expect(page.getByText('Remaining spots').locator('..')).toContainText('49')

  await page.getByRole('button', { name: 'Back to My events' }).click()
  await expect(page.getByRole('button', { name: /Hack Night/ })).toBeVisible()
})
