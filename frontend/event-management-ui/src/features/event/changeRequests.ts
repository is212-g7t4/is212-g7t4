import type { SubmittedEvent } from './submission'
import type { EditableField, EventChanges, ArrangementConflict } from './eventDetails'

export interface EventChangeRequest {
  id: string
  eventId: string
  proposedChanges: EventChanges
  status: 'Pending Review' | 'Approved' | 'Rejected'
  requestedAt: string
  requestedBy: string
  reason: string
  reviewedBy: string | null
  reviewedAt: string | null
  rejectionReason: string | null
  event: SubmittedEvent
}

export interface ChangeRequestDecision {
  id: string
  eventId: string
  status: 'Approved' | 'Rejected'
  reviewedBy: string
  reviewedAt: string
  rejectionReason: string | null
  event: SubmittedEvent
}

export class ChangeRequestReviewError extends Error {
  code?: string
  conflicts: ArrangementConflict[]

  constructor(message: string, code?: string, conflicts: ArrangementConflict[] = []) {
    super(message)
    this.name = 'ChangeRequestReviewError'
    this.code = code
    this.conflicts = conflicts
  }
}

const serviceUrl = () => import.meta.env.VITE_EVENT_WORKFLOW_SERVICE_URL || 'http://localhost:5014'

async function request(path: string, init?: RequestInit) {
  const response = await fetch(`${serviceUrl()}${path}`, init)
  const body = await response.json().catch(() => ({}))
  if (response.ok) return body
  throw new ChangeRequestReviewError(
    body.message || 'Unable to process the change request.',
    body.code,
    body.conflicts || [],
  )
}

export async function fetchPendingChangeRequests(coordinatorId: string): Promise<EventChangeRequest[]> {
  const params = new URLSearchParams({ coordinatorId })
  const body = await request(`/change-requests?${params.toString()}`)
  return body.changeRequests
}

export async function decideChangeRequest(
  changeRequestId: string,
  coordinatorId: string,
  decision: 'Approved' | 'Rejected',
  reason?: string,
): Promise<ChangeRequestDecision> {
  return request(`/change-requests/${changeRequestId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ coordinatorId, decision, ...(reason ? { reason } : {}) }),
  })
}

export const CHANGE_REQUEST_FIELD_ORDER: EditableField[] = [
  'eventName',
  'preferredStartDate',
  'preferredEndDate',
  'expectedAttendance',
  'venueRequirements',
  'accessibilityNeeds',
  'equipmentRequirements',
  'description',
  'purpose',
  'registrationNeeds',
]
