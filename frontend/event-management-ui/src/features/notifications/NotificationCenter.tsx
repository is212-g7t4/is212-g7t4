import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { User } from '../../types'
import { notificationApi, notificationDate, notificationPath, notificationPayload } from './notifications'
import type { InboxItem, InboxPage } from './notifications'
import './notifications.css'

type Center = {
  recent: InboxItem[]; items: InboxItem[]; count: number; warning: string
  unread: boolean; setUnread: (value: boolean) => void
  loading: boolean; pending: boolean; cursor: string | null
  refresh: () => void; loadMore: () => void
  mark: (item: InboxItem, read: boolean, open?: boolean) => Promise<boolean>
}
const Context = createContext<Center | null>(null)

/** Identity is a lifetime boundary, including pending reads/writes and open UI. */
export function NotificationProvider({ user, children, onNavigate }: { user?: User; children: ReactNode; onNavigate: (path: string) => void }) {
  return <Session key={`${user?.id}-${user?.role}`} user={user} onNavigate={onNavigate}>{children}</Session>
}
function Session({ user, children, onNavigate }: { user?: User; children: ReactNode; onNavigate: (path: string) => void }) {
  const [recent, setRecent] = useState<InboxItem[]>([])
  const [items, setItems] = useState<InboxItem[]>([])
  const [count, setCount] = useState(0)
  const [warning, setWarning] = useState('')
  const [unread, setUnread] = useState(false)
  const [cursor, setCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(Boolean(user))
  const [pending, setPending] = useState(false)
  const alive = useRef(true)
  const revision = useRef(0)
  const writing = useRef(false)
  // Filter/identity/write revisions invalidate reads. Ordinary polls do not
  // invalidate pagination: list reads are serialized and a poll is coalesced.
  const windowState = useRef<{ rows: InboxItem[]; cursor: string | null }>({ rows: [], cursor: null })
  const reader = useRef<object | null>(null)
  const refreshQueued = useRef(false)
  const listQuery = `/notifications?limit=20&unread=${unread}`
  const storeWindow = useCallback((rows: InboxItem[], nextCursor: string | null) => {
    windowState.current = { rows, cursor: nextCursor }
    setItems(rows); setCursor(nextCursor)
  }, [])
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const refresh = useCallback(async (): Promise<void> => {
    if (!user || !alive.current || writing.current) return
    if (reader.current) { refreshQueued.current = true; return }
    const request = {}; reader.current = request
    const version = revision.current
    const valid = () => alive.current && version === revision.current
    // Refresh through the previously loaded oldest key, not just a page count:
    // new head rows can push an entire former page beyond page one. Traversing
    // fresh keysets also removes externally-read rows in the unread view.
    const boundary = windowState.current.rows.at(-1)
    const coversBoundary = (last: InboxItem) => {
      if (!boundary || last.id === boundary.id) return true
      // Date.parse normalizes offsets but truncates PostgreSQL microseconds.
      // Add the remaining three digits before comparing the UUID tie-breaker;
      // raw ISO strings cannot be compared because offsets may differ.
      const key = (value: string | null) => {
        const milliseconds = Date.parse(value ?? '')
        if (!Number.isFinite(milliseconds)) return null
        const fraction = value?.match(/\.(\d+)/)?.[1] ?? ''
        return BigInt(milliseconds) * 1000n + BigInt(fraction.padEnd(6, '0').slice(3, 6))
      }
      const a = key(last.createdAt), b = key(boundary.createdAt)
      return a !== null && b !== null && (a < b || (a === b && last.id <= boundary.id))
    }
    try {
      const readWindow = async () => {
        let page: InboxPage = await notificationApi(user, listQuery)
        const rows = [...page.notifications]
        while (valid() && boundary && page.nextCursor && (!rows.length || !coversBoundary(rows[rows.length - 1]))) {
          page = await notificationApi(user, listQuery + '&cursor=' + encodeURIComponent(page.nextCursor))
          rows.push(...page.notifications)
        }
        return { rows: [...new Map(rows.map(row => [row.id, row])).values()], cursor: page.nextCursor }
      }
      const [page, total, recentPage]: [{ rows: InboxItem[]; cursor: string | null }, { unreadCount: number }, InboxPage] = await Promise.all([
        readWindow(), notificationApi(user, '/notifications/unread-count'), notificationApi(user, '/notifications?limit=5'),
      ])
      if (!valid()) return
      storeWindow(page.rows, page.cursor); setRecent(recentPage.notifications); setCount(total.unreadCount); setWarning('')
    } catch {
      if (valid()) setWarning('Notifications could not refresh. Showing the last available information; retry to get the latest.')
    } finally {
      if (reader.current === request) {
        reader.current = null
        if (valid()) setLoading(false)
        if (refreshQueued.current) { refreshQueued.current = false; refreshLatest.current() }
      }
    }
  }, [user, listQuery, storeWindow])
  // Initialized before effects or event handlers can start a read.
  const refreshLatest = useRef(refresh)
  useEffect(() => {
    refreshLatest.current = refresh
    // oxlint-disable-next-line react/set-state-in-effect
    void refresh()
    const timer = window.setInterval(() => { if (document.visibilityState !== 'hidden') void refresh() }, 25000)
    const visible = () => { if (document.visibilityState !== 'hidden') void refresh() }
    document.addEventListener('visibilitychange', visible)
    return () => { window.clearInterval(timer); document.removeEventListener('visibilitychange', visible) }
  }, [refresh])
  const loadMore = async () => {
    if (!user || !cursor || reader.current || writing.current) return
    const request = {}; reader.current = request
    const version = revision.current
    const valid = () => alive.current && version === revision.current
    setLoading(true)
    try {
      const page: InboxPage = await notificationApi(user, listQuery + '&cursor=' + encodeURIComponent(cursor))
      if (!valid()) return
      const current = windowState.current.rows
      storeWindow([...current, ...page.notifications.filter(item => !current.some(old => old.id === item.id))], page.nextCursor)
      setWarning('')
    } catch { if (valid()) setWarning('More notifications could not load. Your current list is retained; retry.') }
    finally {
      if (reader.current === request) {
        reader.current = null
        if (valid()) setLoading(false)
        if (refreshQueued.current) { refreshQueued.current = false; refreshLatest.current() }
      }
    }
  }
  const mark = async (item: InboxItem, read: boolean, open = false) => {
    if (!user || writing.current) return false
    writing.current = true; revision.current++; reader.current = null; refreshQueued.current = false; setPending(true); setLoading(false)
    let saved = false
    try {
      const body: { notification: InboxItem } = await notificationApi(user, '/notifications/' + encodeURIComponent(item.id), { method: 'PATCH', body: JSON.stringify({ read }) })
      if (!alive.current) return false
      const replace = (rows: InboxItem[]) => rows.map(row => row.id === item.id ? body.notification : row)
      setRecent(replace); storeWindow(replace(windowState.current.rows).filter(row => !unread || !row.readAt), windowState.current.cursor)
      setCount(value => Math.max(0, value + (Boolean(item.readAt) !== read ? (read ? -1 : 1) : 0)))
      setWarning(''); saved = true
      const path = notificationPath(notificationPayload(item).destination)
      if (open && path) onNavigate(path)
      return true
    } catch {
      if (alive.current) setWarning('Read status could not be confirmed. Your notification is retained. Retry or refresh before trying again.')
      return false
    } finally {
      writing.current = false
      if (alive.current) { setPending(false); if (saved) void refresh() }
    }
  }
  return <Context.Provider value={{ recent, items, count, warning, unread, setUnread: value => { revision.current++; reader.current = null; refreshQueued.current = false; setUnread(value); storeWindow([], null); setLoading(true) }, cursor, loading, pending, refresh: () => { void refresh() }, loadMore: () => { void loadMore() }, mark }}>{children}</Context.Provider>
}

function Content({ item }: { item: InboxItem }) {
  const payload = notificationPayload(item)
  const raw = payload.details
  const text = (value: unknown) => typeof value === 'string' ? value : ''
  const details = { eventName: text(raw?.eventName), venueName: text(raw?.venueName), startDateTime: text(raw?.startDateTime), endDateTime: text(raw?.endDateTime), reason: text(raw?.reason) }
  return <>
    {details?.eventName && <strong>{details.eventName}</strong>}
    {details?.venueName && <span>{details.venueName}</span>}
    <p>{text(payload.message) || 'Notification content unavailable.'}</p>
    {details?.startDateTime && details?.endDateTime && <p>{notificationDate(details.startDateTime)} – {notificationDate(details.endDateTime)}</p>}
    {details?.reason && <p className="notification-reason">{details.reason}</p>}
    {text(raw?.equipmentType) && <span>{text(raw?.equipmentType)}</span>}
    {typeof raw?.quantityReserved === 'number' && Number.isSafeInteger(raw.quantityReserved) && raw.quantityReserved > 0 && <p>Quantity reserved: {raw.quantityReserved}</p>}
    {typeof raw?.round === 'number' && Number.isSafeInteger(raw.round) && raw.round > 0 && <p>Safety review round: {raw.round}</p>}
    {text(raw?.closureStart) && text(raw?.closureEnd) && <p>Closure period: {notificationDate(raw?.closureStart)} – {notificationDate(raw?.closureEnd)}</p>}
    <small>{notificationDate(item.createdAt)} · {item.readAt ? 'Read' : 'Unread'}</small>
  </>
}
export function NotificationBell({ onViewAll }: { onViewAll: () => void }) {
  const center = useContext(Context)
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!open) return
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false) }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [open])
  if (!center) return null
  return <div className="notification-bell" ref={root} onKeyDown={(event) => { if (event.key === 'Escape') { setOpen(false); button.current?.focus() } }}>
    <button ref={button} className="button notification-toggle" type="button" aria-label={`Notifications, ${center.count} unread`} aria-expanded={open} aria-controls="recent-notifications" onClick={() => setOpen(!open)}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" /></svg>
      <span>{center.count > 99 ? '99+' : center.count}</span>
    </button>
    {open && <section id="recent-notifications" className="notification-dropdown panel" aria-label="Recent notifications">
      <h2>Recent notifications</h2>
      {center.warning && <><p role="alert">{center.warning}</p><button className="button small" onClick={center.refresh} disabled={center.pending}>Retry notifications</button></>}
      {center.recent.length ? <Items items={center.recent} onOpened={() => setOpen(false)} /> : <p>{center.loading ? 'Loading notifications…' : 'No notifications yet.'}</p>}
      <button className="button primary" onClick={() => { setOpen(false); onViewAll() }}>View all notifications</button>
    </section>}
  </div>
}
function Items({ items, onOpened }: { items: InboxItem[]; onOpened?: () => void }) {
  const center = useContext(Context)!
  return <ul className="notification-list">{items.map(item => {
    const path = notificationPath(notificationPayload(item).destination)
    return <li key={item.id} className={item.readAt ? '' : 'notification-unread'}>
      {path ? <a className="notification-content-link" href={path} aria-label="Open notification" aria-disabled={center.pending} onClick={event => {
        event.preventDefault()
        void center.mark(item, true, true).then(opened => { if (opened) onOpened?.() })
      }}><Content item={item} /><span className="notification-destination">{item.type === 'venue.closure-rejection' ? 'View rejection →' : 'View details →'}</span></a> : <><Content item={item} /><span>Destination unavailable.</span></>}
      <div className="notification-actions">
        <button className="button small" disabled={center.pending} onClick={() => void center.mark(item, !item.readAt)}>{item.readAt ? 'Mark unread' : 'Mark read'}</button>
      </div>
    </li>
  })}</ul>
}
export function NotificationsPage() {
  const center = useContext(Context)
  if (!center) return null
  return <section className="panel notifications-page" aria-label="Notifications inbox">
    <header className="notification-page-header"><div><h2>Your notifications</h2><p className="muted">Newest first · Times shown in Singapore time (SGT)</p></div><button className="button" onClick={center.refresh} disabled={center.pending}>Refresh notifications</button></header>
    <label className="notification-filter"><input type="checkbox" checked={center.unread} disabled={center.pending} onChange={event => center.setUnread(event.target.checked)} /> Unread only</label>
    {center.warning && <p role="alert" className="notification-warning">{center.warning}</p>}
    {center.items.length ? <Items items={center.items} /> : <p role="status">{center.loading ? 'Loading notifications…' : center.unread ? 'No unread notifications.' : 'No notifications yet.'}</p>}
    {center.cursor && <button className="button" disabled={center.loading || center.pending} onClick={center.loadMore}>{center.loading ? 'Loading…' : 'Load more'}</button>}
  </section>
}
