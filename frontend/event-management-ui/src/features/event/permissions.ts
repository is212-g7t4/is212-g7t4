import type { Role } from '../../types'

export function canViewInternalEvents(role: Role) {
  return role === 'Event Coordinator' || role === 'Venue Staff' || role === 'Technical Support'
}

export function canViewMyEvents(role: Role) {
  return role === 'Event Organiser' || canViewInternalEvents(role)
}

export function canViewAllInternalEvents(role: Role, isManager: boolean) {
  return (role === 'Event Coordinator' && isManager) || role === 'Venue Staff' || role === 'Technical Support'
}

export const INTERNAL_EVENT_ACCESS_MESSAGE =
  'Event information is visible to Event Coordinators, Venue Staff, and Technical Support.'
