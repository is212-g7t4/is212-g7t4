import type { User } from '../../types'

export interface InboxItem {
  id: string
  type: string
  eventId: string | null
  createdAt: string | null
  readAt: string | null
  payload: {
    message?: string
    destination?: unknown
    details?: { eventName?: string; venueName?: string; startDateTime?: string; endDateTime?: string; reason?: string }
  } | null
}
export interface InboxPage { notifications: InboxItem[]; nextCursor: string | null }

export async function notificationApi(user: User, path: string, init: RequestInit = {}) {
  const response = await fetch(`${import.meta.env.VITE_NOTIFICATION_SERVICE_URL || 'http://localhost:5015'}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', 'X-Dev-User-Id': user.id, 'X-Dev-Role': user.role },
  })
  const body = await response.json()
  if (!response.ok) throw new Error(body.message || 'Unable to load notifications.')
  return body
}

/** Allowlisted app destinations, shared by all types; never follow producer URLs. */
export function notificationPath(destination: unknown): string | null {
  if (!destination || typeof destination !== 'object') return null
  const value = destination as Record<string, unknown>
  const uuid = (id: unknown): id is string => typeof id === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)
  if (value.kind === 'event-venue-request' && uuid(value.eventId) && uuid(value.bookingId)) return `/events/${value.eventId}?booking=${value.bookingId}`
  return null
}

export function notificationDate(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) return 'Date unavailable'
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return 'Date unavailable'
  return new Intl.DateTimeFormat('en-SG', { timeZone: 'Asia/Singapore', year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(date) + ' SGT'
}
