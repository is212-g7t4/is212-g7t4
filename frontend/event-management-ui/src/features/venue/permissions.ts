import type { Role } from '../../types'
import { isCoordinator } from '../../roles'

/** SCRUM-24 AC2: the catalogue and venue details are read-only for Event
 *  Coordinators, and hidden from everyone outside these two roles. */
export function canViewVenues(role: Role): boolean {
  return isCoordinator(role) || role === 'Venue Staff'
}

/** Only Venue Staff may add or edit a venue. No Add/Edit controls exist yet —
 *  SCRUM-22 and SCRUM-23 gate theirs with this so AC2 holds by construction. */
export function canManageVenues(role: Role): boolean {
  return role === 'Venue Staff'
}

/** SCRUM-26: venue search is the Event Coordinator's tool for matching a venue
 *  to an event's requirements, so only that role sees it (SCRUM-23 AC4 calls
 *  it "the Event Coordinator's venue search"). */
export function canSearchVenues(role: Role): boolean {
  return isCoordinator(role)
}

export const VENUE_ACCESS_NOTICE = 'The Venue Catalogue is visible to Event Coordinators and Venue Staff.'

export const VENUE_SEARCH_NOTICE = 'Venue search is available to Event Coordinators.'

/** SCRUM-28 AC2: the event statuses in which a coordinator may submit a new
 *  venue request. Mirrors SUBMITTABLE_EVENT_STATUSES in
 *  services/venue-booking-service/app/routes.py, which enforces it. */
export const VENUE_REQUEST_SUBMITTABLE_STATUSES: readonly string[] = ['Submitted', 'Under Review', 'Approved', 'Safety Changes Requested']

/** Venue Staff can decide on a request only once the event is in review.
 *  Mirrors REVIEWABLE_EVENT_STATUSES in the same file. */
export const VENUE_REQUEST_REVIEWABLE_STATUSES: readonly string[] = ['Under Review', 'Approved', 'Safety Changes Requested']

export function canSubmitVenueRequest(eventStatus: string): boolean {
  return VENUE_REQUEST_SUBMITTABLE_STATUSES.includes(eventStatus)
}

/** SCRUM-28 AC4: `Pending` is the legacy seed spelling of `Pending Review`. */
export function isAwaitingVenueReview(bookingStatus: string): boolean {
  return bookingStatus === 'Pending' || bookingStatus === 'Pending Review'
}

export const VENUE_REQUEST_CLOSED_NOTICE = 'New venue requests can be submitted while the event is Submitted, Under Review, Approved or Safety Changes Requested.'

/** SCRUM-28 Part B: an existing booking can also be edited or cancelled once
 *  the event is Confirmed (which withdraws its safety approval). Mirrors
 *  CHANGEABLE_EVENT_STATUSES in services/venue-booking-service/app/routes.py. */
export const VENUE_BOOKING_CHANGEABLE_STATUSES: readonly string[] = [...VENUE_REQUEST_SUBMITTABLE_STATUSES, 'Confirmed']

export function canChangeVenueBooking(eventStatus: string): boolean {
  return VENUE_BOOKING_CHANGEABLE_STATUSES.includes(eventStatus)
}

export const venueChangeClosedNotice = (eventStatus: string) =>
  `Venue bookings can't be edited or cancelled while the event is ${eventStatus}.`

export const SAFETY_WITHDRAWAL_WARNING = "Changing this booking withdraws the event's safety approval. The event goes back to Approved; Venue Staff will re-review this booking, then resubmit the event for its safety check."

/** Why Venue Availability refused a booking or approval, keyed by its conflict
 *  type. Shared by the coordinator's booking form and the staff review dialog. */
export const VENUE_CONFLICT_MESSAGES: Record<string, string> = {
  APPROVED_BOOKING: 'An approved booking overlaps this time.',
  TENTATIVE_HOLD: 'An active tentative hold overlaps this time.',
  VENUE_CLOSURE: 'The venue is closed during this time.',
}

export const describeVenueConflicts = (types: readonly string[]) => types
  .map((type) => Object.hasOwn(VENUE_CONFLICT_MESSAGES, type) ? VENUE_CONFLICT_MESSAGES[type] : '')
  .filter(Boolean).join(' ')

const singaporeNow = (now: Date) => {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Singapore', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(now)
  const part = (type: string) => parts.find(p => p.type === type)?.value
  return `${part('year')}-${part('month')}-${part('day')}T${part('hour')}:${part('minute')}`
}

/** SCRUM-28: a booking must start in the future and fall on the event's dates
 *  (by day, so setup on the event's morning is fine). All values are SGT
 *  `YYYY-MM-DDTHH:mm`. Mirrors _booking_window_invalid in
 *  services/venue-booking-service/app/routes.py. Returns '' when valid. */
export function bookingWindowError(start: string, end: string, eventStart: string, eventEnd: string, now = new Date()): string {
  if (start <= singaporeNow(now)) return 'Booking start must be in the future.'
  if (!eventStart || !eventEnd) return ''
  const firstDay = eventStart.slice(0, 10)
  const lastDay = eventEnd.slice(0, 10)
  if (start.slice(0, 10) < firstDay || end.slice(0, 10) > lastDay) {
    return `Booking must fall within the event's dates (${firstDay} to ${lastDay}).`
  }
  return ''
}
