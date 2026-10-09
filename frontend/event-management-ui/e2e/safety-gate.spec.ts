import { allUsers, asUser, json, makeEvent, mock, test, expect, users, venues } from './fixtures'

// SCRUM-152: 'Confirmed' is the preparation stage, and only the safety workflow
// sets it. A coordinator is never offered it — they are told what to do next.

const approved = makeEvent({ id: 'evt-010', eventName: 'Safety Pending Expo', status: 'Approved' })
const confirmed = makeEvent({ id: 'evt-011', eventName: 'Safety Cleared Expo', status: 'Confirmed' })

test('AC1: an approved event is not offered Confirmed, and is told to submit for safety check', async ({ page, mockApi }) => {
  await mockApi(page)
  await asUser(page, users.coordinator.user_id)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await mock(page, 'venue', '/venues', (route) => json(route, { venues }))
  await mock(page, 'event', '/events', (route) => json(route, { events: [approved] }))
  await mock(page, 'event', `/events/${approved.id}`, (route) => json(route, approved))
  // 'Approved' still shows the registrations panel, which is left alone by this story.
  await mock(page, 'registration', '/registrations', (route) => json(route, { registrations: [] }))
  await page.goto('/my-events')

  await page.getByRole('button', { name: /Safety Pending Expo/ }).click()
  await expect(page.getByRole('heading', { name: 'Safety Pending Expo' })).toBeVisible()

  const status = page.getByLabel('Status')
  await expect(status.getByRole('option')).toHaveCount(1)
  await expect(status.getByRole('option', { name: 'Approved' })).toBeAttached()
  await expect(status.getByRole('option', { name: 'Confirmed' })).toHaveCount(0)
  await expect(page.getByRole('note')).toContainText(
    'Submit this event for safety check for it to progress to Confirmed.',
  )
})

// Boundary: the gate must not over-block an event that already passed its check.
test('a confirmed event has reached preparation and can record progress', async ({ page, mockApi }) => {
  const patched: Record<string, unknown>[] = []
  await mockApi(page)
  await asUser(page, users.coordinator.user_id)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await mock(page, 'venue', '/venues', (route) => json(route, { venues }))
  await mock(page, 'event', '/events', (route) => json(route, { events: [confirmed] }))
  await mock(page, 'event', `/events/${confirmed.id}`, (route) => json(route, confirmed))
  await mock(page, 'event', `/events/${confirmed.id}/progress`, (route) => {
    patched.push(route.request().postDataJSON())
    return json(route, { ...confirmed, actionDetails: 'Preparation under way.' })
  })
  await page.goto('/my-events')

  await page.getByRole('button', { name: /Safety Cleared Expo/ }).click()
  await expect(page.getByRole('heading', { name: 'Safety Cleared Expo' })).toBeVisible()

  // Past the gate: no hint, and the status stays put while progress is recorded.
  await expect(page.getByRole('note')).toHaveCount(0)
  await expect(page.getByLabel('Status')).toHaveValue('Confirmed')
  await page.getByLabel('Action details').fill('Preparation under way.')
  await page.getByRole('button', { name: 'Save progress' }).click()

  await expect(page.getByText('Event progress updated successfully.')).toBeVisible()
  expect(patched.at(-1)).toMatchObject({ status: 'Confirmed', actionDetails: 'Preparation under way.' })
  await expect(page.locator('.status-badge')).toContainText('Confirmed')
})
