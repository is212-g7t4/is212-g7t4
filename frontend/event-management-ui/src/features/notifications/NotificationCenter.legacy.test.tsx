/** Legacy approval compatibility: actual card rendering with mocked transport only.
 * Supporting UI contract; no service, broker or database persistence claim.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { NotificationProvider, NotificationsPage } from './NotificationCenter'
import type { InboxItem } from './notifications'
const eventId = '30000000-0000-0000-0000-000000000001'
const user = { id: '10000000-0000-0000-0000-000000000001', role: 'Event Organiser' as const, username: 'A', email: '', organization: '' }
const legacy = (overrides: Partial<InboxItem> = {}): InboxItem => ({ id: 'legacy', type: 'event_approved', eventId, createdAt: null, readAt: null, payload: { eventName: 'Tech Conference 2026' } as InboxItem['payload'], ...overrides })
afterEach(() => vi.unstubAllGlobals())
function start(item: InboxItem, failWrite = false) {
 const navigate = vi.fn()
 let saved = item
 const fetcher = vi.fn(async (url: string, init: RequestInit) => {
  if (init.method === 'PATCH') {
   if (failWrite) throw new Error('offline')
   saved = { ...saved, readAt: JSON.parse(init.body as string).read ? '2026-10-17T02:00:00Z' : null }
   return { ok: true, json: async () => ({ notification: saved }) }
  }
  return { ok: true, json: async () => url.includes('unread-count') ? { unreadCount: saved.readAt ? 0 : 1 } : { notifications: [saved], nextCursor: null } }
 })
 vi.stubGlobal('fetch', fetcher)
 render(<NotificationProvider user={user} onNavigate={navigate}><NotificationsPage /></NotificationProvider>)
 return { fetcher, navigate }
}
test('legacy approval renders its recorded name, status and safe event link without writing on render', async () => {
 const item = legacy(), before = JSON.stringify(item)
 const { fetcher } = start(item)
 await screen.findByText('Your event has been approved.')
 expect(screen.getByText('Tech Conference 2026')).toBeInTheDocument()
 expect(screen.getByRole('link', { name: 'Open notification' })).toHaveAttribute('href', `/events/${eventId}`)
 expect(screen.getByText('Date unavailable · Unread')).toBeInTheDocument()
 expect(fetcher.mock.calls.every(([, init]) => init.method !== 'PATCH')).toBe(true)
 expect(JSON.stringify(item)).toBe(before)
})

test('legacy rejection renders its recorded name and reason without inventing venue or schedule', async () => {
 start(legacy({ type: 'event_rejected', payload: { eventName: 'Charity Gala', reason: 'Venue unavailable on the requested date.' } as InboxItem['payload'] }))
 await screen.findByText('Your event has been rejected.')
 expect(screen.getByText('Charity Gala')).toBeInTheDocument()
 expect(screen.getByText('Venue unavailable on the requested date.')).toHaveClass('notification-reason')
 expect(screen.getByRole('link', { name: 'Open notification' })).toHaveAttribute('href', `/events/${eventId}`)
 expect(document.querySelector('.notification-content-link > span:not(.notification-destination)')).toBeNull()
})

// Existing security/read-lifecycle behavior characterized against legacy rows;
// these checks are not claimed as newly failing RED tests.
test.each(['event.approved', 'event_rejected_extra', 'EVENT_APPROVED', 'future'])('unknown type %s never receives guessed legacy content or links', async type => {
 start(legacy({ type }))
 await screen.findByText('Notification content unavailable.')
 expect(screen.queryByText('Tech Conference 2026')).not.toBeInTheDocument()
 expect(screen.queryByRole('link')).not.toBeInTheDocument()
})
test.each([null, '', '//evil.test', 'javascript:alert(1)', `${eventId}?x=1`, '30000000-0000-0000-0000-00000000000g'])('legacy eventId %j cannot create an unsafe link', async eventId => {
 start(legacy({ eventId }))
 await screen.findByText('Your event has been approved.')
 expect(screen.queryByRole('link')).not.toBeInTheDocument()
 expect(screen.getByText('Destination unavailable.')).toBeInTheDocument()
})
test.each([null, 'https://evil.test', 'javascript:alert(1)', { kind: 'url', url: '//evil.test' }, { kind: 'event-details', eventId: '//evil.test' }])('explicit invalid destination %j is not replaced with a guessed link', async destination => {
 start(legacy({ payload: { eventName: 'Recorded', destination } }))
 await screen.findByText('Recorded')
 expect(screen.queryByRole('link')).not.toBeInTheDocument()
})
test('modern message, details and structured venue destination take precedence over legacy fields', async () => {
 const bookingId = '40000000-0000-0000-0000-000000000001'
 start(legacy({ type: 'event_rejected', payload: { eventName: 'Old name', reason: 'Old reason', message: 'Frozen modern message', details: { eventName: 'Modern name', reason: 'Modern reason', venueName: 'Frozen venue' }, destination: { kind: 'event-venue-request', eventId, bookingId } } }))
 await screen.findByText('Frozen modern message')
 for (const text of ['Modern name', 'Modern reason', 'Frozen venue']) expect(screen.getByText(text)).toBeInTheDocument()
 for (const text of ['Old name', 'Old reason', 'Your event has been rejected.']) expect(screen.queryByText(text)).not.toBeInTheDocument()
 expect(screen.getByRole('link')).toHaveAttribute('href', `/events/${eventId}?booking=${bookingId}`)
})
test('modern event-details destination remains supported for a nonlegacy notification type', async () => {
 start(legacy({ type: 'event.approved', payload: { message: 'Frozen approval', destination: { kind: 'event-details', eventId } } }))
 await screen.findByText('Frozen approval')
 expect(screen.getByRole('link')).toHaveAttribute('href', `/events/${eventId}`)
})
test.each([null, {}, { eventName: 12, reason: { bad: true } }, { eventName: null, reason: [] }])('missing or malformed legacy content %j renders no fabricated details', async payload => {
 start(legacy({ type: 'event_rejected', eventId: null, payload: payload as InboxItem['payload'] }))
 await screen.findByText('Your event has been rejected.')
 expect(document.querySelector('strong')).toBeNull()
 expect(document.querySelector('.notification-reason')).toBeNull()
 expect(screen.queryByRole('link')).not.toBeInTheDocument()
})
test('legacy fields render as plain text, never HTML', async () => {
 const name = '<img src=x onerror=alert(1)>', reason = '<script>alert(1)</script>'
 start(legacy({ type: 'event_rejected', payload: { eventName: name, reason } }))
 await screen.findByText(name)
 expect(screen.getByText(reason)).toBeInTheDocument()
 expect(document.querySelector('img, script')).toBeNull()
})
test.each([false, true])('opening legacy item saves read before navigation (already read: %s)', async alreadyRead => {
 const { navigate, fetcher } = start(legacy({ readAt: alreadyRead ? '2026-10-17T02:00:00Z' : null }))
 await screen.findByText('Your event has been approved.')
 fireEvent.click(screen.getByRole('link'))
 await waitFor(() => expect(navigate).toHaveBeenCalledWith(`/events/${eventId}`))
 const writes = fetcher.mock.calls.filter(([, init]) => init.method === 'PATCH')
 expect(writes).toHaveLength(1)
 expect(JSON.parse(writes[0][1].body as string)).toEqual({ read: true })
 expect(fetcher.mock.invocationCallOrder[fetcher.mock.calls.findIndex(([, init]) => init.method === 'PATCH')]).toBeLessThan(navigate.mock.invocationCallOrder[0])
 await screen.findByRole('button', { name: 'Mark unread' })
 fireEvent.click(screen.getByRole('button', { name: 'Mark unread' }))
 await screen.findByRole('button', { name: 'Mark read' })
 expect(navigate).toHaveBeenCalledOnce()
})
test('failed legacy read write retains unread content and prevents navigation', async () => {
 const { navigate } = start(legacy(), true)
 await screen.findByText('Your event has been approved.')
 fireEvent.click(screen.getByRole('link'))
 await screen.findByRole('alert')
 expect(navigate).not.toHaveBeenCalled()
 expect(screen.getByText('Date unavailable · Unread')).toBeInTheDocument()
 expect(screen.getByRole('button', { name: 'Mark read' })).toBeEnabled()
})
