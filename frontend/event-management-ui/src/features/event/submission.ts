import type { EventData } from '../../types'

export interface SubmittedEvent extends EventData {
  id: string
  status: 'Submitted' | 'Approved' | 'Rejected'
  submittedAt: string | null
  coordinatorId: string | null
  approvedBy: string | null
  approvedAt: string | null
}

export const requiredFields: [keyof EventData, string][] = [
  ['eventName', 'Event Name'], ['description', 'Description'], ['purpose', 'Purpose'],
  ['preferredStartDate', 'Preferred Start Date & Time'],
  ['preferredEndDate', 'Preferred End Date & Time'], ['expectedAttendance', 'Expected Attendance'],
]

export function validateEvent(event: EventData) {
  const missingFields = requiredFields.filter(([key]) => !event[key].trim()).map(([, label]) => label)
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
  return { missingFields, errors }
}

export class SubmissionError extends Error {
  missingFields: string[]
  errors: string[]
  constructor(message: string, missingFields: string[] = [], errors: string[] = []) {
    super(message)
    this.missingFields = missingFields
    this.errors = errors
  }
}

export async function eventApi(
  path: string,
  data?: EventData | { coordinatorId: string },
  method?: 'POST' | 'PATCH',
) {
  const headers: Record<string, string> = data ? { 'Content-Type': 'application/json' } : {}
  const response = await fetch(`${import.meta.env.VITE_EVENT_SERVICE_URL || 'http://localhost:5003'}${path}`, {
    method: method || (data ? 'POST' : 'GET'), headers, ...(data ? { body: JSON.stringify(data) } : {}),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new SubmissionError(body.message || 'Unable to complete the request.', body.missingFields, body.errors)
  return body
}

