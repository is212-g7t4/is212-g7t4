import { timestampMicros } from './dates'

export interface CalendarBooking {
  id: string
  eventId: string
  venueId: string
  requestedBy: string | null
  reviewedBy: string | null
  status: 'Approved' | 'Pending' | 'Pending Review'
  blocksSelection: boolean
  requestedStartTime: string
  requestedEndTime: string
}
/** Venue/date window + switcher identity → read-only booking snapshot. DEV headers are spoofable. */
export async function fetchCalendar(
  venueId: string,
  window: { start: string; end: string },
  user: { id: string; role: string },
  signal?: AbortSignal,
): Promise<CalendarBooking[]> {
  const query = new URLSearchParams({
    venueId,
    dateFrom: window.start + 'T00:00:00+08:00',
    dateTo: window.end + 'T00:00:00+08:00',
  })
  const response = await fetch(
    `${import.meta.env.VITE_VENUE_AVAILABILITY_SERVICE_URL || 'http://localhost:5008'}/venue-bookings?${query}`,
    { signal, headers: { 'X-Dev-User-Id': user.id, 'X-Dev-Role': user.role } },
  )
  if (!response.ok)
    throw new Error(
      `Availability unavailable (HTTP ${response.status}). Check DEV mode and selected user.`,
    )
  const body: unknown = await response.json().catch(() => null)
  if (
    !body ||
    typeof body !== 'object' ||
    !('bookings' in body) ||
    !Array.isArray(body.bookings) ||
    !body.bookings.every((item) => validBooking(item, venueId))
  )
    throw new Error('Invalid availability response. Availability is unknown.')
  if (new Set(body.bookings.map((b) => b.id)).size !== body.bookings.length)
    throw new Error(
      'Invalid availability response. Duplicate booking identity.',
    )
  return body.bookings
}

/** Unknown JSON row → validated calendar row; never silently discard unsafe records. */
function validBooking(
  value: unknown,
  venueId: string,
): value is CalendarBooking {
  if (!value || typeof value !== 'object') return false
  const b = value as Record<string, unknown>
  if (
    ![b.requestedBy, b.reviewedBy].every(
      (id) => id === null || typeof id === 'string',
    )
  )
    return false
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
  if (
    ![b.id, b.eventId, b.venueId].every(
      (id) => typeof id === 'string' && uuid.test(id),
    ) ||
    b.venueId !== venueId
  )
    return false
  if (
    !['Approved', 'Pending', 'Pending Review'].includes(String(b.status)) ||
    b.blocksSelection !== (b.status === 'Approved')
  )
    return false
  return (
    validTime(b.requestedStartTime) &&
    validTime(b.requestedEndTime) &&
    timestampMicros(b.requestedStartTime)! < timestampMicros(b.requestedEndTime)!
  )
}
/** Server SGT timestamp → valid finite calendar time, rejecting JS date rollover. */
function validTime(value: unknown): value is string {
  if (
    typeof value !== 'string' ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?\+08:00$/.test(value)
  )
    return false
  return timestampMicros(value) !== null
}
