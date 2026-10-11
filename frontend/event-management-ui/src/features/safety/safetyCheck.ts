import type { SubmittedEvent } from '../event/submission'

// SCRUM-149: the Operational Safety Check submit flow. Calls Safety Check
// Service (the composite) — it is the service that owns this workflow, and
// there is no API gateway.

export interface OutstandingArrangement {
  type: 'venue' | 'equipment'
  id: string | null
  status: string | null
  label: string
  reason: string
}

/** One review round. Mirrors `RECORD_STATUSES` in safety-check-record-service. */
export interface SafetyCheckRecord {
  id: string
  eventId: string
  roundNumber: number
  submittedBy: string
  submittedAt: string
  equipmentPlacementNotes: string | null
  crowdMovementNotes: string | null
  status: 'Pending' | 'Safety Approved' | 'Changes Requested' | 'Safety Rejected'
  decidedBy: string | null
  decidedAt: string | null
  remarks: string | null
}

export interface SafetyReadiness {
  ready: boolean
  eventStatus: string
  outstanding: OutstandingArrangement[]
  openSafetyCheck: SafetyCheckRecord | null
}

export interface SubmitSafetyCheck {
  eventId: string
  coordinatorId: string
  equipmentPlacementNotes?: string
  crowdMovementNotes?: string
}

export const NOTES_LIMIT = 2000

/**
 * A refusal from Safety Check Service, with whatever the panel needs to
 * explain it: the outstanding arrangements for a `422` (AC2), or the open
 * round for a `409 SAFETY_CHECK_ALREADY_PENDING` (AC4).
 */
export class SafetySubmitError extends Error {
  code?: string
  outstanding?: OutstandingArrangement[]
  safetyCheck?: SafetyCheckRecord | null

  constructor(
    message: string,
    details: {
      code?: string
      outstanding?: OutstandingArrangement[]
      safetyCheck?: SafetyCheckRecord | null
    } = {},
  ) {
    super(message)
    this.name = 'SafetySubmitError'
    this.code = details.code
    this.outstanding = details.outstanding
    this.safetyCheck = details.safetyCheck
  }
}

const serviceUrl = () => import.meta.env.VITE_SAFETY_CHECK_SERVICE_URL || 'http://localhost:5012'

async function request(path: string, init?: RequestInit) {
  const response = await fetch(`${serviceUrl()}${path}`, init)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new SafetySubmitError(
      body.message || 'Unable to complete the safety check request.',
      { code: body.code, outstanding: body.outstanding, safetyCheck: body.safetyCheck },
    )
  }
  return body
}

/** Can this event be submitted yet, and if not, what's outstanding (AC2)? */
export async function fetchSafetyReadiness(
  eventId: string,
  coordinatorId: string,
): Promise<SafetyReadiness> {
  const params = new URLSearchParams({ eventId, coordinatorId })
  return (await request(`/safety-checks/readiness?${params.toString()}`)) as SafetyReadiness
}

/** Submit the event for its safety check (AC1, AC3). */
export async function submitSafetyCheck(
  details: SubmitSafetyCheck,
): Promise<{ safetyCheck: SafetyCheckRecord; event: SubmittedEvent }> {
  return request('/safety-checks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(details),
  })
}

/**
 * When the event was submitted for its safety check, from its own history —
 * the event detail page has this already and needs no extra call (AC1).
 */
export function submittedForSafetyCheckAt(event: SubmittedEvent): string | null {
  const submissions = event.actionHistory.filter(
    (action) => action.status === 'Pending Safety Check',
  )
  return submissions.length > 0 ? submissions[submissions.length - 1].recordedAt : null
}
