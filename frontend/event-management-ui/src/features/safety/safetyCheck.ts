import type { EventChanges } from '../event/eventDetails'
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

/** The three planning areas a change request can flag (SCRUM-151 AC1). Mirrors
 * `FLAG_AREAS` in safety-check-record-service. */
export type SafetyFlagArea = 'venue arrangement' | 'technical arrangement' | 'event details'

export const FLAG_AREAS: { value: SafetyFlagArea; label: string }[] = [
  { value: 'venue arrangement', label: 'Venue arrangement' },
  { value: 'technical arrangement', label: 'Technical / equipment arrangement' },
  { value: 'event details', label: 'Event details' },
]

export interface SafetyCheckFlag {
  id: string
  area: SafetyFlagArea
  bookingId: string | null
  equipmentRequestId: string | null
  changeRequired: string
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
  status: 'Pending' | 'Safety Approved' | 'Changes Requested' | 'Safety Rejected' | 'Approval Withdrawn'
  decidedBy: string | null
  decidedAt: string | null
  remarks: string | null
  /** SCRUM-153 AC3: set on a round whose approval a later high-impact change
   * withdrew. Its decision fields above are kept, so the history still shows
   * who approved it and when. Null on every other round. */
  withdrawnAt: string | null
  withdrawnBy: string | null
  withdrawalReason: string | null
  flags: SafetyCheckFlag[]
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

export interface ApproveSafetyCheck {
  eventId: string
  safetyOfficerId: string
  remarks?: string
}

export interface RequestSafetyChanges {
  eventId: string
  safetyOfficerId: string
  reason: string
  flags: { area: SafetyFlagArea; changeRequired: string }[]
}

export interface RejectSafetyCheck {
  eventId: string
  safetyOfficerId: string
  reason: string
}

export interface RecheckSafety {
  eventId: string
  coordinatorId: string
  changes: EventChanges
}

/** The venue bookings a rejection released, and any it couldn't (SCRUM-151 AC5). */
export interface SafetyRejectionRelease {
  venueBookingsReleased: string[]
  venueBookingsNotReleased: string[]
  equipment: string
}

/** One row of the Safety Officer's queue (SCRUM-162). */
export interface SafetyQueueItem {
  eventId: string
  eventName: string
  preferredStartDate: string
  preferredEndDate: string
  expectedAttendance: string
  venues: { id: string; name: string }[]
  safetyCheckId: string
  /** When the open round was submitted — a resubmission's own date, not the first. */
  submittedAt: string | null
  roundNumber: number
  resubmission: boolean
}

export interface SafetyReview {
  event: SubmittedEvent
  safetyCheck: SafetyCheckRecord
  venues: {
    bookingId: string
    venueId: string
    name: string | null
    expectedAttendance: string | null
    capacity: number | null
    overCapacity: boolean
    layout: string | null
    emergencyAccess: string | null
    accessibility: string | null
    restrictions: string | null
    venueRequirements: string | null
    status: string | null
  }[]
  equipment: {
    requestId: string
    name: string | null
    description: string | null
    quantity: number | null
    technicalRequirements: string | null
    status: string | null
  }[]
  history: SafetyCheckRecord[]
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

/**
 * SCRUM-162: events awaiting a safety check, nearest event date first. The
 * service checks the role itself and sorts the list; the page only renders it.
 */
export async function fetchSafetyQueue(safetyOfficerId: string): Promise<SafetyQueueItem[]> {
  const params = new URLSearchParams({ safetyOfficerId })
  const body = await request(`/safety-checks/queue?${params.toString()}`)
  return body.events as SafetyQueueItem[]
}

/** Load event, arrangement and prior-decision context for the officer's review. */
export async function fetchSafetyReview(
  eventId: string,
  safetyOfficerId: string,
): Promise<SafetyReview> {
  const params = new URLSearchParams({ safetyOfficerId })
  return (await request(`/safety-checks/${eventId}/review?${params.toString()}`)) as SafetyReview
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

/** Approve the event's Operational Safety Check (SCRUM-150 AC1, AC2). */
export async function approveSafetyCheck(
  details: ApproveSafetyCheck,
): Promise<{ safetyCheck: SafetyCheckRecord; event: SubmittedEvent }> {
  return request('/safety-checks/approve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(details),
  })
}

/** Request changes to the event's safety arrangements (SCRUM-151 AC1, AC2). */
export async function requestSafetyChanges(
  details: RequestSafetyChanges,
): Promise<{ safetyCheck: SafetyCheckRecord; event: SubmittedEvent }> {
  return request('/safety-checks/request-changes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(details),
  })
}

/**
 * Reject the event's Operational Safety Check (SCRUM-151 AC3, AC4, AC5).
 * Always sends `confirmed: true` — call this only once the officer has gone
 * through the UI's own confirm step.
 */
export async function rejectSafetyCheck(
  details: RejectSafetyCheck,
): Promise<{ safetyCheck: SafetyCheckRecord; event: SubmittedEvent; release: SafetyRejectionRelease }> {
  return request('/safety-checks/reject', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...details, confirmed: true }),
  })
}

/**
 * Withdraw the event's safety approval after a high-impact change (SCRUM-153).
 *
 * Call this **only** after `updateEventDetails` threw `SafetyRecheckRequired`
 * and the coordinator confirmed, with the same `changes`: this one request
 * withdraws the approval, opens the next round, saves the edit and moves the
 * event back to 'Pending Safety Check'.
 */
export async function recheckSafety(
  details: RecheckSafety,
): Promise<{
  event: SubmittedEvent
  safetyCheck: SafetyCheckRecord
  withdrawnSafetyCheck: SafetyCheckRecord
  changedFields: string[]
  reason: string
}> {
  return request('/safety-checks/recheck', {
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
