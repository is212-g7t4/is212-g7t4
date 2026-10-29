import type { SubmittedEvent } from '../event/submission'
import type { Venue } from '../venue/venues'
import { fetchApprovedVenueId } from '../venue/eventVenue'
import { fetchVenue } from '../venue/venues'

interface ApiRegistration {
  registration_id: string
  event_id: string
  attendee_id: string
  registration_date: string | null
  withdrawn_at: string | null
  status: string
  attendee_name: string
  attendee_email: string
  attendee_organization: string
}

// While a safety re-check is open, the composite sends the last approved venue
// name with the approved times (SCRUM-153 AC4/AC5); the live venue may differ.
type ApiEvent = SubmittedEvent & { attendeeVenueName?: string | null }

interface ApiRegistrationItem {
  registration: ApiRegistration
  event: ApiEvent
}

export interface AttendeeRegistration {
  id: string
  attendeeId: string
  registrationDate: string | null
  withdrawnAt: string | null
  status: string
  attendeeName: string
  attendeeEmail: string
  attendeeOrganization: string
  event: SubmittedEvent
  venue: Venue | null
  approvedVenueName: string | null
}

export async function loadAttendeeRegistrations(attendeeId: string): Promise<AttendeeRegistration[]> {
  const serviceUrl = import.meta.env.VITE_ATTENDEE_REGISTRATION_SERVICE_URL || 'http://localhost:5009'
  const response = await fetch(`${serviceUrl}/registrations?attendeeId=${encodeURIComponent(attendeeId)}`)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to load your registrations.')

  const items = body.registrations as ApiRegistrationItem[]
  if (items.length === 0) return []
  const eventIds = Array.from(new Set(items.filter(({ event }) => !event.attendeeVenueName).map(({ event }) => event.id)))
  const venueIdByEvent = new Map(await Promise.all(
    eventIds.map(async (eventId) => [eventId, await fetchApprovedVenueId(eventId)] as const),
  ))
  const venueIds = Array.from(new Set([...venueIdByEvent.values()].filter((id): id is string => Boolean(id))))
  const venues = new Map(await Promise.all(
    venueIds.map(async (venueId) => [venueId, await fetchVenue(venueId)] as const),
  ))

  return items.map(({ registration, event: { attendeeVenueName, ...event } }) => ({
    id: registration.registration_id,
    attendeeId: registration.attendee_id,
    registrationDate: registration.registration_date,
    withdrawnAt: registration.withdrawn_at || null,
    status: registration.status,
    attendeeName: registration.attendee_name,
    attendeeEmail: registration.attendee_email,
    attendeeOrganization: registration.attendee_organization,
    event,
    venue: attendeeVenueName ? null : venues.get(venueIdByEvent.get(event.id) ?? '') ?? null,
    approvedVenueName: attendeeVenueName || null,
  }))
}

export async function withdrawRegistration(registrationId: string, attendeeId: string) {
  const serviceUrl = import.meta.env.VITE_ATTENDEE_REGISTRATION_SERVICE_URL || 'http://localhost:5009'
  const response = await fetch(`${serviceUrl}/registrations/${encodeURIComponent(registrationId)}/withdraw`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ attendeeId }),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to withdraw this registration.')
  return {
    message: body.message as string,
    status: body.registration.status as string,
    withdrawnAt: (body.registration.withdrawn_at || null) as string | null,
  }
}
