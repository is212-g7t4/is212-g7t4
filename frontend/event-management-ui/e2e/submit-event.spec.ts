import { allUsers, asUser, json, makeEvent, mock, test, expect, users, venues } from './fixtures'

test.beforeEach(async ({ page, mockApi }) => {
  await mockApi(page)
  await asUser(page, users.organiser.user_id)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await mock(page, 'venue', '/venues', (route) => json(route, { venues }))
})

test('organiser submits an event request', async ({ page }) => {
  let posted: Record<string, string> | undefined
  await mock(page, 'event', '/events', (route) => {
    posted = route.request().postDataJSON()
    return json(route, makeEvent({ eventName: posted?.eventName }), 201)
  })
  await page.goto('/events/new')

  await page.getByRole('button', { name: 'Submit Request' }).click()
  const missing = page.getByRole('dialog', { name: 'Missing Required Fields' })
  await expect(missing).toContainText('Event Name')
  await missing.getByRole('button', { name: 'OK' }).click()

  await page.getByLabel(/Event Name/).fill('Design Workshop')
  await page.getByLabel(/Description/).fill('Hands-on workshop')
  await page.getByLabel(/Purpose/).fill('Teach design thinking')
  await page.getByLabel(/Preferred Start Date/).fill('2026-12-01T09:00')
  await page.getByLabel(/Preferred End Date/).fill('2026-12-01T17:00')
  await page.getByLabel(/Expected Attendance/).fill('40')
  await page.getByRole('button', { name: 'Submit Request' }).click()

  await expect(page.getByRole('dialog', { name: 'Event Submitted' })).toContainText('Design Workshop')
  expect(posted).toMatchObject({ eventName: 'Design Workshop', expectedAttendance: '40' })
  await page.getByRole('button', { name: 'OK' }).click()
  await expect(page.getByRole('status')).toContainText('Status: Submitted')
})

test('shows the service error when submission is rejected', async ({ page }) => {
  await mock(page, 'event', '/events', (route) => json(route, { message: 'Venue is unavailable.' }, 409))
  await page.goto('/events/new')
  await page.getByLabel(/Event Name/).fill('Design Workshop')
  await page.getByLabel(/Description/).fill('d')
  await page.getByLabel(/Purpose/).fill('p')
  await page.getByLabel(/Preferred Start Date/).fill('2026-12-01T09:00')
  await page.getByLabel(/Preferred End Date/).fill('2026-12-01T17:00')
  await page.getByLabel(/Expected Attendance/).fill('40')
  await page.getByRole('button', { name: 'Submit Request' }).click()
  await expect(page.getByRole('dialog', { name: 'Submission Failed' })).toContainText('Venue is unavailable.')
})
