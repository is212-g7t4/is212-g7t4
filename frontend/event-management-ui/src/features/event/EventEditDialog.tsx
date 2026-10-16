import { useState } from 'react'
import {
  EDITABLE_FIELDS,
  EventEditError,
  HIGH_IMPACT_FIELDS,
  SafetyRecheckRequired,
  fieldLabels,
  sentenceList,
  updateEventDetails,
} from './eventDetails'
import type { EditableField, EventChanges } from './eventDetails'
import { validateEvent } from './submission'
import type { SubmittedEvent } from './submission'
import { recheckSafety } from '../safety/safetyCheck'

type Props = {
  event: SubmittedEvent
  coordinatorId: string
  onCancel: () => void
  /** Called with the saved event and the line to show, so the page can refresh. */
  onSaved: (event: SubmittedEvent, message: string) => void
}

type Field = {
  field: EditableField
  label: string
  type: 'text' | 'textarea' | 'number' | 'datetime'
  /** One of the six `requiredFields` a submission needs, so an edit can't
   * leave the event in a state it couldn't have been submitted in. */
  required?: true
}

// Grouped the way the consequence falls, not the way the submit form is laid
// out: a coordinator editing a Confirmed event needs to see at a glance which
// fields cost them their safety approval (SCRUM-153 AC1). The labels match
// EventRequestForm's, so the same field reads the same way in both.
const SAFETY_RELEVANT: Field[] = [
  { field: 'preferredStartDate', label: 'Preferred Start Date & Time', type: 'datetime', required: true },
  { field: 'preferredEndDate', label: 'Preferred End Date & Time', type: 'datetime', required: true },
  { field: 'expectedAttendance', label: 'Expected Attendance', type: 'number', required: true },
  { field: 'venueRequirements', label: 'Venue Requirements', type: 'textarea' },
  { field: 'equipmentRequirements', label: 'Equipment Requirements', type: 'textarea' },
  { field: 'accessibilityNeeds', label: 'Accessibility Needs', type: 'textarea' },
]
const OTHER: Field[] = [
  { field: 'eventName', label: 'Event Name', type: 'text', required: true },
  { field: 'description', label: 'Description', type: 'textarea', required: true },
  { field: 'purpose', label: 'Purpose', type: 'textarea', required: true },
  { field: 'registrationNeeds', label: 'Registration Needs', type: 'textarea' },
]

/**
 * SCRUM-153: the assigned coordinator edits an event's details.
 *
 * Two steps, because a high-impact change to a `Confirmed` event costs the
 * event its safety approval and that must not happen by accident:
 *
 * 1. Save. Event Service decides what is high-impact, so the edit always goes
 *    there first. A low-impact one saves and the event stays `Confirmed`
 *    (AC2); a high-impact one comes back `SAFETY_RECHECK_REQUIRED` with
 *    nothing written.
 * 2. Confirm. The coordinator is told exactly what changed and what it costs,
 *    then `recheckSafety` withdraws the approval, saves the edit and moves
 *    the event to `Pending Safety Check` (AC1).
 *
 * The API enforces this on its own (the gate), so this dialog is the
 * explanation, not the enforcement.
 */
export function EventEditDialog({ event, coordinatorId, onCancel, onSaved }: Props) {
  const [draft, setDraft] = useState<Record<EditableField, string>>(() =>
    Object.fromEntries(
      EDITABLE_FIELDS.map((field) => [field, event[field] || '']),
    ) as Record<EditableField, string>,
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [validationErrors, setValidationErrors] = useState<string[]>([])
  const [recheck, setRecheck] = useState<SafetyRecheckRequired | null>(null)

  // Only the fields the user actually touched are sent. Event Service ignores
  // a resent identical value anyway, but sending less keeps the history line
  // honest about what was edited.
  const changes: EventChanges = Object.fromEntries(
    EDITABLE_FIELDS.filter((field) => draft[field] !== (event[field] || '')).map((field) => [
      field,
      draft[field],
    ]),
  )
  const changedFields = Object.keys(changes) as EditableField[]
  const highImpact = changedFields.filter((field) =>
    (HIGH_IMPACT_FIELDS as readonly string[]).includes(field),
  )
  const localCheck = validateEvent({ ...event, ...draft })
  const blocker = localCheck.missingFields.length > 0
    ? `${localCheck.missingFields.join(', ')} ${localCheck.missingFields.length === 1 ? 'is' : 'are'} required.`
    : localCheck.errors[0] || (changedFields.length === 0 ? 'Change a detail to save.' : '')

  const update = (field: EditableField, value: string) => {
    setDraft((previous) => ({ ...previous, [field]: value }))
    setError('')
    setValidationErrors([])
  }

  const fail = (cause: unknown, fallback: string) => {
    if (cause instanceof EventEditError) {
      setError(cause.message)
      setValidationErrors([...cause.missingFields, ...cause.errors])
      return
    }
    setError(cause instanceof Error ? cause.message : fallback)
  }

  const save = async () => {
    if (saving || blocker) return
    setSaving(true)
    setError('')
    setValidationErrors([])
    try {
      const updated = await updateEventDetails(event.id, coordinatorId, changes)
      onSaved(updated, 'Event details saved.')
    } catch (cause) {
      // Not an error the coordinator has to fix: the edit is valid, it just
      // costs the safety approval. Move to the confirm step instead.
      if (cause instanceof SafetyRecheckRequired) setRecheck(cause)
      else fail(cause, 'Unable to save these event details.')
    } finally {
      setSaving(false)
    }
  }

  const confirmRecheck = async () => {
    if (saving) return
    setSaving(true)
    setError('')
    try {
      const result = await recheckSafety({ eventId: event.id, coordinatorId, changes })
      onSaved(
        result.event,
        `Saved. Safety approval withdrawn because ${sentenceList(
          fieldLabels(result.changedFields),
        )} changed. The event is back to Pending Safety Check.`,
      )
    } catch (cause) {
      // Back to the form: whatever Event Service refused (a stale round, the
      // status having moved) is shown there, and nothing was saved.
      setRecheck(null)
      fail(cause, 'Unable to withdraw this event’s safety approval.')
    } finally {
      setSaving(false)
    }
  }

  if (recheck) {
    const labels = recheck.labels.length > 0 ? recheck.labels : fieldLabels(highImpact)
    return <div className="panel event-edit-confirm" role="dialog" aria-label="Withdraw safety approval?">
      <h3>Withdraw safety approval?</h3>
      <p>
        You changed <strong>{sentenceList(labels)}</strong>. This event will go back to{' '}
        <strong>Pending Safety Check</strong> and can’t proceed to preparation until a Safety
        Officer approves it again. New attendee registrations close until then.
      </p>
      {error && <p className="field-error" role="alert">{error}</p>}
      <button className="button primary" type="button" disabled={saving} onClick={confirmRecheck}>
        {saving ? 'Saving…' : 'Save and withdraw approval'}
      </button>{' '}
      <button className="button small" type="button" disabled={saving} onClick={() => setRecheck(null)}>
        Go back
      </button>
    </div>
  }

  return <div className="panel event-edit-dialog" role="dialog" aria-label="Edit event details">
    <h3>Edit event details</h3>
    {event.status === 'Confirmed' && <p className="muted" role="note">
      Changing safety-relevant details withdraws the safety approval.
    </p>}
    {event.status === 'Pending Safety Check' && <p className="muted" role="note">
      This event is waiting for its Operational Safety Check, so only the other details
      below can be changed until the Safety Officer decides.
    </p>}

    <fieldset>
      <legend>Safety-relevant details</legend>
      {SAFETY_RELEVANT.map((item) => <EditField key={item.field} item={item} value={draft[item.field]} onChange={update} />)}
    </fieldset>
    <fieldset>
      <legend>Other details</legend>
      {OTHER.map((item) => <EditField key={item.field} item={item} value={draft[item.field]} onChange={update} />)}
    </fieldset>

    {changedFields.length > 0 && <p className="muted" role="status">
      Changing: {sentenceList(fieldLabels(changedFields))}.
      {highImpact.length > 0 && event.status === 'Confirmed' &&
        ' Saving will ask you to confirm withdrawing the safety approval.'}
    </p>}
    {error && <p className="field-error" role="alert">{error}</p>}
    {validationErrors.length > 0 && <ul className="field-error">
      {validationErrors.map((message) => <li key={message}>{message}</li>)}
    </ul>}
    {blocker && <p className="muted" role="note">{blocker}</p>}

    <button className="button primary" type="button" disabled={saving || Boolean(blocker)} onClick={save}>
      {saving ? 'Saving…' : 'Save details'}
    </button>{' '}
    <button className="button small" type="button" disabled={saving} onClick={onCancel}>Cancel</button>
  </div>
}

function EditField({ item, value, onChange }: {
  item: Field
  value: string
  onChange: (field: EditableField, value: string) => void
}) {
  const id = `event-edit-${item.field}`
  const required = item.required === true
  return <div className="field">
    <label htmlFor={id}>{item.label}{required ? ' *' : ''}</label>
    {item.type === 'textarea'
      ? <textarea id={id} value={value} required={required} onChange={(change) => onChange(item.field, change.target.value)} />
      : <input
          id={id}
          type={item.type === 'datetime' ? 'datetime-local' : item.type === 'number' ? 'number' : 'text'}
          {...(item.type === 'number' ? { min: 1 } : {})}
          value={value}
          required={required}
          onChange={(change) => onChange(item.field, change.target.value)}
        />}
  </div>
}
