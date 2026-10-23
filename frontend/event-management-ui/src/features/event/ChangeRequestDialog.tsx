import { useState } from 'react'
import type { EditableField, EventChanges } from './eventDetails'
import { EDITABLE_FIELDS, fieldLabels, sentenceList } from './eventDetails'
import type { SubmittedEvent } from './submission'
import { validateEvent } from './submission'

type Props = {
  event: SubmittedEvent
  organiserId: string
  onCancel: () => void
  onSubmitted: () => void
}

const FIELDS: { field: EditableField; label: string; type: 'text' | 'textarea' | 'number' | 'datetime' }[] = [
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

async function submitEventChangeRequest(eventId: string, organiserId: string, changes: EventChanges, reason: string) {
  const response = await fetch(`${import.meta.env.VITE_EVENT_SERVICE_URL || 'http://localhost:5003'}/events/${eventId}/change-requests`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ organiserId, changes, reason }),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to submit the change request.')
  return body
}

export function ChangeRequestDialog({ event, organiserId, onCancel, onSubmitted }: Props) {
  const [draft, setDraft] = useState<Record<EditableField, string>>(() =>
    Object.fromEntries(EDITABLE_FIELDS.map((field) => [field, event[field] || ''])) as Record<EditableField, string>,
  )
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const changes = Object.fromEntries(
    EDITABLE_FIELDS.filter((field) => draft[field] !== (event[field] || '')).map((field) => [field, draft[field]]),
  ) as EventChanges
  const changedFields = Object.keys(changes) as EditableField[]
  const validation = validateEvent({ ...event, ...draft })
  const blocker = validation.missingFields[0] || validation.errors[0]
    || (changedFields.length === 0 ? 'Propose at least one change.' : '')
    || (!reason.trim() ? 'A reason or justification is required.' : '')

  const submit = async () => {
    if (submitting || blocker) return
    setSubmitting(true)
    setError('')
    try {
      await submitEventChangeRequest(event.id, organiserId, changes, reason.trim())
      onSubmitted()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to submit the change request.')
    } finally {
      setSubmitting(false)
    }
  }

  return <section className="panel event-edit-dialog" role="dialog" aria-label="Request event changes">
    <h3>Request changes</h3>
    <p className="muted">Your event details will stay unchanged while the request is reviewed.</p>
    {FIELDS.map(({ field, label, type }) => <label className="field" key={field}>
      <span>{label}</span>
      {type === 'textarea'
        ? <textarea value={draft[field]} onChange={(change) => { setDraft((current) => ({ ...current, [field]: change.target.value })); setError('') }} />
        : <input type={type === 'datetime' ? 'datetime-local' : type} min={type === 'number' ? 1 : undefined} value={draft[field]}
            onChange={(change) => { setDraft((current) => ({ ...current, [field]: change.target.value })); setError('') }} />}
    </label>)}
    <label className="field"><span>Reason or justification <span className="required">*</span></span>
      <textarea value={reason} required onChange={(change) => { setReason(change.target.value); setError('') }} />
    </label>
    {changedFields.length > 0 && <p className="muted" role="status">Proposing changes to: {sentenceList(fieldLabels(changedFields))}.</p>}
    {error && <p className="field-error" role="alert">{error}</p>}
    {blocker && <p className="muted" role="note">{blocker}</p>}
    <button className="button primary" type="button" disabled={submitting || Boolean(blocker)} onClick={submit}>
      {submitting ? 'Submitting…' : 'Submit change request'}
    </button>{' '}
    <button className="button small" type="button" disabled={submitting} onClick={onCancel}>Cancel</button>
  </section>
}
