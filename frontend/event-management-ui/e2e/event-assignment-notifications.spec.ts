/** SCRUM-45 AC4: existing UI renders initial-assignment name/message and
 * navigates to organiser event details. APIs mocked; not backend delivery proof.
 */
import { test, expect, mock, json, asUser, allUsers, users, makeEvent } from './fixtures'
const eventId = '30000000-0000-0000-0000-000000000001'
const message = 'Alice Tan has been assigned to coordinate Community Workshop.'
test('organiser bell and inbox display assigned name and open event details', async ({ page, mockApi }) => {
  await mockApi(page)
  await mock(page, 'user', '/users', route => json(route, { users: allUsers }))
  let read = false
  const writes: unknown[] = []
  const item = () => ({ id: 'n-assignment', eventId, type: 'event.coordinator-assignment',
    createdAt: '2026-10-21T01:00:00Z', readAt: read ? '2026-10-21T02:00:00Z' : null,
    payload: { message, destination: { kind: 'event-details', eventId },
      details: { eventName: 'Community Workshop', coordinatorName: 'Alice Tan', coordinatorId: users.coordinator.user_id } } })
  await mock(page, 'notification', '/notifications', route => json(route, { notifications: [item()], nextCursor: null }))
  await mock(page, 'notification', '/notifications/unread-count', route => json(route, { unreadCount: read ? 0 : 1 }))
  await mock(page, 'notification', '/notifications/n-assignment', route => {
    writes.push(route.request().postDataJSON()); read = true
    return json(route, { notification: item() })
  })
  await mock(page, 'event', `/events/${eventId}`, route => json(route, makeEvent({ id: eventId,
    eventName: 'Community Workshop', status: 'Under Review', organiserId: users.organiser.user_id,
    coordinatorId: users.coordinator.user_id })))
  await asUser(page, users.organiser.user_id)
  await page.goto('/')
  await page.getByRole('button', { name: 'Notifications, 1 unread', exact: true }).click()
  await expect(page.getByText(message, { exact: true })).toBeVisible()
  expect(writes).toEqual([])
  await page.getByRole('button', { name: 'View all notifications' }).click()
  await expect(page).toHaveURL('/notifications')
  await expect(page.getByText(message, { exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Open notification' }).click()
  await expect(page).toHaveURL(`/events/${eventId}`)
  await expect(page.getByRole('heading', { name: 'Community Workshop', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Notifications, 0 unread', exact: true })).toBeVisible()
  expect(writes).toEqual([{ read: true }])
})
