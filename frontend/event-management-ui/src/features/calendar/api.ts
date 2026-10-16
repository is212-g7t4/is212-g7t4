import { timestampMicros } from './dates'

export interface CalendarBooking {
  id: string
  eventId: string | null
  venueId: string
  requestedBy: string | null
  reviewedBy: string | null
  status: 'Approved' | 'Pending' | 'Pending Review' | 'On Hold'
  blocksSelection: boolean
  requestedStartTime: string
  requestedEndTime: string
  effectiveStartTime?: string
  effectiveEndTime?: string
}
/** Presentation-only closure entry: never submitted as a booking or event. */
export interface CalendarClosure extends Omit<CalendarBooking, 'status'> {
  kind: 'closure'
  status: 'Closed'
  reason: string
}
export type CalendarEntry = CalendarBooking | CalendarClosure
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const validId = (id: unknown): id is string => typeof id === 'string' && uuid.test(id)
interface ClosureResponse { closureId: string; venueId: string; startDateTime: string; endDateTime: string; reason: string }

/** Venue/date window + DEV identity → complete validated read-only entries. */
export async function fetchCalendar(
  venueId: string,
  window: { start: string; end: string },
  user: { id: string; role: string },
  signal?: AbortSignal,
  buffer: { setupTimeMinutes?: number; turnaroundTimeMinutes?: number } = {},
): Promise<CalendarEntry[]> {
  const query = new URLSearchParams({
    venueId,
    dateFrom: window.start + 'T00:00:00+08:00',
    dateTo: window.end + 'T00:00:00+08:00',
    setupTimeMinutes: String(buffer.setupTimeMinutes ?? 0),
    turnaroundTimeMinutes: String(buffer.turnaroundTimeMinutes ?? 0),
  })
  const response = await fetch(`${import.meta.env.VITE_VENUE_AVAILABILITY_SERVICE_URL || 'http://localhost:5008'}/venue-bookings?${query}`, {
    signal, headers: { 'X-Dev-User-Id': user.id, 'X-Dev-Role': user.role },
  })
  if (!response.ok) throw new Error(`Availability unavailable (HTTP ${response.status}). Check DEV mode and selected user.`)
  const body: unknown = await response.json().catch(() => null)
  if (!body || typeof body !== 'object' || !('bookings' in body) || !Array.isArray(body.bookings) ||
      !body.bookings.every(item => validBooking(item, venueId)) || !('closures' in body) ||
      !Array.isArray(body.closures) || !body.closures.every(item => validClosure(item, venueId)))
    throw new Error('Invalid availability response. Availability is unknown.')
  if (new Set(body.bookings.map(b => b.id.toLowerCase())).size !== body.bookings.length)
    throw new Error('Invalid availability response. Duplicate booking identity.')
  if (new Set(body.closures.map(c => c.closureId.toLowerCase())).size !== body.closures.length)
    throw new Error('Invalid availability response. Duplicate closure identity.')
  return [...body.bookings, ...body.closures.map(c => ({
    kind: 'closure' as const, id: `closure:${c.closureId.toLowerCase()}`, eventId: null, venueId: c.venueId,
    requestedBy: null, reviewedBy: null, status: 'Closed' as const, blocksSelection: true,
    requestedStartTime: c.startDateTime, requestedEndTime: c.endDateTime, reason: c.reason,
  }))]
}

/** Unknown JSON → validated booking; holds may have no event but must block. */
function validBooking(value: unknown, venueId: string): value is CalendarBooking {
  if (!value || typeof value !== 'object') return false
  const b = value as Record<string, unknown>
  if (![b.requestedBy, b.reviewedBy].every(id => id === null || typeof id === 'string')) return false
  if (!validId(b.id) || !validId(b.venueId) || b.venueId !== venueId ||
      !(validId(b.eventId) || (b.status === 'On Hold' && b.eventId === null))) return false
  if (!['Approved', 'Pending', 'Pending Review', 'On Hold'].includes(String(b.status)) ||
      b.blocksSelection !== (b.status === 'Approved' || b.status === 'On Hold')) return false
  if (!validInterval(b.requestedStartTime, b.requestedEndTime)) return false
  if (b.effectiveStartTime === undefined && b.effectiveEndTime === undefined) return true
  return validInterval(b.effectiveStartTime, b.effectiveEndTime) &&
    timestampMicros(b.effectiveStartTime)! <= timestampMicros(b.requestedStartTime)! &&
    timestampMicros(b.effectiveEndTime)! >= timestampMicros(b.requestedEndTime)!
}

export const occupancyStart = (booking: CalendarEntry) => booking.effectiveStartTime ?? booking.requestedStartTime
export const occupancyEnd = (booking: CalendarEntry) => booking.effectiveEndTime ?? booking.requestedEndTime
/** Closure records stay distinct and keep their original full bounds and reason. */
function validClosure(value: unknown, venueId: string): value is ClosureResponse {
  if (!value || typeof value !== 'object') return false
  const c = value as Record<string, unknown>
  return validId(c.closureId) && c.venueId === venueId && typeof c.reason === 'string' &&
    !!c.reason.trim() && !c.reason.includes('\0') && validInterval(c.startDateTime, c.endDateTime)
}
function validInterval(start: unknown, end: unknown): boolean {
  return validTime(start) && validTime(end) && timestampMicros(start)! < timestampMicros(end)!
}
/** Server SGT timestamp → finite calendar time, rejecting JS date rollover. */
function validTime(value: unknown): value is string {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?\+08:00$/.test(value) && timestampMicros(value) !== null
}
