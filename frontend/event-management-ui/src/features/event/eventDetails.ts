import type { SubmittedEvent } from './submission'
import { authFetch } from '../auth/session'

// SCRUM-20: editing an event's details. Calls Event Workflow Service (the
// composite), which validates a high-impact change against the event's venue
// and equipment arrangements before Event Service saves it. Event Service
// still owns the fields and the low/high-impact split, and there is no API
// gateway.

/** The five details in SCRUM-153 AC1 whose change invalidates a safety review.
 * Mirrors `HIGH_IMPACT_FIELDS` in services/event-service/app/models.py. */
export const HIGH_IMPACT_FIELDS = [
  'preferredStartDate',
  'preferredEndDate',
  'expectedAttendance',
  'venueRequirements',
  'equipmentRequirements',
  'accessibilityNeeds',
] as const

/** AC2's fields: an edit to any of these leaves the event 'Confirmed'. */
export const LOW_IMPACT_FIELDS = [
  'eventName',
  'description',
  'purpose',
  'registrationNeeds',
] as const

export type EditableField =
  | (typeof HIGH_IMPACT_FIELDS)[number]
  | (typeof LOW_IMPACT_FIELDS)[number]

export const EDITABLE_FIELDS: EditableField[] = [...LOW_IMPACT_FIELDS, ...HIGH_IMPACT_FIELDS]

/** Human labels for the confirm step and the history line (AC1's "told why").
 * Both date fields share one label, so changing start and end reads
 * "Date/time" once. Mirrors `FIELD_LABELS` in event-service. */
export const FIELD_LABELS: Record<EditableField, string> = {
  preferredStartDate: 'Date/time',
  preferredEndDate: 'Date/time',
  expectedAttendance: 'Expected attendance',
  venueRequirements: 'Venue requirements',
  equipmentRequirements: 'Equipment requirements',
  accessibilityNeeds: 'Accessibility needs',
  eventName: 'Event name',
  description: 'Description',
  purpose: 'Purpose',
  registrationNeeds: 'Registration needs',
}

/** The editable fields in form order, with their form label and input type.
 * Shared by the organiser's change-request form (SCRUM-42) and the
 * amendment request and response (SCRUM-16), so the three can't drift. */
export const FIELD_INPUTS: { field: EditableField; label: string; type: 'text' | 'textarea' | 'number' | 'datetime' }[] = [
  { field: 'eventName', label: 'Event Name', type: 'text' },
  { field: 'preferredStartDate', label: 'Preferred Start Date & Time', type: 'datetime' },
  { field: 'preferredEndDate', label: 'Preferred End Date & Time', type: 'datetime' },
  { field: 'expectedAttendance', label: 'Expected Attendance', type: 'number' },
  { field: 'venueRequirements', label: 'Venue Requirements', type: 'textarea' },
  { field: 'accessibilityNeeds', label: 'Accessibility Needs', type: 'textarea' },
  { field: 'equipmentRequirements', label: 'Equipment Requirements', type: 'textarea' },
  { field: 'description', label: 'Description', type: 'textarea' },
  { field: 'purpose', label: 'Purpose', type: 'textarea' },
  { field: 'registrationNeeds', label: 'Registration Requirements', type: 'textarea' },
]

/** One checkbox per FIELD_LABELS label, in form order: "Date/time" is a single
 * option carrying both date fields, because Event Service flags them as a pair
 * (SCRUM-16). */
export const AMENDMENT_OPTIONS: { label: string; fields: EditableField[] }[] = FIELD_INPUTS.reduce(
  (options, { field }) => {
    const label = FIELD_LABELS[field]
    const existing = options.find((option) => option.label === label)
    if (existing) existing.fields.push(field)
    else options.push({ label, fields: [field] })
    return options
  },
  [] as { label: string; fields: EditableField[] }[],
)

export function isHighImpact(field: string): boolean {
  return (HIGH_IMPACT_FIELDS as readonly string[]).includes(field)
}

/** The distinct labels for `fields`, deduplicated and in a stable order. */
export function fieldLabels(fields: readonly string[]): string[] {
  const labels: string[] = []
  for (const field of EDITABLE_FIELDS) {
    const label = FIELD_LABELS[field]
    if (fields.includes(field) && !labels.includes(label)) labels.push(label)
  }
  return labels
}

/** "A", "A and B", "A, B and C" — for the sentences AC1 shows the coordinator. */
export function sentenceList(labels: string[]): string {
  if (labels.length <= 1) return labels.join('')
  return `${labels.slice(0, -1).join(', ')} and ${labels[labels.length - 1]}`
}

export type EventChanges = Partial<Record<EditableField, string>>

/**
 * Event Service's `409 SAFETY_RECHECK_REQUIRED` (SCRUM-153 AC1): the edit was
 * **not** saved, and going ahead will withdraw the event's safety approval.
 * Carries what the confirm step has to show.
 */
export class SafetyRecheckRequired extends Error {
  changedFields: string[]
  highImpactFields: string[]
  labels: string[]

  constructor(
    message: string,
    details: { changedFields?: string[]; highImpactFields?: string[]; labels?: string[] } = {},
  ) {
    super(message)
    this.name = 'SafetyRecheckRequired'
    this.changedFields = details.changedFields || []
    this.highImpactFields = details.highImpactFields || []
    this.labels = details.labels || []
  }
}

/** One reason a high-impact change was refused (SCRUM-20 AC3). */
export type ArrangementConflict = {
  field: string
  area: 'venue' | 'equipment'
  message: string
}

/** Any other refusal from the service, with its code so callers needn't
 * match on the prose (e.g. 'EVENT_UNDER_SAFETY_REVIEW', 'EVENT_NOT_EDITABLE',
 * 'CHANGE_CONTRADICTS_ARRANGEMENTS'). */
export class EventEditError extends Error {
  code?: string
  missingFields: string[]
  errors: string[]
  conflicts: ArrangementConflict[]

  constructor(
    message: string,
    details: {
      code?: string
      missingFields?: string[]
      errors?: string[]
      conflicts?: ArrangementConflict[]
    } = {},
  ) {
    super(message)
    this.name = 'EventEditError'
    this.code = details.code
    this.missingFields = details.missingFields || []
    this.errors = details.errors || []
    this.conflicts = details.conflicts || []
  }
}

const serviceUrl = () => import.meta.env.VITE_EVENT_WORKFLOW_SERVICE_URL || 'http://localhost:5014'

/**
 * Save an edit (AC2), or learn that it needs a safety re-check first (AC1).
 *
 * This is deliberately the **first** call the dialog makes, even for a
 * high-impact change: Event Service decides which fields are high-impact, and
 * a low-impact edit must work with no safety call at all. A high-impact change
 * to a `Confirmed` event throws `SafetyRecheckRequired` with nothing saved.
 */
export async function updateEventDetails(
  eventId: string,
  coordinatorId: string,
  changes: EventChanges,
): Promise<SubmittedEvent> {
  const response = await authFetch(`${serviceUrl()}/events/${eventId}/details`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ coordinatorId, changes }),
  })
  const body = await response.json().catch(() => ({}))
  if (response.ok) return body as SubmittedEvent
  if (body.code === 'SAFETY_RECHECK_REQUIRED') {
    throw new SafetyRecheckRequired(body.message || 'This change needs a new safety check.', {
      changedFields: body.changedFields,
      highImpactFields: body.highImpactFields,
      labels: body.labels,
    })
  }
  throw new EventEditError(body.message || 'Unable to save these event details.', {
    code: body.code,
    missingFields: body.missingFields,
    errors: body.errors,
    conflicts: body.conflicts,
  })
}
