/** SCRUM-45 AC1/AC3: mocked browser seam, not real persistence evidence. */
import { test, expect, mock, json, asUser, allUsers, users, makeEvent } from './fixtures'
const eventId = '30000000-0000-0000-0000-000000000001'
test('organiser bell and inbox open event-only decision details with recorded approval', async ({ page, mockApi }) => {
  await mockApi(page)
  await mock(page, 'user', '/users', route => json(route, { users: allUsers }))
  await mock(page, 'attendeeRegistration', `/events/${eventId}/registrations`, route => json(route, { registrations: [] }))
  let read = false
  const item = () => ({ id: 'n-approval', eventId, type: 'event.approval',
    createdAt: '2026-10-21T01:00:00Z', readAt: read ? '2026-10-21T02:00:00Z' : null,
    payload: { message: 'Community Workshop was approved',
      destination: { kind: 'event-details', eventId }, details: { eventName: 'Community Workshop', decision: 'Approved' } } })
  await mock(page, 'notification', '/notifications', route => json(route, { notifications: [item()], nextCursor: null }))
  await mock(page, 'notification', '/notifications/unread-count', route => json(route, { unreadCount: read ? 0 : 1 }))
  await mock(page, 'notification', '/notifications/n-approval', route => { read = true; return json(route, { notification: item() }) })
  await mock(page, 'event', `/events/${eventId}`, route => json(route, makeEvent({ id: eventId,
    eventName: 'Community Workshop', status: 'Approved', organiserId: users.organiser.user_id,
    decision: { status: 'Approved', reason: null, decidedAt: '2026-10-21T01:00:00Z' } })))
  await asUser(page, users.organiser.user_id)
  await page.goto('/notifications')
  await expect(page.getByText('Community Workshop was approved')).toBeVisible()
  await page.getByRole('link', { name: 'Open notification' }).click()
  await expect(page).toHaveURL(`/events/${eventId}`)
  await expect(page.getByText('Approved', { exact: true })).toBeVisible()
  await expect(page.locator('.event-footnote')).toContainText('Approved on')
  await expect(page.getByText('Total registrations', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Rejection reason' })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Community Workshop', exact: true })).toBeVisible()
  expect(read).toBe(true)
  await page.getByRole('button', { name: 'Notifications, 0 unread', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Open notification' })).toBeVisible()
})
