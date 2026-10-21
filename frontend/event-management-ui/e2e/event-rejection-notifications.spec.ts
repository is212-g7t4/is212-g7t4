/** SCRUM-45 AC2/AC3: mocked browser seam, not real persistence evidence. */
import { test, expect, mock, json, asUser, allUsers, users, makeEvent } from './fixtures'
const eventId = '30000000-0000-0000-0000-000000000001'
const reason = 'The proposal needs a safety plan.\nPlease revise.'
test('organiser bell and inbox open event-only decision details with rejection reason', async ({ page, mockApi }) => {
  await mockApi(page)
  await mock(page, 'user', '/users', route => json(route, { users: allUsers }))
  let read = false
  const item = () => ({ id: 'n-rejection', eventId, type: 'event.rejection',
    createdAt: '2026-10-21T01:00:00Z', readAt: read ? '2026-10-21T02:00:00Z' : null,
    payload: { message: `Community Workshop was rejected: ${reason}`,
      destination: { kind: 'event-details', eventId }, details: { eventName: 'Community Workshop', reason } } })
  await mock(page, 'notification', '/notifications', route => json(route, { notifications: [item()], nextCursor: null }))
  await mock(page, 'notification', '/notifications/unread-count', route => json(route, { unreadCount: read ? 0 : 1 }))
  await mock(page, 'notification', '/notifications/n-rejection', route => { read = true; return json(route, { notification: item() }) })
  await mock(page, 'event', `/events/${eventId}`, route => json(route, makeEvent({ id: eventId,
    eventName: 'Community Workshop', status: 'Rejected', organiserId: users.organiser.user_id,
    decision: { status: 'Rejected', reason } })))
  await asUser(page, users.organiser.user_id)
  await page.goto('/notifications')
  await expect(page.getByText(`Community Workshop was rejected: ${reason}`)).toBeVisible()
  await page.getByRole('link', { name: 'Open notification' }).click()
  await expect(page).toHaveURL(`/events/${eventId}`)
  await expect(page.getByRole('heading', { name: 'Event request decision' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Rejection reason' })).toBeVisible()
  await expect(page.locator('p').filter({ hasText: reason })).toBeVisible()
  expect(read).toBe(true)
  await page.getByRole('button', { name: 'Notifications, 0 unread', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Open notification' })).toBeVisible()
})
