import { useState } from 'react'
import type { FormEvent } from 'react'
import { FIELD_INPUTS, fieldLabels, sentenceList } from './eventDetails'
import type { EditableField } from './eventDetails'
import { eventApi, SubmissionError } from './submission'
import type { SubmittedEvent } from './submission'
import { formatTimestamp } from './formatDates'

// SCRUM-16 AC3/AC4: the organiser edits only the fields the coordinator
// flagged and resubmits. Unflagged fields get no input at all; Event Service
// enforces the same lock, so this only mirrors it.
export function AmendmentResponseForm({ event, organiserId, resolveUserName, onResubmitted }: {
  event: SubmittedEvent
  organiserId: string
  resolveUserName?: (userId: string | null | undefined) => string | null
  onResubmitted: (updated: SubmittedEvent) => void
}) {
  const amendment = [...(event.amendmentHistory || [])].reverse().find((round) => !round.resubmittedAt)
  const inputs = FIELD_INPUTS.filter(({ field }) => amendment?.fields.includes(field))
  const [draft, setDraft] = useState<Partial<Record<EditableField, string>>>(() =>
    Object.fromEntries(inputs.map(({ field }) => [field, event[field] || ''])))
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<{ message: string; details: string[] } | null>(null)

  if (!amendment) return null

  const changes = Object.fromEntries(
    inputs.filter(({ field }) => draft[field] !== (event[field] || '')).map(({ field }) => [field, draft[field] || '']),
  )
  const hasChanges = Object.keys(changes).length > 0

  const update = (field: EditableField, value: string) => {
    setDraft((current) => ({ ...current, [field]: value }))
    setError(null)
  }

  const submit = async (formEvent: FormEvent) => {
    formEvent.preventDefault()
    if (!hasChanges || submitting) return
    setSubmitting(true)
    setError(null)
    try {
      const updated = await eventApi(
        `/events/${event.id}/amendment-response`,
        { organiserId, changes, ...(note.trim() ? { note: note.trim() } : {}) },
        'PATCH',
      )
      onResubmitted(updated)
    } catch (cause) {
      setError(cause instanceof SubmissionError
        ? { message: cause.message, details: [...cause.missingFields.map((field) => `${field} is required.`), ...cause.errors] }
        : { message: 'Unable to resubmit your amended request.', details: [] })
    } finally {
      setSubmitting(false)
    }
  }

  return <section className="event-card-section">
    <h3>Amendment required</h3>
    <p>The assigned Event Coordinator asked you to change {sentenceList(fieldLabels(amendment.fields))}. Every other detail stays as submitted.</p>
    <p style={{ whiteSpace: 'pre-wrap' }}>{amendment.reason}</p>
    <p className="muted">Requested by {resolveUserName?.(amendment.requestedBy) || amendment.requestedBy} on {formatTimestamp(amendment.requestedAt)}</p>
    <form onSubmit={submit}>
      {inputs.map(({ field, label, type }) => <label className="field" key={field}>
        <span>{label}</span>
        {type === 'textarea'
          ? <textarea value={draft[field] || ''} disabled={submitting} onChange={(change) => update(field, change.target.value)} />
          : <input type={type === 'datetime' ? 'datetime-local' : type} min={type === 'number' ? 1 : undefined} value={draft[field] || ''}
              disabled={submitting} onChange={(change) => update(field, change.target.value)} />}
      </label>)}
      <label className="field"><span>Note to coordinator</span>
        <textarea value={note} maxLength={1000} disabled={submitting} onChange={(change) => setNote(change.target.value)} placeholder="Optional: explain your changes, or anything you left as it was." />
        <small>{note.length}/1000 characters</small>
      </label>
      {error && <div className="field-error" role="alert">
        <p>{error.message}</p>
        {error.details.length > 0 && <ul>{error.details.map((detail) => <li key={detail}>{detail}</li>)}</ul>}
      </div>}
      {!hasChanges && <p className="muted" role="note">Change at least one flagged field before resubmitting.</p>}
      <button className="button primary" type="submit" disabled={!hasChanges || submitting}>{submitting ? 'Resubmitting…' : 'Resubmit'}</button>
    </form>
  </section>
}
