// An event's venue is its approved VenueBooking (docs/db-structure.md); the
// Event record itself does not name a venue.
const availabilityServiceUrl = () => import.meta.env.VITE_VENUE_AVAILABILITY_SERVICE_URL || 'http://localhost:5008'

interface EventBooking {
  venueId: string
  status: string
  requestedStartTime: string
}

export async function fetchApprovedVenueId(eventId: string): Promise<string | null> {
  const response = await fetch(`${availabilityServiceUrl()}/events/${encodeURIComponent(eventId)}/venue-bookings`)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to load the event venue.')
  const approved = (body.bookings as EventBooking[])
    .filter((booking) => booking.status === 'Approved')
    .sort((a, b) => a.requestedStartTime.localeCompare(b.requestedStartTime))
  return approved[0]?.venueId ?? null
}
