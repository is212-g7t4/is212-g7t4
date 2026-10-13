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
