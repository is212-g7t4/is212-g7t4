/** SCRUM-45 AC4/DR4: replacement and earlier assignment render independently
 * and link to the same organiser event details. Mocked APIs, not delivery proof.
 */
import { test, expect, mock, json, asUser, allUsers, users, makeEvent } from './fixtures'

const eventId = '30000000-0000-0000-0000-000000000001'
const aliceMessage = 'Alice Tan has been assigned to coordinate Community Workshop.'
const bobMessage = 'Bob Lim has been assigned to coordinate Community Workshop.'
const bob = { ...users.coordinator, user_id: 'u-bob', username: 'Bob Lim' }

test('reassignment keeps historical name in bell and inbox and opens current event', async ({ page, mockApi }) => {
  await mockApi(page)
  await mock(page, 'user', '/users', route => json(route, { users: [...allUsers, bob] }))
  const writes: unknown[] = []
  let read = false
  const items = () => [
    { id: 'n-bob', eventId, type: 'event.coordinator-assignment',
      createdAt: '2026-10-21T02:00:00Z', readAt: read ? '2026-10-21T03:00:00Z' : null,
      payload: { message: bobMessage, destination: { kind: 'event-details', eventId },
        details: { eventName: 'Community Workshop', coordinatorName: 'Bob Lim', coordinatorId: bob.user_id } } },
    { id: 'n-alice', eventId, type: 'event.coordinator-assignment',
      createdAt: '2026-10-21T01:00:00Z', readAt: '2026-10-21T01:30:00Z',
      payload: { message: aliceMessage, destination: { kind: 'event-details', eventId },
        details: { eventName: 'Community Workshop', coordinatorName: 'Alice Tan', coordinatorId: users.lead.user_id } } },
  ]
  await mock(page, 'notification', '/notifications', route => json(route, { notifications: items(), nextCursor: null }))
  await mock(page, 'notification', '/notifications/unread-count', route => json(route, { unreadCount: read ? 0 : 1 }))
  await mock(page, 'notification', '/notifications/n-bob', route => {
    writes.push(route.request().postDataJSON()); read = true
    return json(route, { notification: items()[0] })
  })
  await mock(page, 'event', `/events/${eventId}`, route => json(route, makeEvent({ id: eventId,
    eventName: 'Community Workshop', status: 'Under Review', organiserId: users.organiser.user_id,
    coordinatorId: bob.user_id })))
  await asUser(page, users.organiser.user_id)
  await page.goto('/')
  await page.getByRole('button', { name: 'Notifications, 1 unread', exact: true }).click()
  await expect(page.getByText(bobMessage, { exact: true })).toBeVisible()
  await expect(page.getByText(aliceMessage, { exact: true })).toBeVisible()
  expect(writes).toEqual([])
  await page.getByRole('button', { name: 'View all notifications' }).click()
  await expect(page).toHaveURL('/notifications')
  await expect(page.getByText(bobMessage, { exact: true })).toBeVisible()
  await expect(page.getByText(aliceMessage, { exact: true })).toBeVisible()
  await page.getByRole('listitem').filter({ hasText: bobMessage }).getByRole('link', { name: 'Open notification' }).click()
  await expect(page).toHaveURL(`/events/${eventId}`)
  await expect(page.getByRole('heading', { name: 'Community Workshop', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Notifications, 0 unread', exact: true })).toBeVisible()
  expect(writes).toEqual([{ read: true }])
})
