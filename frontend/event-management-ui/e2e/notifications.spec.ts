/**
 * # SCRUM-173 — Receive Venue Disruption Notifications
 *
 * As an Event Coordinator, I want to receive an in-app notification when a venue booking for an event assigned to me is affected, so that I know that alternative arrangements are required.
 * AC1: Given a rejection is ready for notification, then the notification is addressed to the coordinator assigned to that event when the notification is created.
 * AC2: The notification contains the event name, affected venue, closure start/end, rejection reason, and a link to the venue rejection.
 * AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.
 *
 * ## AC2 direct / supporting UI access and recovery
 * Mocked browser contract, not AC1 selection or real AC3 persistence evidence.
 */
/**
 * # SCRUM-173 mocked browser seam — AC2 full content and exact rejection link.
 * All APIs mocked by shared fixture: proves UI routing/accessibility, NOT persistence.
 * Separate real-browser harness verifies actual services, queue and PostgreSQL.
 */
import { test, expect, mock, json, asUser, allUsers, users, venues, makeEvent } from './fixtures'
const eventId = '30000000-0000-0000-0000-000000000001'
const bookingId = '40000000-0000-0000-0000-000000000001'
const item = { id: 'n1', type: 'venue.closure-rejection', eventId, createdAt: '2026-10-17T01:00:00Z', readAt: null as string | null, payload: { message: 'Frozen disruption', destination: { kind: 'event-venue-request', eventId, bookingId }, details: { eventName: 'Historic conference', venueName: 'Historic hall', startDateTime: '2099-01-01T00:00:00Z', endDateTime: '2099-01-02T00:00:00Z', reason: 'Maintenance\nOperational safety' } } }
test('bell opens without reading; click focuses exact rejected request; unread and identity isolation', async ({ page, mockApi }) => {
 await mockApi(page)
 await mock(page, 'user', '/users', route => json(route, { users: allUsers }))
 let read = false, writes = 0
 await mock(page, 'notification', '/notifications', route => json(route, { notifications: route.request().headers()['x-dev-user-id'] === users.coordinator.user_id ? [{ ...item, readAt: read ? '2026-10-17T02:00:00Z' : null }] : [], nextCursor: null }))
 await mock(page, 'notification', '/notifications/unread-count', route => json(route, { unreadCount: route.request().headers()['x-dev-user-id'] === users.coordinator.user_id && !read ? 1 : 0 }))
 await mock(page, 'notification', '/notifications/n1', route => { writes++; read = route.request().postDataJSON().read; return json(route, { notification: { ...item, readAt: read ? '2026-10-17T02:00:00Z' : null } }) })
 await mock(page, 'event', `/events/${eventId}`, route => json(route, makeEvent({ id: eventId, status: 'Under Review' })))
 await mock(page, 'venue', '/venues', route => json(route, { venues }))
 await mock(page, 'venueBooking', `/events/${eventId}/booking-requests`, route => json(route, { bookings: [
   { id: '40000000-0000-0000-0000-000000000002', venueName: 'Other room', eventId, venueId: venues[1].id, status: 'Pending Review', requestedStartTime: '2099-01-01T09:00', requestedEndTime: '2099-01-01T12:00', requiredCapacity: 10, venueRequirements: '' },
   { id: bookingId, eventId, venueId: venues[0].id, venueName: 'Grand Hall', status: 'Rejected', requestedStartTime: '2099-01-01T09:00', requestedEndTime: '2099-01-01T12:00', requiredCapacity: 20, venueRequirements: 'Stage', closureRejection: { closureId: 'closure', startDateTime: '2099-01-01T00:00:00Z', endDateTime: '2099-01-02T00:00:00Z', reason: 'Maintenance\nOperational safety' } },
 ] }))
 await asUser(page, users.coordinator.user_id)
 await page.goto('/')
 await page.getByRole('button', { name: 'Notifications, 1 unread', exact: true }).click()
 await expect(page.getByText('1 Jan 2099, 08:00 SGT – 2 Jan 2099, 08:00 SGT', { exact: true })).toBeVisible()
 expect(writes).toBe(0)
 await page.getByRole('link', { name: 'Open notification' }).click()
 await expect(page).toHaveURL(`/events/${eventId}?booking=${bookingId}`)
 const target = page.locator(`#venue-booking-${bookingId}`)
 await expect(target).toHaveClass(/notification-target/)
 await expect(target).toBeFocused()
 await expect(target.getByText('Rejected', { exact: true })).toBeVisible()
 await expect(target.getByText('Maintenance\nOperational safety', { exact: true })).toBeVisible()
 await page.getByRole('button', { name: 'Notifications, 0 unread', exact: true }).click()
 await page.getByRole('button', { name: 'View all notifications' }).click()
 await expect(page).toHaveURL('/notifications')
 await page.getByRole('button', { name: 'Mark unread' }).click()
 await expect(page.getByRole('button', { name: 'Notifications, 1 unread', exact: true })).toBeVisible()
 await page.getByLabel('Select active user').selectOption(users.attendee.user_id)
 await expect(page.getByText('No notifications yet.', { exact: true })).toBeVisible()
 await expect(page.getByText('Historic conference')).toHaveCount(0)
})

test('inaccessible event keeps notification read and renders ordinary permission fallback', async ({ page, mockApi }) => {
 await mockApi(page)
 await mock(page, 'user', '/users', route => json(route, { users: allUsers }))
 let read = false
 await mock(page, 'notification', '/notifications', route => json(route, { notifications: [{ ...item, readAt: read ? '2026-10-17T02:00:00Z' : null }], nextCursor: null }))
 await mock(page, 'notification', '/notifications/unread-count', route => json(route, { unreadCount: read ? 0 : 1 }))
 await mock(page, 'notification', '/notifications/n1', route => { read = true; return json(route, { notification: { ...item, readAt: '2026-10-17T02:00:00Z' } }) })
 await mock(page, 'event', `/events/${eventId}`, route => json(route, { message: 'Event not found or access denied.' }, 404))
 await asUser(page, users.coordinator.user_id); await page.goto('/notifications')
 await page.getByRole('link', { name: 'Open notification' }).click()
 await expect(page.getByRole('alert')).toContainText('Event not found or access denied.')
 expect(read).toBe(true)
 await page.getByRole('button', { name: 'Notifications, 0 unread', exact: true }).click()
 await expect(page.getByText('Historic conference')).toBeVisible()
 await expect(page.getByRole('button', { name: 'Mark unread' })).toBeVisible()
})

for (const scenario of [
 { name: 'cancelled assigned event', status: 'Cancelled', viewer: users.coordinator.user_id, assigned: users.coordinator.user_id },
 { name: 'viewable reassigned Lead event', status: 'Under Review', viewer: users.lead.user_id, assigned: users.coordinator.user_id },
]) test(`linked request fallback and legacy null card: ${scenario.name}`, async ({ page, mockApi }) => {
 await mockApi(page)
 await mock(page, 'user', '/users', route => json(route, { users: allUsers }))
 let read = false
 const notice = () => ({ ...item, createdAt: null, readAt: read ? '2026-10-17T02:00:00Z' : null })
 await mock(page, 'notification', '/notifications', route => json(route, { notifications: [notice()], nextCursor: null }))
 await mock(page, 'notification', '/notifications/unread-count', route => json(route, { unreadCount: read ? 0 : 1 }))
 await mock(page, 'notification', '/notifications/n1', route => { read = true; return json(route, { notification: notice() }) })
 await mock(page, 'event', `/events/${eventId}`, route => json(route, makeEvent({ id: eventId, status: scenario.status, coordinatorId: scenario.assigned })))
 await asUser(page, scenario.viewer); await page.goto('/notifications')
 await expect(page.locator('small').filter({ hasText: 'Date unavailable' })).toBeVisible()
 await expect(page.getByText(/1970/)).toHaveCount(0)
 await page.getByRole('link', { name: 'Open notification' }).click()
 await expect(page).toHaveURL(`/events/${eventId}?booking=${bookingId}`)
 await expect(page.getByRole('heading', { name: 'Tech Conference', exact: true })).toBeVisible()
 await expect(page.getByRole('status').filter({ hasText: 'The linked venue request is unavailable or you do not have access to it.' })).toBeVisible()
 await expect(page.locator(`#venue-booking-${bookingId}`)).toHaveCount(0)
 await expect(page.getByRole('button', { name: 'Edit details', exact: true })).toHaveCount(0)
 expect(read).toBe(true)
 await page.getByRole('button', { name: 'Notifications, 0 unread', exact: true }).click()
 await expect(page.getByText('Historic conference', { exact: true })).toBeVisible()
 await expect(page.getByRole('button', { name: 'Mark unread', exact: true })).toBeVisible()
})
