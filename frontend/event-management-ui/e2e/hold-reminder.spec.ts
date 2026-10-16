import { allUsers, asUser, json, mock, test, expect, users, venues } from './fixtures'

test('coordinator sees an alert naming the venue and expiry of a hold due within 3 days', async ({ page, mockApi }) => {
  await mockApi(page)
  await asUser(page, users.coordinator.user_id)
  await mock(page, 'user', '/users', route => json(route, { users: allUsers }))
  await mock(page, 'venue', '/venues', route => json(route, { venues }))
  await mock(page, 'availability', '/venue-holds/reminders', route => json(route, {
    reminders: [{ id: 'h1', venueId: venues[0].id, createdAt: '2026-10-16T09:00:00', expiresAt: '2026-10-19T12:00:00', heldBy: users.venueStaff.user_id }],
  }))
  await page.goto('/')
  const alert = page.getByRole('alert').filter({ hasText: 'Grand Hall' })
  await expect(alert).toContainText('expires on')
  await expect(alert).toContainText('19 Oct 2026')
})
