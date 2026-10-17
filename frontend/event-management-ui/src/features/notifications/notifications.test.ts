/**
 * # SCRUM-173 — Receive Venue Disruption Notifications
 *
 * As an Event Coordinator, I want to receive an in-app notification when a venue booking for an event assigned to me is affected, so that I know that alternative arrangements are required.
 * AC1: Given a rejection is ready for notification, then the notification is addressed to the coordinator assigned to that event when the notification is created.
 * AC2: The notification contains the event name, affected venue, closure start/end, rejection reason, and a link to the venue rejection.
 * AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.
 *
 * ## AC groups and layer
 * Direct AC2 content/destination and supporting inbox UI/recovery checks.
 * AC1 recipient selection is backend evidence, not inferred from these mocks.
 * AC2 content/navigation; AC3 supporting UI isolation/recovery.
 * FIRST: synthetic independent fixtures, controlled I/O/clocks, automatic assertions.
 * Historical tests are retrospective; no blanket historical TDD claim.
 */
/**
 * # SCRUM-173 API seam — supporting own-inbox UI contract / AC2 destination.
 * Network is mocked; fixtures and clock are fixed. Does not establish persistence.
 * Verify explicit identity, keyset/filter encoding, read write, and safe structured
 * navigation for known destinations even on future notification types.
 */
import { afterEach, expect, test, vi } from 'vitest'
import { notificationApi, notificationDate, notificationPath } from './notifications'
const user = { id: '10000000-0000-0000-0000-000000000001', role: 'Attendee' as const, username: 'A', email: '', organization: '' }
afterEach(() => vi.unstubAllGlobals())
test('own list/count/read use caller identity and opaque pagination, not recipient query', async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ notifications: [], nextCursor: null }) })
  vi.stubGlobal('fetch', fetch)
  await notificationApi(user, '/notifications?'+new URLSearchParams({ limit: '20', unread: 'true', cursor: 'opaque+/=' }))
  // Integration regression: 5014 belongs to SCRUM-20 Event Workflow, not inbox.
  expect(fetch.mock.calls[0][0]).toBe('http://localhost:5015/notifications?limit=20&unread=true&cursor=opaque%2B%2F%3D')
  expect(fetch).toHaveBeenCalledWith(expect.stringContaining('cursor=opaque%2B%2F%3D'), expect.objectContaining({ headers: expect.objectContaining({ 'X-Dev-User-Id': user.id, 'X-Dev-Role': 'Attendee' }) }))
  await notificationApi(user, '/notifications/item', { method: 'PATCH', body: JSON.stringify({ read: false }) })
  expect(fetch).toHaveBeenLastCalledWith(expect.stringContaining('/notifications/item'), expect.objectContaining({ method: 'PATCH', body: '{"read":false}' }))
})
test('structured destinations are independent of future type and never arbitrary URLs', () => {
 const eventId = '30000000-0000-0000-0000-000000000001', bookingId = '40000000-0000-0000-0000-000000000001'
 expect(notificationPath({ kind: 'event-venue-request', eventId, bookingId })).toBe(`/events/${eventId}?booking=${bookingId}`)
 for (const destination of [{ kind: 'url', url: 'javascript:alert(1)' }, { kind: 'event-venue-request', eventId: '//evil.test', bookingId }, null]) expect(notificationPath(destination)).toBeNull()
})
test.each([
 [{ message: 'Temporarily unavailable' }, 'Temporarily unavailable'],
 [{}, 'Unable to load notifications.'],
])('failed API reads are errors, not empty successful inboxes: %j', async (body, expected) => {
 vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: async () => body }))
 await expect(notificationApi(user, '/notifications')).rejects.toThrow(expected)
})

/** Review P3 public formatter: never coerce absent/malformed JSON timestamps into dates. */
test.each([null, undefined, 0, '   ', 'not-a-date'])('notificationDate rejects malformed timestamp %j', (value) => {
 expect(notificationDate(value)).toBe('Date unavailable')
})
test('notificationDate keeps valid timestamps explicitly in Singapore time', () => {
 expect(notificationDate('2026-10-17T01:00:00Z')).toBe('17 Oct 2026, 09:00 SGT')
})
