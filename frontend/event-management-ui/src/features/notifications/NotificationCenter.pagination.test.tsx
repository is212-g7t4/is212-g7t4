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
 * # SCRUM-173 MF-03 — public inbox DOM, supporting agreed paginated browsing.
 * Controlled network/deferred promises; no real clocks/I/O. Poll/post-write refresh
 * preserves loaded history, merges a new head without cursor gaps, revalidates
 * older read states and unread membership. Identity/write fencing regressed too.
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { NotificationProvider, NotificationsPage } from './NotificationCenter'
import type { InboxItem } from './notifications'
const user = { id: '10000000-0000-0000-0000-000000000001', role: 'Event Coordinator' as const, username: 'A', email: '', organization: '' }
const row = (n: number): InboxItem => ({ id: `n${n}`, type: 'future', createdAt: `2026-10-17T00:00:0${n}Z`, readAt: null, eventId: null, payload: { message: `Notice ${n}` } })
let rows: InboxItem[]
let fetcher: ReturnType<typeof vi.fn>
const response = (body: unknown) => ({ ok: true, json: async () => body })
let held: { promise: Promise<ReturnType<typeof response>>; resolve: (r: ReturnType<typeof response>) => void } | undefined
let holdCursor = false
function result(url: string) {
 const q = new URL(url, 'http://local').searchParams
 let filtered = rows.filter(r => q.get('unread') !== 'true' || !r.readAt)
 const cursor = q.get('cursor')
 if (cursor) filtered = filtered.filter(r => r.id < cursor)
 const page = filtered.slice(0, 2)
 return response({ notifications: structuredClone(page), nextCursor: filtered.length > 2 ? page[page.length - 1].id : null })
}
beforeEach(() => {
 rows = [6,5,4,3,2,1].map(row); held = undefined; holdCursor = false
 fetcher = vi.fn(async (url: string, init: RequestInit) => {
  if (init.method === 'PATCH') {
   const id = url.split('/').pop()!, read = JSON.parse(init.body as string).read
   rows = rows.map(r => r.id === id ? { ...r, readAt: read ? '2026-10-17T01:00:00Z' : null } : r)
   return response({ notification: structuredClone(rows.find(r => r.id === id)) })
  }
  if (url.includes('unread-count')) return response({ unreadCount: rows.filter(r => !r.readAt).length })
  if (holdCursor && url.includes('cursor=')) {
   holdCursor = false
   let resolve!: (r: ReturnType<typeof response>) => void
   const promise = new Promise<ReturnType<typeof response>>(r => { resolve = r })
   held = { promise, resolve }; return promise
  }
  return result(url)
 })
 vi.stubGlobal('fetch', fetcher)
})
afterEach(() => { vi.unstubAllGlobals() })
async function start() {
 render(<NotificationProvider user={user} onNavigate={() => {}}><NotificationsPage /></NotificationProvider>)
 await screen.findByText('Notice 6')
}
async function more() {
 fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
 await screen.findByText('Notice 3')
}
async function poll() { await act(async () => { document.dispatchEvent(new Event('visibilitychange')) }) }
function card(n: number) { return screen.getByText(`Notice ${n}`).closest('li')! }

test('MF-03a loaded page two survives poll, new head does not skip cursor items', async () => {
 await start(); await more()
 rows = [row(8), row(7), ...rows]
 await poll()
 for (const n of [8,7,6,5,4,3]) expect(screen.getByText(`Notice ${n}`)).toBeInTheDocument()
 fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
 await screen.findByText('Notice 1')
 expect(screen.getAllByRole('listitem')).toHaveLength(8)
})

test('MF-03b marking an older item preserves its read state and older loaded neighbors', async () => {
 await start(); await more()
 fireEvent.click(within(card(3)).getByRole('button', { name: 'Mark read' }))
 await waitFor(() => expect(within(card(3)).getByRole('button', { name: 'Mark unread' })).toBeEnabled())
 await poll()
 expect(within(card(3)).getByRole('button', { name: 'Mark unread' })).toBeInTheDocument()
 expect(screen.getByText('Notice 4')).toBeInTheDocument()
 expect(screen.getByRole('button', { name: 'Load more' })).toBeEnabled()
})

test('MF-03c poll during in-flight load more retains that valid older page and cursor', async () => {
 await start(); holdCursor = true
 fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
 await waitFor(() => expect(held).toBeDefined())
 await poll()
 await act(async () => { held!.resolve(result('/notifications?cursor=n5')) })
 await screen.findByText('Notice 3')
 expect(screen.getByText('Notice 4')).toBeInTheDocument()
 fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
 await screen.findByText('Notice 1')
})

test('MF-03d unread refresh removes older externally read rows without losing older unread history', async () => {
 await start(); fireEvent.click(screen.getByLabelText('Unread only'))
 await screen.findByText('Notice 6'); await more()
 rows = rows.map(r => r.id === 'n4' || r.id === 'n3' ? { ...r, readAt: '2026-10-17T01:00:00Z' } : r)
 await poll()
 expect(screen.queryByText('Notice 4')).not.toBeInTheDocument()
 expect(screen.queryByText('Notice 3')).not.toBeInTheDocument()
 expect(screen.getByText('Notice 2')).toBeInTheDocument()
 expect(screen.getByText('Notice 1')).toBeInTheDocument()
})

test('MF-03e filter invalidation fences a pending old load more response', async () => {
 await start(); holdCursor = true
 fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
 await waitFor(() => expect(held).toBeDefined())
 const stale = result('/notifications?cursor=n5')
 rows = rows.map(r => Number(r.id.slice(1)) <= 4 ? { ...r, readAt: '2026-10-17T01:00:00Z' } : r)
 fireEvent.click(screen.getByLabelText('Unread only'))
 await screen.findByText('Notice 6')
 await act(async () => { held!.resolve(stale) })
 expect(screen.queryByText('Notice 3')).not.toBeInTheDocument()
 expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
})


// MF-03f / AC3 supporting UI recovery: retain the server's full PostgreSQL key.
test.each([
 ['microseconds', '2026-10-17T00:00:00.', '+00:00'],
 ['offset crossing the previous calendar day', '2026-10-16T17:00:00.', '-07:00'],
])('MF-03f refresh preserves loaded history across %s', async (_label, prefix, offset) => {
 const precise = (n: number, id: number, base = '2026-10-17T00:00:00.', zone = '+00:00'): InboxItem => ({
  ...row(n), id: `20000000-0000-0000-0000-${String(id).padStart(12, '0')}`,
  createdAt: `${base}000${n}00${zone}`,
 })
 rows = [precise(4, 400), precise(3, 300), precise(2, 200), precise(1, 100)]
 // Cursor is opaque; the server fixture orders full instants, not UUID strings.
 fetcher.mockImplementation(async (url: string) => {
  const query = new URL(url, 'http://local').searchParams
  if (url.includes('unread-count')) return response({ unreadCount: rows.length })
  const cursor = query.get('cursor')
  const start = cursor ? rows.findIndex(r => r.id === cursor) + 1 : 0
  const page = rows.slice(start, start + 2)
  return response({ notifications: structuredClone(page), nextCursor: rows.length > start + 2 ? page.at(-1)!.id : null })
 })
 render(<NotificationProvider user={user} onNavigate={() => {}}><NotificationsPage /></NotificationProvider>)
 await screen.findByText('Notice 4')
 fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
 await screen.findByText('Notice 1')
 rows = [precise(6, 1, prefix, offset), precise(5, 2, prefix, offset), ...rows]
 await poll()
 expect(screen.getByText('Notice 1')).toBeInTheDocument()
 expect(screen.getAllByRole('listitem')).toHaveLength(6)
 expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
})


/** ## Supporting browsing — equal full instants use UUID, not stale row presence. */
test('MF-03g refresh reaches a deleted boundary using the server UUID tie-breaker and retains its cursor', async () => {
 const tied = (n: number, id: number): InboxItem => ({ ...row(n),
  id: `20000000-0000-0000-0000-${String(id).padStart(12, '0')}`, createdAt: '2026-10-17T00:00:00.000100Z' })
 rows = [tied(4, 400), tied(3, 300), tied(2, 200), tied(1, 100)]
 fetcher.mockImplementation(async (url: string) => {
  if (url.includes('unread-count')) return response({ unreadCount: rows.length })
  const cursor = new URL(url, 'http://local').searchParams.get('cursor')
  const start = cursor ? rows.findIndex(r => r.id === cursor) + 1 : 0
  const page = rows.slice(start, start + 2)
  return response({ notifications: structuredClone(page), nextCursor: rows.length > start + 2 ? page.at(-1)!.id : null })
 })
 render(<NotificationProvider user={user} onNavigate={() => {}}><NotificationsPage /></NotificationProvider>)
 await screen.findByText('Notice 4')
 fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
 await screen.findByText('Notice 1')
 rows = [tied(6, 600), tied(5, 500), ...rows.slice(0, 3), tied(0, 50), tied(-1, 25)]
 await poll()
 expect(screen.queryByText('Notice 1')).not.toBeInTheDocument()
 expect(screen.getAllByRole('listitem')).toHaveLength(6)
 expect(screen.getByText('Notice 0')).toBeInTheDocument()
 expect(screen.queryByText('Notice -1')).not.toBeInTheDocument()
 fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
 await screen.findByText('Notice -1')
 expect(screen.getAllByRole('listitem')).toHaveLength(7)
})


/** ## Cross-ticket legacy compatibility / supporting UI recovery — null dates cannot define a false cutoff. */
test('MF-03h a loaded legacy null timestamp retains history until the fresh traversal is exhausted', async () => {
 rows = rows.map(r => r.id === 'n1' ? { ...r, createdAt: null } : r)
 await start(); await more()
 fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
 await screen.findByText('Notice 1')
 rows = [row(8), row(7), ...rows]
 await poll()
 expect(screen.getAllByRole('listitem')).toHaveLength(8)
 expect(screen.getByText('Notice 1')).toBeInTheDocument()
 expect(screen.getByText(/Date unavailable/)).toBeInTheDocument()
 expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
})
