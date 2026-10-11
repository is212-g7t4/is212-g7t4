import type { SubmittedEvent } from '../event/submission'
import type { Venue } from '../venue/venues'
import { fetchApprovedVenueId } from '../venue/eventVenue'
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
  const eventIds = Array.from(new Set(items.map(({ event }) => event.id)))
  const venueIdByEvent = new Map(await Promise.all(
    eventIds.map(async (eventId) => [eventId, await fetchApprovedVenueId(eventId)] as const),
  ))
  const venueIds = Array.from(new Set([...venueIdByEvent.values()].filter((id): id is string => Boolean(id))))
  const venues = new Map(await Promise.all(
    venueIds.map(async (venueId) => [venueId, await fetchVenue(venueId)] as const),
  ))

  return items.map(({ registration, event }) => ({
    id: registration.registration_id,
    attendeeId: registration.attendee_id,
    registrationDate: registration.registration_date,
    status: registration.status,
    attendeeName: registration.attendee_name,
    attendeeEmail: registration.attendee_email,
    attendeeOrganization: registration.attendee_organization,
    event,
    venue: venues.get(venueIdByEvent.get(event.id) ?? '') ?? null,
  }))
}
