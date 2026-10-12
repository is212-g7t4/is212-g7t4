import type { Role, Route } from '../../types'
import { isCoordinator, isLead } from '../../roles'

export function canViewInternalEvents(role: Role) {
  return isCoordinator(role) || role === 'Venue Staff' || role === 'Technical Support' || role === 'Safety Officer'
}

export function canViewMyEvents(role: Role) {
  return role === 'Event Organiser' || canViewInternalEvents(role)
}

// Sent to Event Service as ?viewerRole= to widen "assigned to me" to every event.
export function canViewAllInternalEvents(role: Role) {
  return isLead(role) || role === 'Venue Staff' || role === 'Technical Support' || role === 'Safety Officer'
}

export const INTERNAL_EVENT_ACCESS_MESSAGE =
  'Event information is visible to Event Coordinators, Venue Staff, Technical Support, and Safety Officers.'

// Event Coordinators (and the Lead) see their event screens as tabs of one
// Events page. The unassigned queue is Lead-only.
export function coordinatorEventTabs(role: Role): Route[] {
  return isLead(role) ? ['queue', 'myEvents', 'review'] : ['myEvents', 'review']
}
