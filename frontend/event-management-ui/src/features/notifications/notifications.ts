import type { User } from '../../types'

export interface InboxItem {
  id: string
  type: string
  eventId: string | null
  createdAt: string | null
  readAt: string | null
  payload: {
    eventName?: string
    venueName?: string
    reason?: string
    remarks?: string
    equipmentType?: string
    quantityReserved?: number
    round?: number
    closureStart?: string
    closureEnd?: string
    message?: string
    destination?: unknown
    details?: { eventName?: string; venueName?: string; startDateTime?: string; endDateTime?: string; reason?: string | null; areas?: string[]; decision?: string; eventId?: string; changeRequestId?: string; proposedChanges?: Record<string, string>; previousEventName?: string; equipmentType?: string; quantityReserved?: number; round?: number; closureStart?: string; closureEnd?: string }
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
  if (value.kind === 'attendee-registration' && uuid(value.registrationId)) return `/registrations?registration=${value.registrationId}`
  if (value.kind === 'event-details' && uuid(value.eventId)) return `/events/${value.eventId}`
  if (value.kind === 'change-request-review' && uuid(value.eventId) && uuid(value.changeRequestId)) {
    return `/change-requests?${new URLSearchParams({ event: value.eventId, request: value.changeRequestId })}`
  }
  if (value.kind === 'venue-requests') return '/venue-requests'
  if (value.kind === 'equipment-requests' && uuid(value.eventId) && Array.isArray(value.requestIds)
    && value.requestIds.length > 0 && value.requestIds.length <= 50 && value.requestIds.every(uuid)) {
    const query = new URLSearchParams({ event: value.eventId })
    for (const id of value.requestIds) query.append('request', id)
    return `/equipment-requests?${query}`
  }
  return null
}

/** Read-only compatibility view for the exact seed-backed pre-envelope history formats.
 * Never rewrite inbox records or follow producer-supplied URLs.
 */
export function notificationPayload(item: InboxItem): NonNullable<InboxItem['payload']> {
  const payload = item.payload ?? {}
  // These exact history formats are defined by database/supabase/seed.sql.
  // No new destination is inferred: history lacks request/booking identifiers
  // and does not prove current event ownership/assignment. In particular an
  // Attendee cannot use the internal /events/:id page.
  const messages: Record<string, string> = {
    coordinator_assigned: 'You have been assigned as an event coordinator.',
    venue_booking_rejected: 'Your venue booking has been rejected.',
    equipment_request_approved: 'Your equipment request has been approved.',
    safety_changes_requested: 'Safety changes have been requested for your event.',
    safety_approved: 'Your event safety check has been approved.',
    booking_affected_by_closure: 'Your venue booking is affected by a venue closure.',
    registration_confirmed: 'Your event registration has been confirmed.',
  }
  if (Object.hasOwn(messages, item.type)) return {
    ...payload,
    message: payload.message ?? messages[item.type],
    details: {
      eventName: payload.eventName,
      venueName: item.type === 'venue_booking_rejected' || item.type === 'booking_affected_by_closure' ? payload.venueName : undefined,
      reason: item.type === 'safety_changes_requested' ? payload.remarks : item.type === 'venue_booking_rejected' || item.type === 'booking_affected_by_closure' ? payload.reason : undefined,
      ...(item.type === 'equipment_request_approved' ? { equipmentType: payload.equipmentType, quantityReserved: payload.quantityReserved } : {}),
      ...(item.type === 'safety_approved' || item.type === 'safety_changes_requested' ? { round: payload.round } : {}),
      ...(item.type === 'booking_affected_by_closure' ? { closureStart: payload.closureStart, closureEnd: payload.closureEnd } : {}),
      ...payload.details,
    },
  }
  if (item.type !== 'event_approved' && item.type !== 'event_rejected') return payload
  return {
    ...payload,
    message: payload.message ?? (item.type === 'event_approved' ? 'Your event has been approved.' : 'Your event has been rejected.'),
    details: { eventName: payload.eventName, reason: item.type === 'event_rejected' ? payload.reason : undefined, ...payload.details },
    destination: payload.destination === undefined ? { kind: 'event-details', eventId: item.eventId } : payload.destination,
  }
}

export function notificationDate(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) return 'Date unavailable'
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return 'Date unavailable'
  return new Intl.DateTimeFormat('en-SG', { timeZone: 'Asia/Singapore', year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(date) + ' SGT'
}
