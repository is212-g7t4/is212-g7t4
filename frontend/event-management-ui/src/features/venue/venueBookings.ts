import type { User } from '../../types'

export interface VenueBooking {
  id: string
  eventId: string
  venueId: string
  venueName: string
  requestedStartTime: string
  requestedEndTime: string
  requiredCapacity: number
  venueRequirements: string
  status: string
  requestedBy: string
  reviewedBy: string | null
  /** SCRUM-28 AC2: when the request was recorded; null for legacy rows. */
  requestedAt?: string | null
  /** SCRUM-28 AC4: set by the staff queue when the request still needs a decision. */
  awaitingReview?: boolean
  /** SCRUM-29 AC2/AC3: when Venue Staff decided; null while undecided and for legacy rows. */
  reviewedAt?: string | null
  /** SCRUM-29 AC4/AC6: why Venue Staff rejected it; null unless rejected with a reason. */
  rejectionReason?: string | null
  safetyFeedback?: { reason: string | null; requestedChanges: string[] } | null
  closureRejection?: { closureId: string; startDateTime: string; endDateTime: string; reason: string; rejectedAt: string } | null
}

export interface CreateVenueBooking {
  eventId: string
  venueId: string
  coordinatorId: string
  requestedStartTime: string
  requestedEndTime: string
  requiredCapacity: number
  venueRequirements: string
}

export class VenueBookingError extends Error {
  status: number
  code?: string
  conflictTypes: string[]

  constructor(status: number, body: unknown) {
    const data = body && typeof body === 'object' ? body as Record<string, unknown> : {}
    super(typeof data.message === 'string' && data.message.trim() ? data.message : 'Unable to complete the venue booking request.')
    this.status = status
    this.code = typeof data.code === 'string' ? data.code : undefined
    this.conflictTypes = Array.isArray(data.conflictTypes)
      ? [...new Set(data.conflictTypes.filter((value): value is string => typeof value === 'string'))]
      : []
  }
}

const serviceUrl = () => import.meta.env.VITE_VENUE_BOOKING_SERVICE_URL || 'http://localhost:5007'

async function request(path: string, init?: RequestInit) {
  const uncertainMessage = init?.method
    ? 'Unable to confirm whether the booking request was saved. Check existing bookings before trying again.'
    : 'Unable to load venue bookings.'
  const response = await fetch(`${serviceUrl()}${path}`, init).catch(() => {
    throw new Error(uncertainMessage)
  })
  const body = await response.json().catch(() => {
    if (response.ok) throw new Error(uncertainMessage)
    return {}
  })
  if (!response.ok) throw new VenueBookingError(response.status, body)
  return body
}

export async function fetchVenueBookings(eventId: string, coordinatorId: string): Promise<VenueBooking[]> {
  const body = await request(
    `/events/${encodeURIComponent(eventId)}/booking-requests?coordinatorId=${encodeURIComponent(coordinatorId)}`,
  )
  return body.bookings as VenueBooking[]
}

export async function createVenueBooking(details: CreateVenueBooking): Promise<VenueBooking> {
  return request('/booking-requests', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(details),
  })
}

export async function updateVenueBooking(bookingId: string, details: CreateVenueBooking): Promise<VenueBooking> {
  return request(`/booking-requests/${encodeURIComponent(bookingId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(details),
  })
}

export async function cancelVenueBooking(
  bookingId: string,
  eventId: string,
  coordinatorId: string,
): Promise<VenueBooking> {
  return request(`/booking-requests/${encodeURIComponent(bookingId)}/cancel`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ eventId, coordinatorId }),
  })
}

export interface VenueRequestEvent {
  eventId: string
  eventName: string
  eventStatus: string
  coordinatorId: string | null
  /** SCRUM-28 AC3: the event's own preferred dates; null when unset. */
  eventStart?: string | null
  eventEnd?: string | null
  awaitingReviewCount?: number
  bookings: VenueBooking[]
}

export async function fetchVenueRequests(user: Pick<User, 'id' | 'role'>, status?: string): Promise<VenueRequestEvent[]> {
  const body = await request(`/booking-requests${status ? `?status=${encodeURIComponent(status)}` : ''}`, {
    headers: { 'X-Dev-User-Id': user.id, 'X-Dev-Role': user.role },
  })
  return body.events as VenueRequestEvent[]
}

export async function reviewVenueRequest(
  bookingId: string,
  status: 'Approved' | 'Rejected',
  user: Pick<User, 'id' | 'role'>,
  rejectionReason?: string,
): Promise<VenueBooking> {
  return request(`/booking-requests/${encodeURIComponent(bookingId)}/review`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', 'X-Dev-User-Id': user.id, 'X-Dev-Role': user.role },
    // SCRUM-29 AC4: only a rejection carries a reason.
    body: JSON.stringify(status === 'Rejected' ? { status, reviewedBy: user.id, rejectionReason } : { status, reviewedBy: user.id }),
  })
}

/** SCRUM-29 AC1: one request with the event's and venue's details, as Venue Staff open it. */
export interface VenueRequestDetail {
  booking: VenueBooking & { occupiedFrom: string | null; occupiedTo: string | null }
  event: {
    id: string
    eventName: string | null
    status: string | null
    coordinatorId: string | null
    preferredStartDate: string | null
    preferredEndDate: string | null
    expectedAttendance: string | null
    venueRequirements: string | null
    accessibilityNeeds: string | null
  }
  venue: {
    id: string
    name: string
    capacity: number | null
    status: string
    setupTimeMinutes: number
    turnaroundTimeMinutes: number
  }
  canDecide: boolean
  decisionBlockedReason: string | null
}

export async function fetchVenueRequestDetail(bookingId: string, user: Pick<User, 'id' | 'role'>): Promise<VenueRequestDetail> {
  return request(`/booking-requests/${encodeURIComponent(bookingId)}`, {
    headers: { 'X-Dev-User-Id': user.id, 'X-Dev-Role': user.role },
  })
}
