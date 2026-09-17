import { useEffect, useState } from 'react'
import type { Role } from '../types'
import { eventApi } from '../features/event/submission'
import type { SubmittedEvent } from '../features/event/submission'
import { StatusBadge } from '../components/FormControls'
import { users } from '../mockData'

export function EventDetailPage({ eventId, role, backLabel, onBack }: { eventId: string; role: Role; backLabel: string; onBack: () => void }) {
  const [event, setEvent] = useState<SubmittedEvent | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)
  const currentCoordinator = {
    ...users[0],
    id: import.meta.env.VITE_CURRENT_COORDINATOR_ID || users[0].id,
    name: import.meta.env.VITE_CURRENT_COORDINATOR_NAME || users[0].name,
  }
  useEffect(() => {
    if (role !== 'Event Coordinator') return
    let active = true
    eventApi(`/events/${eventId}?coordinatorId=${currentCoordinator.id}`).then((body) => {
      if (active) setEvent(body)
    }).catch((cause: Error) => {
      if (active) setError(cause.message)
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [eventId, role, refresh, currentCoordinator.id])

  if (role !== 'Event Coordinator') return <p className="role-warning">Event details are visible to Event Coordinators.</p>

  return <div className="page-stack">
    <section className="intro">
      <button className="button small" onClick={onBack}>← Back to {backLabel}</button>{' '}
      <button className="button small" onClick={() => { setLoading(true); setError(''); setRefresh((value) => value + 1) }}>Refresh</button>
    </section>
    {loading ? <p role="status">Loading event details…</p> : error ? <p role="alert">{error}</p> : event && <article className="panel">
      <h2>{event.eventName}</h2><StatusBadge status={event.status} />
      <p>Submitted: {event.submittedAt ? new Date(event.submittedAt).toLocaleString('en-SG', { timeZone: 'Asia/Singapore' }) + ' SGT' : 'Not recorded'}</p>
      {event.approvedAt && <p>Approved: {new Date(event.approvedAt).toLocaleString('en-SG', { timeZone: 'Asia/Singapore' })} SGT</p>}
      <dl>{[
        ['Description', event.description], ['Purpose', event.purpose],
        ['Preferred start', event.preferredStartDate.replace('T', ' ')],
        ['Preferred end', event.preferredEndDate.replace('T', ' ')],
        ['Expected attendance', event.expectedAttendance],
        ['Venue requirements', event.venueRequirements], ['Accessibility needs', event.accessibilityNeeds],
        ['Equipment requirements', event.equipmentRequirements], ['Registration needs', event.registrationNeeds],
        ['Assigned coordinator', event.coordinatorId || 'Not assigned'],
      ].map(([label, value]) => <div key={label}><dt><strong>{label}</strong></dt><dd style={{ whiteSpace: 'pre-wrap' }}>{value || 'Not specified'}</dd></div>)}</dl>
      <p className="muted">Venue and equipment are shown as requested — confirmed assignment isn't tracked yet.</p>
    </article>}
  </div>
}
