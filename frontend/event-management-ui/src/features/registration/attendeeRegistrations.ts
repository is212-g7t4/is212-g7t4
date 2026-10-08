import type { SubmittedEvent } from '../event/submission'
import type { Venue } from '../venue/venues'
import { fetchVenue } from '../venue/venues'

interface ApiRegistration {
  registration_id: string
  event_id: string
  attendee_id: string
  registration_date: string | null
  status: string
  attendee_name: string
  attendee_email: string
  attendee_organization: string
}

interface ApiRegistrationItem {
  registration: ApiRegistration
  event: SubmittedEvent
}

export interface AttendeeRegistration {
  id: string
  attendeeId: string
  registrationDate: string | null
  status: string
  attendeeName: string
  attendeeEmail: string
  attendeeOrganization: string
  event: SubmittedEvent
  venue: Venue | null
}

export async function loadAttendeeRegistrations(attendeeId: string): Promise<AttendeeRegistration[]> {
  const serviceUrl = import.meta.env.VITE_ATTENDEE_REGISTRATION_SERVICE_URL || 'http://localhost:5009'
  const response = await fetch(`${serviceUrl}/registrations?attendeeId=${encodeURIComponent(attendeeId)}`)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to load your registrations.')

  const items = body.registrations as ApiRegistrationItem[]
  if (items.length === 0) return []
  const venueIds = Array.from(new Set(items.map(({ event }) => event.venueId).filter(Boolean)))
  const venueResults = await Promise.all(
    venueIds.map(async (venueId) => [venueId, await fetchVenue(venueId)] as const),
  )
  const venues = new Map(venueResults)

  return items.map(({ registration, event }) => ({
    id: registration.registration_id,
    attendeeId: registration.attendee_id,
    registrationDate: registration.registration_date,
    status: registration.status,
    attendeeName: registration.attendee_name,
    attendeeEmail: registration.attendee_email,
    attendeeOrganization: registration.attendee_organization,
    event,
    venue: venues.get(event.venueId) ?? null,
  }))
}
