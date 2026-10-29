/** Seed-backed history presentation; HTTP is mocked, never database delivery.
 * No inferred links: historical event IDs alone do not establish current access.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import type { Role } from '../../types'
import { NotificationProvider, NotificationsPage, NotificationBell } from './NotificationCenter'
import { notificationPayload } from './notifications'
import { signInAs, tokenOf } from '../../test/session'
import type { InboxItem } from './notifications'
const eventId = '30000000-0000-0000-0000-000000000001'
const user = (role: Role) => ({ id: '10000000-0000-0000-0000-000000000001', role, username: '', email: '', organization: '' })
const row = (type: string, payload: object): InboxItem => ({ id: type, type, eventId, createdAt: null, readAt: null, payload })
afterEach(() => vi.unstubAllGlobals())
const cases: [Role, string, object, string, string[]][] = [
 ['Event Coordinator', 'coordinator_assigned', { eventName: 'Assigned event', assignedBy: 'Recorded assigner' }, 'You have been assigned as an event coordinator.', ['Assigned event']],
 ['Event Coordinator', 'venue_booking_rejected', { venueName: 'Recorded venue', reason: 'Recorded rejection' }, 'Your venue booking has been rejected.', ['Recorded venue', 'Recorded rejection']],
 ['Event Coordinator Lead', 'equipment_request_approved', { equipmentType: 'Projector', quantityReserved: 2 }, 'Your equipment request has been approved.', ['Projector', 'Quantity reserved: 2']],
 ['Event Coordinator', 'safety_changes_requested', { eventName: 'Safety event', round: 1, remarks: 'Recorded safety feedback' }, 'Safety changes have been requested for your event.', ['Safety event', 'Recorded safety feedback', 'Safety review round: 1']],
 ['Event Coordinator', 'safety_approved', { eventName: 'Safety event', round: 2 }, 'Your event safety check has been approved.', ['Safety event', 'Safety review round: 2']],
 ['Event Coordinator', 'booking_affected_by_closure', { venueName: 'Closed venue', reason: 'Recorded closure reason', closureStart: '2026-11-25T08:00:00+08:00', closureEnd: '2026-12-06T18:00:00+08:00' }, 'Your venue booking is affected by a venue closure.', ['Closed venue', 'Recorded closure reason', 'Closure period:']],
 ['Attendee', 'registration_confirmed', { eventName: 'Registered event' }, 'Your event registration has been confirmed.', ['Registered event']],
]
test.each(cases)('%s renders seed-backed %s in bell and inbox without guessed links or writes', async (role, type, payload, message, details) => {
 const item = row(type, payload), before = JSON.stringify(item)
 const fetcher = vi.fn(async () => ({ ok: true, json: async () => ({ notifications: [item], nextCursor: null, unreadCount: 1 }) }))
 vi.stubGlobal('fetch', fetcher)
 render(<NotificationProvider user={user(role)} onNavigate={vi.fn()}><NotificationBell onViewAll={vi.fn()} /><NotificationsPage /></NotificationProvider>)
 await screen.findByText(message)
 for (const text of details) expect(screen.getByText(text, { exact: text !== 'Closure period:' })).toBeInTheDocument()
 expect(screen.queryByRole('link')).not.toBeInTheDocument()
 fireEvent.click(screen.getByRole('button', { name: 'Notifications, 1 unread' }))
 expect(screen.getAllByText(message)).toHaveLength(2)
 expect(fetcher.mock.calls.every(args => !((args as unknown as [string, RequestInit])[1]?.method))).toBe(true)
 expect(JSON.stringify(item)).toBe(before)
})
test.each(cases)('modern envelope wins for %s %s', (_role, type, legacy) => {
 const payload = { ...legacy, message: 'Frozen message', details: { eventName: 'Frozen name', reason: 'Frozen reason' }, destination: null }
 const result = notificationPayload(row(type, payload))
 expect(result.message).toBe('Frozen message')
 expect(result.details?.eventName).toBe('Frozen name')
 expect(result.details?.reason).toBe('Frozen reason')
 expect(result.destination).toBeNull()
})
test.each(['coordinator.assigned', 'REGISTRATION_CONFIRMED', 'safety_approved_extra', 'equipment_request_rejected'])('unproven type %s remains untouched', type => {
 const item = row(type, { eventName: 'Do not interpret', reason: 'Do not guess' })
 expect(notificationPayload(item)).toBe(item.payload)
})

test.each([null, {}, { equipmentType: { bad: true }, quantityReserved: -1, round: '2', remarks: [], closureStart: 42, closureEnd: false }])('malformed known history %j renders no invented detail', async payload => {
 const item = row('equipment_request_approved', payload as object)
 vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ notifications: [item], nextCursor: null, unreadCount: 1 }) })))
 render(<NotificationProvider user={user('Event Coordinator Lead')} onNavigate={vi.fn()}><NotificationsPage /></NotificationProvider>)
 await screen.findByText('Your equipment request has been approved.')
 expect(screen.queryByText(/Quantity reserved:/)).not.toBeInTheDocument()
 expect(screen.queryByRole('link')).not.toBeInTheDocument()
})
test.each(['__proto__', 'constructor', 'toString'])('object property %s is not an allowlisted notification type', type => {
 const item = row(type, { eventName: 'Unknown event' })
 expect(notificationPayload(item)).toBe(item.payload)
})
test('closure time is labelled as closure, never invented as the event schedule', () => {
 const result = notificationPayload(row('booking_affected_by_closure', { closureStart: '2026-11-25T08:00:00+08:00', closureEnd: '2026-12-06T18:00:00+08:00', reason: 'Recorded reason' }))
 expect(result.details?.startDateTime).toBeUndefined()
 expect(result.details?.endDateTime).toBeUndefined()
 expect(result.details?.reason).toBe('Recorded reason')
})

test('role switches clear bell, inbox, cursor, filter and late responses, including the same user ID', async () => {
 let resolveOld: (value: unknown) => void = () => {}
 const held = new Promise(resolve => { resolveOld = resolve })
 let hold = false
 const fetcher = vi.fn(async (_url: string, init: RequestInit) => {
  const role = tokenOf(init).replace(/^Bearer \S+ /, '')
  if (role === 'Event Coordinator' && hold) return held
  return { ok: true, json: async () => ({ notifications: role === 'Event Coordinator' ? [row('coordinator_assigned', { eventName: 'Old identity event' })] : [], nextCursor: role === 'Event Coordinator' ? 'old-cursor' : null, unreadCount: role === 'Event Coordinator' ? 1 : 0 }) }
 })
 vi.stubGlobal('fetch', fetcher)
 const ui = (role: Role) => (signInAs(user(role)), <NotificationProvider user={user(role)} onNavigate={vi.fn()}><NotificationBell onViewAll={vi.fn()} /><NotificationsPage /></NotificationProvider>)
 const view = render(ui('Event Coordinator'))
 await screen.findByText('Old identity event')
 fireEvent.click(screen.getByRole('button', { name: 'Notifications, 1 unread' }))
 hold = true
 fireEvent.click(screen.getByRole('checkbox'))
 for (const role of ['Attendee', 'Event Organiser', 'Event Coordinator Lead', 'Venue Staff', 'Technical Support', 'Safety Officer'] as Role[]) {
  view.rerender(ui(role))
  await screen.findByText('No notifications yet.')
  expect(screen.queryByText('Old identity event')).not.toBeInTheDocument()
  expect(screen.getByRole('checkbox')).not.toBeChecked()
  expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Notifications, 0 unread' })).toHaveAttribute('aria-expanded', 'false')
 }
 await act(async () => resolveOld({ ok: true, json: async () => ({ notifications: [row('coordinator_assigned', { eventName: 'Leaked late event' })], nextCursor: 'leaked', unreadCount: 9 }) }))
 await waitFor(() => expect(screen.queryByText('Leaked late event')).not.toBeInTheDocument())
 expect(fetcher.mock.calls.every(([, init]) => !init.method)).toBe(true)
})
