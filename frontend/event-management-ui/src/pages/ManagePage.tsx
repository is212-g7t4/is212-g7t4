import { useEffect, useState } from 'react'
import type { EventData } from '../types'
import type { SubmittedEvent } from '../features/event/submission'
import { eventApi, SubmissionError } from '../features/event/submission'
import { Field } from '../components/FormControls'

export function ManagePage({ event, coordinatorId, onClose, onSaved }: {
  event: SubmittedEvent
  coordinatorId: string
  onClose: () => void
  onSaved: (event: SubmittedEvent) => void
}) {
  const [draft, setDraft] = useState<EventData>(event)
  const [original] = useState<EventData>(event)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    const closeOnEscape = (keyboardEvent: KeyboardEvent) => {
      if (keyboardEvent.key === 'Escape' && !saving) onClose()
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [onClose, saving])

  const update = (field: keyof EventData, value: string) => setDraft((current) => ({ ...current, [field]: value }))
  const save = async () => {
    setSaving(true)
    setError('')
    const changes = Object.fromEntries(Object.entries(draft).filter(([field, value]) => value !== original[field as keyof EventData]))
    try {
      const saved = await eventApi(`/events/${event.id}/update`, { ...changes, coordinatorId }, 'PATCH')
      onSaved(saved)
    } catch (cause) {
      const message = cause instanceof SubmissionError && cause.errors.length
        ? `${cause.message} ${cause.errors.join(' ')}`
        : cause instanceof Error ? cause.message : 'Unable to save event details.'
      setError(message)
    } finally {
      setSaving(false)
    }
  }

  return <div className="modal-backdrop" role="presentation" onMouseDown={(mouseEvent) => {
    if (mouseEvent.target === mouseEvent.currentTarget && !saving) onClose()
  }}>
    <section className="modal-panel" role="dialog" aria-modal="true" aria-labelledby="edit-event-title">
      <header className="modal-header"><div><p className="eyebrow">EDIT EVENT</p><h2 id="edit-event-title">{event.eventName}</h2></div><div className="modal-header-actions"><span className="info-tooltip"><button className="info-button" type="button" aria-label="Show impact check information">i</button><span className="info-tooltip-text" role="tooltip"><strong>Low-impact changes</strong><p>These updates usually do not affect arrangements already made for the event and can be saved directly.</p><ul><li>Event Name</li><li>Description</li><li>Purpose</li><li>Registration Needs</li></ul><strong>High-impact changes</strong><p>These updates may contradict existing arrangements, so the system checks them before applying the change.</p><ul><li>Date/Time</li><li>Expected Attendance</li><li>Venue Requirements</li><li>Equipment Requirements</li><li>Accessibility Needs</li></ul></span></span><button className="button secondary" disabled={saving} onClick={onClose} aria-label="Close edit event dialog">Close</button></div></header>
      {error && <p className="role-warning" role="alert">{error}</p>}
      <div className="modal-content">
        <Field label="Event title" value={draft.eventName} onChange={(value) => update('eventName', value)} />
        <Field label="Description" value={draft.description} onChange={(value) => update('description', value)} textarea />
        <Field label="Purpose" value={draft.purpose} onChange={(value) => update('purpose', value)} textarea />
        <Field label="Start date and time" value={draft.preferredStartDate} onChange={(value) => update('preferredStartDate', value)} type="datetime-local" />
        <Field label="End date and time" value={draft.preferredEndDate} onChange={(value) => update('preferredEndDate', value)} type="datetime-local" />
        <Field label="Expected attendance" value={draft.expectedAttendance} onChange={(value) => update('expectedAttendance', value)} type="number" min="1" />
        <Field label="Venue requirements" value={draft.venueRequirements} onChange={(value) => update('venueRequirements', value)} textarea />
        <Field label="Equipment requirements" value={draft.equipmentRequirements} onChange={(value) => update('equipmentRequirements', value)} textarea />
        <Field label="Accessibility needs" value={draft.accessibilityNeeds} onChange={(value) => update('accessibilityNeeds', value)} textarea />
        <Field label="Registration needs" value={draft.registrationNeeds} onChange={(value) => update('registrationNeeds', value)} textarea />
      </div>
      <footer className="modal-actions"><button className="button secondary" disabled={saving} onClick={onClose}>Cancel</button><button className="button primary" disabled={saving} onClick={save}>{saving ? 'Checking arrangements…' : 'Save changes'}</button></footer>
    </section>
  </div>
}
