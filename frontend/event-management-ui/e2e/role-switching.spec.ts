import { allUsers, asUser, json, mock, switchUser, test, expect, users } from './fixtures'

test.beforeEach(async ({ page, mockApi }) => {
  await mockApi(page)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await mock(page, 'venue', '/venues', (route) => json(route, { venues: [] }))
})

test('sidebar and role pill follow the user being viewed', async ({ page }) => {
  await asUser(page, users.organiser.user_id)
  await page.goto('/')
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await expect(page.getByRole('heading', { name: 'Hi Olivia, any events for today?' })).toBeVisible()
  await expect(nav.getByRole('button', { name: 'Venues', exact: true })).toHaveCount(0)
  await expect(nav.getByRole('button', { name: 'Venue availability calendar' })).toHaveCount(0)

  await switchUser(page, users.lead)
  await expect(page.getByRole('heading', { name: 'Hi Alice, any events for today?' })).toBeVisible()
  await expect(nav.getByRole('button', { name: 'Venues', exact: true })).toBeVisible()
  await expect(nav.getByRole('button', { name: 'Venue availability calendar' })).toBeVisible()
})

test('attendee is denied the venue availability calendar', async ({ page }) => {
  await asUser(page, users.attendee.user_id)
  await page.goto('/venue-availability')
  await expect(page.getByRole('alert')).toContainText('Permission denied')
})
