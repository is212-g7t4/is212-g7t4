import type { EventData } from '../../types'

export interface SubmittedEvent extends EventData {
  id: string
  status: EventStatus
  submittedAt: string | null
  coordinatorId: string | null
  organiserId?: string | null
  /** The Event Coordinator Lead who made the current assignment, and when. */
  assignedBy?: string | null
  assignedAt?: string | null
  previousCoordinatorId?: string | null
  decision: EventDecision | null
  decisionHistory: EventDecision[]
  actionDetails: string
  actionHistory: EventAction[]
  clarificationHistory?: EventClarification[]
}

export interface EventClarification {
  id: string
  question: string
  requestedBy: string
  requestedAt: string
  response: string | null
  respondedBy: string | null
  respondedAt: string | null
}

export interface EventDecision {
  status: 'Approved' | 'Rejected'
  coordinatorId: string
  decidedAt: string
  reason: string | null
}

export interface EventAction {
  status: EventStatus
  details: string
  coordinatorId?: string
  /** Set when the Event Organiser answers a clarification request. */
  organiserId?: string
  recordedAt: string
  /** Set on the Safety Officer's decision entries (SCRUM-150/151). */
  remarks?: string | null
  /** Set only on a 'Safety Changes Requested' entry (SCRUM-151 AC1, AC6). */
  areas?: string[]
  /** Set on an edit entry (SCRUM-153): the fields the coordinator changed, and
   * — on a re-check — which of them withdrew the safety approval, plus the
   * round that approval belonged to (AC1, AC3). */
  changedFields?: string[]
  highImpactFields?: string[]
  withdrawnSafetyCheckId?: string
}

export interface EventProgressUpdate {
  coordinatorId: string
  status: EventStatus
  actionDetails: string
}

// The lifecycle, in order. `Confirmed` means the event passed its Operational
// Safety Check and may proceed — it is the preparation stage — and only the
// safety workflow sets it (SCRUM-152). Mirrors ALL_STATUSES in
// services/event-service/app/models.py. An organiser's 'Draft' is deliberately
// not here: drafts never reach a coordinator, as DRAFT_STATUS there.
export type EventStatus =
  | 'Submitted' | 'Under Review' | 'Clarification Requested' | 'Approved' | 'Rejected'
  | 'Pending Safety Check' | 'Confirmed' | 'Safety Changes Requested' | 'Cancelled'

export interface Coordinator {
  user_id: string
  username: string
  email: string
  role: string
  organization: string
  contact_details: string
}

export const requiredFields: [keyof EventData, string][] = [
  ['eventName', 'Event Name'], ['description', 'Description'], ['purpose', 'Purpose'],
  ['preferredStartDate', 'Preferred Start Date & Time'],
  ['preferredEndDate', 'Preferred End Date & Time'], ['expectedAttendance', 'Expected Attendance'],
]

export function validateEvent(event: EventData) {
  const missingFields = requiredFields.filter(([key]) => !event[key]?.trim()).map(([, label]) => label)
  const errors: string[] = []
  if (event.expectedAttendance.trim() && (!/^\d+$/.test(event.expectedAttendance.trim()) ||
      Number(event.expectedAttendance) < 1 || Number(event.expectedAttendance) > 2147483647)) {
    errors.push('Expected Attendance must be a positive whole number (maximum 2147483647).')
  }
  if (event.preferredStartDate && event.preferredEndDate) {
    const start = Date.parse(event.preferredStartDate)
    const end = Date.parse(event.preferredEndDate)
    if (!Number.isFinite(start) || !Number.isFinite(end)) errors.push('Preferred dates must be valid dates and times.')
    else if (end <= start) errors.push('Preferred End Date & Time must be after the start.')
  }
  if (event.withdrawalDeadline) {
    const deadline = Date.parse(event.withdrawalDeadline)
    const start = Date.parse(event.preferredStartDate)
    if (!Number.isFinite(deadline) || !Number.isFinite(start) || deadline > start) {
      errors.push('Withdrawal Deadline must be a valid date and time no later than the event start.')
    }
  }
  return { missingFields, errors }
}

// A draft needs only its name; anything else filled in must already be valid.
// Mirrors validate_draft in services/event-service/app/validation.py.
export function validateDraft(event: EventData) {
  const missingFields = event.eventName.trim() ? [] : ['Event Name']
  const { errors } = validateEvent(event)
  const startOnly = event.preferredStartDate && !event.preferredEndDate ? [event.preferredStartDate] : []
  const endOnly = event.preferredEndDate && !event.preferredStartDate ? [event.preferredEndDate] : []
  if ([...startOnly, ...endOnly].some((value) => !Number.isFinite(Date.parse(value)))) {
    errors.push('Preferred dates must be valid dates and times.')
  }
  return { missingFields, errors }
}

export class SubmissionError extends Error {
  missingFields: string[]
  errors: string[]
  // Machine-readable error code where the backend sends one, e.g.
  // 'SAFETY_APPROVAL_REQUIRED', so callers needn't match on the prose.
  code?: string
  constructor(message: string, missingFields: string[] = [], errors: string[] = [], code?: string) {
    super(message)
    this.missingFields = missingFields
    this.errors = errors
    this.code = code
  }
}

export async function eventApi(
  path: string,
  data?: (EventData & { organiserId?: string }) | EventProgressUpdate
    | { coordinatorId: string; reason?: string; message?: string }
    | { organiserId: string; response: string },
  method?: 'POST' | 'PATCH' | 'DELETE',
) {
  const headers: Record<string, string> = data ? { 'Content-Type': 'application/json' } : {}
  const response = await fetch(`${import.meta.env.VITE_EVENT_SERVICE_URL || 'http://localhost:5003'}${path}`, {
    method: method || (data ? 'POST' : 'GET'), headers, ...(data ? { body: JSON.stringify(data) } : {}),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new SubmissionError(body.message || 'Unable to complete the request.', body.missingFields, body.errors, body.code)
  return body
}

export async function assignmentApi(path: string, method: 'GET' | 'POST' = 'GET', data?: Record<string, string>) {
  const response = await fetch(`${import.meta.env.VITE_COORDINATOR_ASSIGNMENT_SERVICE_URL || 'http://localhost:5004'}${path}`, {
    method,
    headers: data ? { 'Content-Type': 'application/json' } : undefined,
    ...(data ? { body: JSON.stringify(data) } : {}),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new SubmissionError(body.error || 'Unable to complete the coordinator assignment.')
  return body
}

