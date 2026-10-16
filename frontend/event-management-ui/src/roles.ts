import type { Role } from './types'

// The Lead is an Event Coordinator with extra rights (assigning coordinators,
// seeing every event), so every coordinator screen is open to them too.
export function isCoordinator(role: Role) {
  return role === 'Event Coordinator' || role === 'Event Coordinator Lead'
}

export function isLead(role: Role) {
  return role === 'Event Coordinator Lead'
}
