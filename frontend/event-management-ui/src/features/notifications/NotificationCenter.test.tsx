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
 * # SCRUM-173 component seam — AC2 full frozen content and agreed inbox UI.
 * Mock only network, control time. These DOM checks are not PostgreSQL evidence.
 * Opening is not reading; explicit actions and destination links are separate.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { NotificationProvider, NotificationBell, NotificationsPage } from './NotificationCenter'
const A = { id: '10000000-0000-0000-0000-000000000001', role: 'Event Coordinator' as const, username: 'A', email: '', organization: '' }
const B = { ...A, id: '10000000-0000-0000-0000-000000000002', username: 'B' }
const destination = { kind: 'event-venue-request', eventId: '30000000-0000-0000-0000-000000000001', bookingId: '40000000-0000-0000-0000-000000000001' }
const item = { id: 'n1', type: 'venue.closure-rejection', createdAt: '2026-10-17T01:00:00Z', readAt: null, eventId: destination.eventId, payload: { message: 'Frozen message <script>alert(1)</script>', destination, details: { eventName: 'Historic event', venueName: 'Historic hall', startDateTime: '2099-01-01T00:00:00Z', endDateTime: '2099-01-02T00:00:00Z', reason: 'Maintenance\nOperational safety' } } }
let fetcher: ReturnType<typeof vi.fn>
const response = (body: unknown) => ({ ok: true, json: async () => body })
beforeEach(() => {
 fetcher = vi.fn(async (url: string) => response(url.includes('unread-count') ? { unreadCount: 1 } : { notifications: [structuredClone(item)], nextCursor: null }))
 vi.stubGlobal('fetch', fetcher)
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })
const view = (user = A, full = false, navigate = vi.fn()) => <NotificationProvider user={user} onNavigate={navigate}><NotificationBell onViewAll={() => {}} />{full && <NotificationsPage />}</NotificationProvider>
test('opening bell never reads and renders full frozen SGT content as text', async () => {
 render(view()); await screen.findByLabelText('Notifications, 1 unread')
 fireEvent.click(screen.getByLabelText('Notifications, 1 unread'))
 expect(await screen.findByText('Historic event')).toBeInTheDocument()
 expect(screen.getByText('Historic hall')).toBeInTheDocument()
 expect(screen.getByText('1 Jan 2099, 08:00 SGT – 2 Jan 2099, 08:00 SGT')).toBeInTheDocument()
 expect(screen.getByText('Maintenance Operational safety')).toHaveTextContent('Maintenance')
 expect(screen.getByText('Frozen message <script>alert(1)</script>')).toBeInTheDocument()
 expect(document.querySelector('script')).toBeNull()
 expect(fetcher.mock.calls.every(([, init]) => init.method !== 'PATCH')).toBe(true)
 fireEvent.keyDown(screen.getByRole('region', { name: 'Recent notifications' }), { key: 'Escape' })
 expect(screen.queryByRole('region', { name: 'Recent notifications' })).not.toBeInTheDocument()
})

/** Agreed inbox controls: keyset pagination/unread filter, individual writes.
 * AC2 supporting navigation: future types reuse the common safe destination.
 */
test('full page paginates, filters and writes individual read/unread, future type navigates', async () => {
 let read = false
 fetcher.mockImplementation(async (url: string, init: RequestInit) => {
   if (init.method === 'PATCH') { read = JSON.parse(init.body as string).read; return response({ notification: { ...item, readAt: read ? '2026-10-17T02:00:00Z' : null } }) }
   if (url.includes('unread-count')) return response({ unreadCount: read ? 0 : 1 })
   if (url.includes('limit=5')) return response({ notifications: [{ ...item, readAt: read ? '2026-10-17T02:00:00Z' : null }], nextCursor: null })
   if (url.includes('cursor=')) return response({ notifications: [{ ...item, id: 'n2', type: 'future.type', payload: { message: 'Older future notification', destination } }], nextCursor: null })
   return response({ notifications: read && url.includes('unread=true') ? [] : [{ ...item, readAt: read ? '2026-10-17T02:00:00Z' : null }], nextCursor: 'opaque+/=' })
 })
 const navigate = vi.fn(); render(view(A, true, navigate))
 await screen.findByRole('button', { name: 'Mark read' })
 fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
 expect(await screen.findByText('Older future notification')).toBeInTheDocument()
 fireEvent.click(screen.getAllByRole('button', { name: 'Mark read' })[0])
 await screen.findByRole('button', { name: 'Mark unread' })
 expect(screen.getByLabelText('Notifications, 0 unread')).toBeInTheDocument()
 fireEvent.click(screen.getByRole('button', { name: 'Mark unread' }))
 await screen.findByRole('button', { name: 'Mark read' })
 fireEvent.click(screen.getByLabelText('Unread only'))
 await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.includes('unread=true'))).toBe(true))
 fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
 await screen.findByText('Older future notification')
 fireEvent.click(screen.getAllByRole('link', { name: 'Open notification' })[1])
 await waitFor(() => expect(navigate).toHaveBeenCalledWith(`/events/${destination.eventId}?booking=${destination.bookingId}`))
})

/** Supporting freshness/recovery: fixed clocks and mocked outage, no real sleeps. */
test('25-second polling and visible-tab refresh retain same-user data on failure then recover', async () => {
 vi.useFakeTimers(); render(view(A, true))
 await act(async () => {})
 expect(screen.getByLabelText('Notifications, 1 unread')).toBeInTheDocument()
 fetcher.mockRejectedValue(new Error('offline'))
 await act(async () => { await vi.advanceTimersByTimeAsync(25000) })
 expect(screen.getByRole('alert')).toHaveTextContent('last available')
 expect(screen.getByText('Historic event')).toBeInTheDocument()
 expect(screen.getByLabelText('Notifications, 1 unread')).toBeInTheDocument()
 fetcher.mockImplementation(async (url: string) => response(url.includes('unread-count') ? { unreadCount: 0 } : { notifications: [], nextCursor: null }))
 await act(async () => { document.dispatchEvent(new Event('visibilitychange')) })
 expect(screen.getByLabelText('Notifications, 0 unread')).toBeInTheDocument()
 expect(screen.queryByText('Historic event')).not.toBeInTheDocument()
 expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})
function deferred<T>() { let resolve!: (value: T) => void, reject!: (error: Error) => void; const promise = new Promise<T>((r, j) => { resolve = r; reject = j }); return { promise, resolve, reject } }
/** Identity isolation: synchronous unmount and late old-user read/write outcomes. */
test('switching identities immediately clears data and ignores pending old-user read', async () => {
 const old = deferred<ReturnType<typeof response>>()
 fetcher.mockImplementation((_: string, init: RequestInit) => (init.headers as Record<string,string>)['X-Dev-User-Id'] === A.id ? old.promise : Promise.resolve(response(_.includes('unread-count') ? { unreadCount: 0 } : { notifications: [], nextCursor: null })))
 const ui = render(view(A, true)); ui.rerender(view(B, true))
 expect(screen.queryByText('Historic event')).not.toBeInTheDocument()
 await screen.findByText('No notifications yet.')
 await act(async () => { old.resolve(response({ notifications: [item], nextCursor: null, unreadCount: 1 })) })
 expect(screen.queryByText('Historic event')).not.toBeInTheDocument()
 expect(screen.getByLabelText('Notifications, 0 unread')).toBeInTheDocument()
})
test('old-user pending click never navigates or changes the new user', async () => {
 const write = deferred<ReturnType<typeof response>>(); const navigate = vi.fn()
 const ui = render(view(A, true, navigate)); await screen.findByText('Historic event')
 fetcher.mockImplementation((url: string, init: RequestInit) => init.method === 'PATCH' ? write.promise : Promise.resolve(response(url.includes('unread-count') ? { unreadCount: 0 } : { notifications: [], nextCursor: null })))
 fireEvent.click(screen.getByRole('link', { name: 'Open notification' }))
 ui.rerender(view(B, true, navigate)); await screen.findByText('No notifications yet.')
 await act(async () => { write.resolve(response({ notification: { ...item, readAt: '2026-10-17T03:00:00Z' } })) })
 expect(navigate).not.toHaveBeenCalled()
 expect(screen.queryByText('Historic event')).not.toBeInTheDocument()
})
/** Same-user late poll cannot overwrite a successfully saved individual read. */
test('pending write fences older refresh and prevents duplicate actions', async () => {
 const navigate = vi.fn()
 render(view(A, true, navigate)); await screen.findByText('Historic event')
 const old = deferred<ReturnType<typeof response>>(), write = deferred<ReturnType<typeof response>>()
 fetcher.mockImplementation((_: string, init: RequestInit) => init.method === 'PATCH' ? write.promise : old.promise)
 fireEvent.click(screen.getByRole('button', { name: 'Refresh notifications' }))
 fireEvent.click(screen.getByRole('button', { name: 'Mark read' }))
 expect(screen.getByRole('button', { name: 'Mark read' })).toBeDisabled()
 // Anchors use aria-disabled, not the native button disabled mechanism:
 // a second content click must still be fenced by the pending-write guard.
 expect(screen.getByRole('link', { name: 'Open notification' })).toHaveAttribute('aria-disabled', 'true')
 fireEvent.click(screen.getByRole('link', { name: 'Open notification' }))
 expect(fetcher.mock.calls.filter(([, init]) => init.method === 'PATCH')).toHaveLength(1)
 expect(navigate).not.toHaveBeenCalled()
 await act(async () => { old.resolve(response({ notifications: [item], nextCursor: null, unreadCount: 1 })) })
 fetcher.mockRejectedValue(new Error('refresh offline'))
 await act(async () => { write.resolve(response({ notification: { ...item, readAt: '2026-10-17T03:00:00Z' } })) })
 expect(screen.getByRole('button', { name: 'Mark unread' })).toBeInTheDocument()
 expect(screen.getByLabelText('Notifications, 0 unread')).toBeInTheDocument()
 expect(screen.getByRole('alert')).toHaveTextContent('last available')
})

/** Supporting reliable actions: failed write must not silently navigate or dismiss its warning. */
test('failed click retains the notification and actionable warning even when list reads work', async () => {
 const navigate=vi.fn(); render(view(A,true,navigate)); await screen.findByText('Historic event')
 fetcher.mockImplementation(async (url: string, init: RequestInit) => {
   if(init.method === 'PATCH') throw new Error('connection lost')
   return response(url.includes('unread-count') ? { unreadCount:1 } : { notifications:[item],nextCursor:null })
 })
 fireEvent.click(screen.getByRole('link',{name:'Open notification'}))
 await screen.findByRole('alert')
 expect(screen.getByRole('alert')).toHaveTextContent('Read status could not be confirmed')
 expect(navigate).not.toHaveBeenCalled()
 expect(screen.getByRole('button',{name:'Mark read'})).toBeEnabled()
 expect(screen.getByLabelText('Notifications, 1 unread')).toBeInTheDocument()
})
/** Legacy payload compatibility: safe plain-text display never trusts a URL or an object as React markup. */
test('legacy malformed display fields degrade safely and arbitrary destination has no link', async () => {
 fetcher.mockImplementation(async (url: string) => response(url.includes('unread-count') ? {unreadCount:1} : { notifications:[{...item,payload:{message:{html:'<img onerror=alert(1)>'},destination:{kind:'url',url:'https://evil.test'},details:{eventName:{unsafe:'object'}}}}],nextCursor:null }))
 render(view(A,true)); expect(await screen.findByText('Notification content unavailable.')).toBeInTheDocument()
 expect(screen.getByText('Destination unavailable.')).toBeInTheDocument()
 expect(screen.queryByRole('link')).not.toBeInTheDocument()
})

/** AC2 link interaction: notification body/title is itself the keyboard-accessible destination. */
test('clicking the notification content, not just its CTA, persists read and opens the rejection', async () => {
 const navigate=vi.fn(); render(view(A,true,navigate)); await screen.findByText('Historic event')
 fetcher.mockImplementation(async (url: string, init: RequestInit) => response(init.method === 'PATCH' ? {notification:{...item,readAt:'2026-10-17T02:00:00Z'}} : url.includes('unread-count') ? {unreadCount:0} : {notifications:[{...item,readAt:'2026-10-17T02:00:00Z'}],nextCursor:null}))
 fireEvent.click(screen.getByText('Historic event'))
 await waitFor(()=>expect(navigate).toHaveBeenCalledWith(`/events/${destination.eventId}?booking=${destination.bookingId}`))
 expect(screen.getByRole('button',{name:'Mark unread'})).toBeInTheDocument()
})

/** SCRUM-173 review P3: actual legacy API null renders on the notification card, not epoch. */
test('legacy null creation date shows Date unavailable on the actual inbox card', async () => {
 fetcher.mockImplementation(async (url: string) => response(url.includes('unread-count') ? { unreadCount: 1 } : { notifications: [{ ...item, createdAt: null }], nextCursor: null }))
 render(view(A, true))
 await screen.findByText('Historic event')
 expect(screen.getByText(/Date unavailable/, { selector: 'small' })).toHaveTextContent('Date unavailable · Unread')
 expect(screen.queryByText(/1970/)).not.toBeInTheDocument()
 expect(screen.getByRole('link', { name: 'Open notification' })).toBeInTheDocument()
})


/** ## Supporting inbox UI — visible bell state machine, not direct AC evidence. */
test('bell shows loading and capped counts, closes outside, retries an outage and opens all', async () => {
 const initial = deferred<ReturnType<typeof response>>()
 fetcher.mockReturnValue(initial.promise)
 const all = vi.fn()
 render(<NotificationProvider user={A} onNavigate={() => {}}><NotificationBell onViewAll={all} /></NotificationProvider>)
 fireEvent.click(screen.getByLabelText('Notifications, 0 unread'))
 expect(screen.getByText('Loading notifications…')).toBeInTheDocument()
 await act(async () => { initial.resolve(response({ notifications: [], nextCursor: null, unreadCount: 105 })) })
 expect(screen.getByText('No notifications yet.')).toBeInTheDocument()
 expect(screen.getByText('99+')).toBeInTheDocument()
 fireEvent.pointerDown(screen.getByRole('heading', { name: 'Recent notifications' }))
 fireEvent.keyDown(screen.getByRole('region', { name: 'Recent notifications' }), { key: 'Tab' })
 expect(screen.getByRole('region', { name: 'Recent notifications' })).toBeInTheDocument()
 fireEvent.pointerDown(document.body)
 expect(screen.queryByRole('region', { name: 'Recent notifications' })).not.toBeInTheDocument()
 fetcher.mockRejectedValue(new Error('offline'))
 await act(async () => { document.dispatchEvent(new Event('visibilitychange')) })
 fireEvent.click(screen.getByLabelText('Notifications, 105 unread'))
 expect(screen.getByRole('alert')).toHaveTextContent('last available')
 fetcher.mockImplementation(async (url: string) => response(url.includes('unread-count') ? { unreadCount: 0 } : { notifications: [], nextCursor: null }))
 fireEvent.click(screen.getByRole('button', { name: 'Retry notifications' }))
 await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
 fireEvent.click(screen.getByRole('button', { name: 'View all notifications' }))
 expect(all).toHaveBeenCalledOnce()
 expect(screen.queryByRole('region', { name: 'Recent notifications' })).not.toBeInTheDocument()
})

/** ## AC3 supporting UI recovery — retry does not discard history or duplicate rows. */
test('load-more outage keeps current rows and retry appends only previously unseen notices', async () => {
 let failed = true
 fetcher.mockImplementation(async (url: string) => {
  if (url.includes('unread-count')) return response({ unreadCount: 2 })
  if (url.includes('cursor=')) {
   if (failed) throw new Error('offline')
   return response({ notifications: [item, { ...item, id: 'n2', payload: null }], nextCursor: null })
  }
  return response({ notifications: [item], nextCursor: 'next' })
 })
 render(view(A, true)); await screen.findByText('Historic event')
 fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
 await screen.findByRole('alert')
 expect(screen.getByRole('alert')).toHaveTextContent('current list is retained')
 expect(screen.getByText('Historic event')).toBeInTheDocument()
 failed = false
 fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
 await screen.findByText('Notification content unavailable.')
 expect(screen.getAllByRole('listitem')).toHaveLength(2)
 expect(screen.queryByRole('alert')).not.toBeInTheDocument()
 expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
})

/** ## Supporting freshness — hidden tabs do not promise a 30-second delivery SLA. */
test('hidden tab suppresses polling and visible-tab refresh then fetches current state', async () => {
 vi.useFakeTimers()
 const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
 try {
  render(view(A, true)); await act(async () => {})
  fetcher.mockClear()
  await act(async () => { await vi.advanceTimersByTimeAsync(25000); document.dispatchEvent(new Event('visibilitychange')) })
  expect(fetcher).not.toHaveBeenCalled()
  visibility.mockReturnValue('visible')
  await act(async () => { document.dispatchEvent(new Event('visibilitychange')) })
  expect(fetcher).toHaveBeenCalledWith(expect.stringContaining('/notifications/unread-count'), expect.anything())
 } finally { visibility.mockRestore() }
})

/** ## Supporting identity lifetime — signed-out rendering never sends identity-free reads. */
test('signed-out notification shell stays empty without attempting inbox requests', () => {
 render(<NotificationProvider onNavigate={() => {}}><NotificationBell onViewAll={() => {}} /><NotificationsPage /></NotificationProvider>)
 expect(screen.getByLabelText('Notifications, 0 unread')).toBeInTheDocument()
 expect(screen.getByText('No notifications yet.')).toBeInTheDocument()
 expect(fetcher).not.toHaveBeenCalled()
})


/** ## AC2 direct — a bell link closes only after its read is saved and navigation succeeds. */
test('bell content click saves read, navigates to the exact rejection and dismisses the dropdown', async () => {
 const navigate = vi.fn()
 render(view(A, false, navigate))
 await screen.findByLabelText('Notifications, 1 unread')
 fireEvent.click(screen.getByLabelText('Notifications, 1 unread'))
 await screen.findByText('Historic event')
 fetcher.mockImplementation(async (url: string, init: RequestInit) => response(init.method === 'PATCH'
  ? { notification: { ...item, readAt: '2026-10-17T02:00:00Z' } }
  : url.includes('unread-count') ? { unreadCount: 0 } : { notifications: [{ ...item, readAt: '2026-10-17T02:00:00Z' }], nextCursor: null }))
 fireEvent.click(screen.getByRole('link', { name: 'Open notification' }))
 await waitFor(() => expect(navigate).toHaveBeenCalledWith(`/events/${destination.eventId}?booking=${destination.bookingId}`))
 expect(screen.queryByRole('region', { name: 'Recent notifications' })).not.toBeInTheDocument()
 expect(screen.getByLabelText('Notifications, 0 unread')).toBeInTheDocument()
})

/** ## Supporting infrastructure — optional context never crashes its host shell. */
test('standalone notification components without a provider leave their host shell intact', () => {
 const ui = render(<main aria-label="Host shell"><NotificationBell onViewAll={() => {}} /><NotificationsPage /></main>)
 expect(screen.getByRole('main', { name: 'Host shell' })).toBeEmptyDOMElement()
 expect(screen.queryByRole('button')).not.toBeInTheDocument()
 expect(fetcher).not.toHaveBeenCalled()
 ui.unmount()
})


/** ## AC3 supporting identity recovery — stale failures cannot label the next user. */
test('late old-user refresh and click failures cannot warn, navigate or repopulate the new session', async () => {
 const navigate = vi.fn(), read = deferred<ReturnType<typeof response>>(), write = deferred<ReturnType<typeof response>>()
 const ui = render(view(A, true, navigate)); await screen.findByText('Historic event')
 fetcher.mockImplementation((url: string, init: RequestInit) => {
  if ((init.headers as Record<string, string>)['X-Dev-User-Id'] === B.id)
   return Promise.resolve(response(url.includes('unread-count') ? { unreadCount: 0 } : { notifications: [], nextCursor: null }))
  return init.method === 'PATCH' ? write.promise : read.promise
 })
 fireEvent.click(screen.getByRole('button', { name: 'Refresh notifications' }))
 fireEvent.click(screen.getByRole('link', { name: 'Open notification' }))
 ui.rerender(view(B, true, navigate)); await screen.findByText('No notifications yet.')
 await act(async () => { read.reject(new Error('old read outage')); write.reject(new Error('old write outage')) })
 expect(screen.queryByRole('alert')).not.toBeInTheDocument()
 expect(screen.queryByText('Historic event')).not.toBeInTheDocument()
 expect(screen.getByLabelText('Notifications, 0 unread')).toBeInTheDocument()
 expect(navigate).not.toHaveBeenCalled()
})

/** ## AC3 supporting browsing — obsolete page success and failure are both fenced. */
test.each(['success', 'failure'])('identity switch fences a pending old page %s', async outcome => {
 const page = deferred<ReturnType<typeof response>>()
 fetcher.mockImplementation((url: string, init: RequestInit) => {
  const isB = (init.headers as Record<string, string>)['X-Dev-User-Id'] === B.id
  if (isB) return Promise.resolve(response(url.includes('unread-count') ? { unreadCount: 0 } : { notifications: [], nextCursor: null }))
  if (url.includes('cursor=')) return page.promise
  return Promise.resolve(response(url.includes('unread-count') ? { unreadCount: 1 } : { notifications: [item], nextCursor: 'next' }))
 })
 const ui = render(view(A, true)); await screen.findByText('Historic event')
 fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
 ui.rerender(view(B, true)); await screen.findByText('No notifications yet.')
 await act(async () => {
  if (outcome === 'success') page.resolve(response({ notifications: [{ ...item, id: 'old-page' }], nextCursor: null }))
  else page.reject(new Error('obsolete page failed'))
 })
 expect(screen.queryByRole('alert')).not.toBeInTheDocument()
 expect(screen.queryByText('Historic event')).not.toBeInTheDocument()
 expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
})

/** ## Supporting inbox read controls — current filter membership reflects the saved write. */
test('marking the only unread row read leaves an explicit empty unread result', async () => {
 let read = false
 fetcher.mockImplementation(async (url: string, init: RequestInit) => {
  if (init.method === 'PATCH') { read = true; return response({ notification: { ...item, readAt: '2026-10-17T02:00:00Z' } }) }
  if (url.includes('unread-count')) return response({ unreadCount: read ? 0 : 1 })
  return response({ notifications: read && url.includes('unread=true') ? [] : [{ ...item, readAt: read ? '2026-10-17T02:00:00Z' : null }], nextCursor: null })
 })
 render(view(A, true)); await screen.findByText('Historic event')
 fireEvent.click(screen.getByLabelText('Unread only'))
 await screen.findByRole('button', { name: 'Mark read' })
 fireEvent.click(screen.getByRole('button', { name: 'Mark read' }))
 await screen.findByText('No unread notifications.')
 expect(screen.getByLabelText('Notifications, 0 unread')).toBeInTheDocument()
 expect(screen.queryByRole('listitem')).not.toBeInTheDocument()
})

/** ## Supporting idempotent read UI — opening an already-read item cannot decrement other unread counts. */
test('opening an already-read notification keeps the unrelated unread count unchanged', async () => {
 const readItem = { ...item, readAt: '2026-10-17T02:00:00Z' }
 fetcher.mockImplementation(async (url: string, init: RequestInit) => response(init.method === 'PATCH'
  ? { notification: readItem } : url.includes('unread-count') ? { unreadCount: 2 } : { notifications: [readItem], nextCursor: null }))
 const navigate = vi.fn(); render(view(A, true, navigate)); await screen.findByText('Historic event')
 fireEvent.click(screen.getByRole('link', { name: 'Open notification' }))
 await waitFor(() => expect(navigate).toHaveBeenCalledOnce())
 expect(screen.getByLabelText('Notifications, 2 unread')).toBeInTheDocument()
 expect(screen.getByRole('button', { name: 'Mark unread' })).toBeEnabled()
})

/** ## Supporting freshness — multiple refresh requests coalesce after the active snapshot. */
test('refresh during an active refresh schedules a fresh snapshot after it completes', async () => {
 const read = deferred<ReturnType<typeof response>>()
 fetcher.mockImplementation(async (url: string) => response(url.includes('unread-count') ? { unreadCount: 1 } : { notifications: [item], nextCursor: 'next' }))
 render(view(A, true)); await screen.findByText('Historic event')
 fetcher.mockReturnValue(read.promise)
 fireEvent.click(screen.getByRole('button', { name: 'Refresh notifications' }))
 fireEvent.click(screen.getByRole('button', { name: 'Refresh notifications' }))
 // Background refresh preserves enabled history controls. A load-more click
 // while its snapshot is pending must not race a stale cursor request.
 fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
 expect(fetcher.mock.calls.some(([url]) => url.includes('cursor='))).toBe(false)
 fetcher.mockImplementation(async (url: string) => response(url.includes('unread-count') ? { unreadCount: 0 } : { notifications: [], nextCursor: null }))
 await act(async () => { read.resolve(response({ notifications: [item], nextCursor: null, unreadCount: 1 })) })
 await screen.findByText('No notifications yet.')
 expect(screen.getByLabelText('Notifications, 0 unread')).toBeInTheDocument()
 expect(screen.queryByText('Historic event')).not.toBeInTheDocument()
})
