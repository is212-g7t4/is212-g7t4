import type { Venue } from './venues'

/** SCRUM-26: a venue's freedom in the searched window, decided by Venue
 *  Booking Service. Only these two reach the UI — Booked and Not operational
 *  venues are left out of the results entirely. */
export type Availability = 'Available' | 'Pending request'

export interface VenueSearchResult extends Venue {
  availability: Availability
}

export interface VenueSearchCriteria {
  /** AC1 required: one date with a start and end time. */
  date: string
  startTime: string
  endTime: string
  expectedAttendance: string
  /** AC1 optional. */
  minCapacity: string
  location: string
  layout: string
  facilities: string[]
  accessibility: string[]
}

export const EMPTY_CRITERIA: VenueSearchCriteria = {
  date: '',
  startTime: '',
  endTime: '',
  expectedAttendance: '',
  minCapacity: '',
  location: '',
  layout: '',
  facilities: [],
  accessibility: [],
}

/** The keys Venue Service can match against its free-text accessibility column. */
export const ACCESSIBILITY_OPTIONS: { key: string; label: string }[] = [
  { key: 'wheelchair', label: 'Wheelchair accessible' },
  { key: 'lift', label: 'Lift or elevator access' },
  { key: 'step_free', label: 'Step-free entrance' },
  { key: 'hearing_loop', label: 'Hearing loop' },
  { key: 'accessible_washroom', label: 'Accessible washroom' },
]

const REQUIRED_FIELDS: { field: keyof VenueSearchCriteria; label: string }[] = [
  { field: 'date', label: 'Date' },
  { field: 'startTime', label: 'Start time' },
  { field: 'endTime', label: 'End time' },
  { field: 'expectedAttendance', label: 'Expected attendance' },
]

/** AC2: which required criteria are still empty, in the order they appear. */
export function missingRequiredFields(criteria: VenueSearchCriteria): string[] {
  return REQUIRED_FIELDS
    .filter(({ field }) => !String(criteria[field]).trim())
    .map(({ label }) => label)
}

/** Naive local (Singapore) time — VenueBooking has no time zone, so no offset. */
function toNaiveIso(date: string, time: string): string {
  return `${date}T${time.length === 5 ? `${time}:00` : time}`
}

/** The criteria as query parameters, shared by the request and the URL state. */
export function toQuery(criteria: VenueSearchCriteria): URLSearchParams {
  const query = new URLSearchParams()
  query.set('start', toNaiveIso(criteria.date, criteria.startTime))
  query.set('end', toNaiveIso(criteria.date, criteria.endTime))
  query.set('expectedAttendance', criteria.expectedAttendance.trim())
  if (criteria.minCapacity.trim()) query.set('minCapacity', criteria.minCapacity.trim())
  if (criteria.location.trim()) query.set('location', criteria.location.trim())
  if (criteria.layout) query.set('layout', criteria.layout)
  criteria.facilities.forEach((facility) => query.append('facility', facility))
  criteria.accessibility.forEach((key) => query.append('accessibility', key))
  return query
}

const venueBookingServiceUrl = () =>
  import.meta.env.VITE_VENUE_BOOKING_SERVICE_URL || 'http://localhost:5007'

/** AC3: the shortlist of venues that fit and are free, from the composite. */
export async function searchVenues(criteria: VenueSearchCriteria): Promise<VenueSearchResult[]> {
  const response = await fetch(`${venueBookingServiceUrl()}/venue-search?${toQuery(criteria)}`)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to search venues right now.')
  return body.venues as VenueSearchResult[]
}
