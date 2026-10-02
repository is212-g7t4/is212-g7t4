export interface Registration {
  id: string
  attendeeName: string
  attendeeEmail: string
  attendeeOrganization: string
  registrationDate: string | null
  status: string
}

interface ApiRegistration {
  registration_id: string
  event_id: string | null
  attendee_id: string | null
  registration_date: string | null
  status: string
  attendee_name: string
  attendee_email: string
  attendee_organization: string
}

function toRegistration(apiRegistration: ApiRegistration): Registration {
  return {
    id: apiRegistration.registration_id,
    attendeeName: apiRegistration.attendee_name,
    attendeeEmail: apiRegistration.attendee_email,
    attendeeOrganization: apiRegistration.attendee_organization,
    registrationDate: apiRegistration.registration_date,
    status: apiRegistration.status,
  }
}

export interface RegistrationCount {
  total: number
  confirmed: number
}

const registrationApi = () => import.meta.env.VITE_REGISTRATION_SERVICE_URL || 'http://localhost:5005'

export async function fetchRegistrationCounts(eventIds: string[]): Promise<Record<string, RegistrationCount>> {
  if (eventIds.length === 0) return {}
  const response = await fetch(`${registrationApi()}/registrations/counts?eventIds=${eventIds.join(',')}`)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to load registration counts.')
  return body.counts as Record<string, RegistrationCount>
}

export async function fetchRegistrations(eventId: string): Promise<Registration[]> {
  const response = await fetch(
    `${registrationApi()}/registrations?eventId=${eventId}`,
  )
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to load registrations.')
  return (body.registrations as ApiRegistration[]).map(toRegistration)
}
