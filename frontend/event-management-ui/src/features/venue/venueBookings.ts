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

const serviceUrl = () => import.meta.env.VITE_VENUE_BOOKING_SERVICE_URL || 'http://localhost:5007'

async function request(path: string, init?: RequestInit) {
  const response = await fetch(`${serviceUrl()}${path}`, init)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to complete the venue booking request.')
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
