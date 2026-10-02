import type { Role } from '../../types'

/** SCRUM-24 AC2: the catalogue and venue details are read-only for Event
 *  Coordinators, and hidden from everyone outside these two roles. */
export function canViewVenues(role: Role): boolean {
  return role === 'Event Coordinator' || role === 'Venue Staff'
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
  return role === 'Event Coordinator'
}

export const VENUE_ACCESS_NOTICE = 'The Venue Catalogue is visible to Event Coordinators and Venue Staff.'

export const VENUE_SEARCH_NOTICE = 'Venue search is available to Event Coordinators.'
