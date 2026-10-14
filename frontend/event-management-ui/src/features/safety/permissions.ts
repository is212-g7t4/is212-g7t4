import type { Role } from '../../types'

/** Only a Safety Officer may see the queue of events awaiting a decision. */
export function canReviewSafetyChecks(role: Role): boolean {
  return role === 'Safety Officer'
}

export const SAFETY_CHECKS_ACCESS_NOTICE =
  'The safety check queue is visible to Safety Officers.'
