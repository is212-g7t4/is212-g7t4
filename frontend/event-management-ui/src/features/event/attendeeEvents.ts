import type { User } from '../../types'
import { fetchRegistrationCounts } from '../registration/registrations'
import { fetchUser } from '../user/users'
import { fetchVenue } from '../venue/venues'
import type { Venue } from '../venue/venues'
import { eventApi } from './submission'
import type { SubmittedEvent } from './submission'

export type RegistrationAvailability = 'Open' | 'Closed' | 'Full'

export interface AttendeeEvent extends SubmittedEvent {
  registrationStatus: RegistrationAvailability
  confirmedRegistrations: number
  venue: Venue | null
  organiser: User | null
  registrationDeadline?: string
  programme?: string
}

export function registrationAvailability(
  event: Pick<SubmittedEvent, 'preferredStartDate' | 'expectedAttendance'>,
  confirmedRegistrations: number,
  now: Date,
): RegistrationAvailability {
  const startsAt = new Date(event.preferredStartDate)
  if (Number.isNaN(startsAt.getTime()) || startsAt.getTime() <= now.getTime()) return 'Closed'
  const capacity = Number(event.expectedAttendance)
  if (Number.isFinite(capacity) && capacity > 0 && confirmedRegistrations >= capacity) return 'Full'
  return 'Open'
}

export async function loadAttendeeEvents(now = new Date()): Promise<AttendeeEvent[]> {
  const body = await eventApi('/events/registration')
  const confirmed = (body.events as SubmittedEvent[]).filter((event) => {
    const endsAt = new Date(event.preferredEndDate)
    return event.status === 'Confirmed' && !Number.isNaN(endsAt.getTime()) && endsAt.getTime() >= now.getTime()
  })
  if (confirmed.length === 0) return []

  const venueIds = Array.from(new Set(confirmed.map((event) => event.venueId).filter(Boolean)))
  const organiserIds = Array.from(new Set(confirmed.map((event) => event.organiserId).filter((id): id is string => Boolean(id))))
  const [counts, venueResults, organiserResults] = await Promise.all([
    fetchRegistrationCounts(confirmed.map((event) => event.id)),
    Promise.all(venueIds.map(async (id) => [id, await fetchVenue(id)] as const)),
    Promise.all(organiserIds.map(async (id) => [id, await fetchUser(id)] as const)),
  ])
  const venues = new Map(venueResults)
  const organisers = new Map(organiserResults)

  return confirmed.map((event) => {
    const confirmedRegistrations = counts[event.id]?.confirmed ?? 0
    return {
      ...event,
      confirmedRegistrations,
      registrationStatus: registrationAvailability(event, confirmedRegistrations, now),
      venue: venues.get(event.venueId) ?? null,
      organiser: event.organiserId ? organisers.get(event.organiserId) ?? null : null,
    }
  })
}
