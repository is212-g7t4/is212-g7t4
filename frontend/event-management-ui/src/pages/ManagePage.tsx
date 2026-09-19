import { useEffect, useState } from 'react'
import type { EventData } from '../types'
import { eventApi, SubmissionError } from '../features/event/submission'
import { Field, Impact, StatusBadge } from '../components/FormControls'

export function ManagePage({ eventId, coordinatorId, onSaved }: { eventId: string; coordinatorId: string; onSaved: (message: string) => void }) {
  const [event, setEvent] = useState<EventData | null>(null)
  const [original, setOriginal] = useState<EventData | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    eventApi(`/events/${eventId}?coordinatorId=${coordinatorId}`).then((body) => {
      setEvent(body)
      setOriginal(body)
    }).catch((cause: Error) => setError(cause.message)).finally(() => setLoading(false))
  }, [eventId, coordinatorId])

  const update = (field: keyof EventData, value: string) => setEvent((current) => current ? { ...current, [field]: value } : current)
  const save = async () => {
    if (!event || !original) return
    setSaving(true)
    setError('')
    const changes = Object.fromEntries(Object.entries(event).filter(([field, value]) => value !== original[field as keyof EventData]))
    try {
      const saved = await eventApi(`/events/${eventId}/update`, { ...changes, coordinatorId }, 'PATCH')
      setEvent(saved)
      setOriginal(saved)
      onSaved('Event details saved.')
    } catch (cause) {
      const message = cause instanceof SubmissionError && cause.errors.length
        ? `${cause.message} ${cause.errors.join(' ')}`
        : cause instanceof Error ? cause.message : 'Unable to save event details.'
      setError(message)
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <p className="page-stack" role="status">Loading event details…</p>
  if (!event) return <p className="page-stack" role="alert">{error || 'Event details are unavailable.'}</p>
  return <div className="page-stack"><div className="two-column"><section className="panel"><div className="section-heading"><div><p className="eyebrow">EDIT EVENT</p><h2>Event information</h2></div><StatusBadge status="Planning" /></div>
    {error && <p className="role-warning" role="alert">{error}</p>}
    <Field label="Event title" value={event.eventName} onChange={(value) => update('eventName', value)} />
    <Field label="Description" value={event.description} onChange={(value) => update('description', value)} textarea />
    <Field label="Purpose" value={event.purpose} onChange={(value) => update('purpose', value)} textarea />
    <Field label="Start date and time" value={event.preferredStartDate} onChange={(value) => update('preferredStartDate', value)} type="datetime-local" />
    <Field label="End date and time" value={event.preferredEndDate} onChange={(value) => update('preferredEndDate', value)} type="datetime-local" />
    <Field label="Expected attendance" value={event.expectedAttendance} onChange={(value) => update('expectedAttendance', value)} type="number" min="1" />
    <Field label="Venue requirements" value={event.venueRequirements} onChange={(value) => update('venueRequirements', value)} textarea />
    <Field label="Equipment requirements" value={event.equipmentRequirements} onChange={(value) => update('equipmentRequirements', value)} textarea />
    <Field label="Accessibility needs" value={event.accessibilityNeeds} onChange={(value) => update('accessibilityNeeds', value)} textarea />
    <Field label="Registration needs" value={event.registrationNeeds} onChange={(value) => update('registrationNeeds', value)} textarea />
    <button className="button primary" disabled={saving} onClick={save}>{saving ? 'Checking arrangements…' : 'Save changes'}</button>
  </section><section className="panel"><div className="section-heading"><div><p className="eyebrow">IMPACT CHECK</p><h2>Planning indicators</h2><p className="muted">Date, attendance, venue, equipment, and accessibility changes are checked against existing arrangements before saving.</p></div></div><Impact label="Low-impact fields" value="Save directly" tone="success" /><Impact label="High-impact fields" value="Conflict check" tone="warning" /></section></div></div>
}
