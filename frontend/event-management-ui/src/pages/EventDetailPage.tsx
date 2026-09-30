import { useEffect, useState } from 'react'
import type { Role } from '../types'
import { eventApi } from '../features/event/submission'
import type { SubmittedEvent } from '../features/event/submission'
import { fetchRegistrations } from '../features/registration/registrations'
import type { Registration } from '../features/registration/registrations'
import { StatusBadge } from '../components/FormControls'

export function EventDetailPage({ eventId, role, isManager, currentCoordinatorId, currentCoordinatorName, backLabel, onBack }: { eventId: string; role: Role; isManager: boolean; currentCoordinatorId?: string; currentCoordinatorName?: string; backLabel: string; onBack: () => void }) {
  const [event, setEvent] = useState<SubmittedEvent | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)
  const [registrations, setRegistrations] = useState<Registration[]>([])
  const [registrationsError, setRegistrationsError] = useState('')
  const [registrationsLoading, setRegistrationsLoading] = useState(true)
  const currentCoordinator = {
    id: currentCoordinatorId || import.meta.env.VITE_CURRENT_COORDINATOR_ID || '',
    name: currentCoordinatorName || import.meta.env.VITE_CURRENT_COORDINATOR_NAME || '',
  }
  useEffect(() => {
    if (role !== 'Event Coordinator' || !currentCoordinator.id) return
    let active = true
    const params = new URLSearchParams({ coordinatorId: currentCoordinator.id })
    if (isManager) params.set('isManager', 'true')
    eventApi(`/events/${eventId}?${params.toString()}`).then((body) => {
      if (active) setEvent(body)
    }).catch((cause: Error) => {
      if (active) setError(cause.message)
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [eventId, role, isManager, refresh, currentCoordinator.id])

  useEffect(() => {
    if (role !== 'Event Coordinator' || event?.status !== 'Approved') return
    let active = true
    fetchRegistrations(eventId).then((fetched) => {
      if (active) {
        setRegistrations(fetched)
        setRegistrationsError('')
      }
    }).catch((cause: Error) => {
      if (active) setRegistrationsError(cause.message)
    }).finally(() => { if (active) setRegistrationsLoading(false) })
    return () => { active = false }
  }, [eventId, role, event?.status, refresh])

  if (role !== 'Event Coordinator') return <p className="role-warning">Event details are visible to Event Coordinators.</p>

  return <div className="page-stack">
    <section className="intro">
      <button className="button small" onClick={onBack}>← Back to {backLabel}</button>{' '}
      <button className="button small" onClick={() => { setLoading(true); setError(''); setRefresh((value) => value + 1) }}>Refresh</button>
    </section>
    {loading ? <p role="status">Loading event details…</p> : error ? <p role="alert">{error}</p> : event && <article className="panel">
      <h2>{event.eventName}</h2><StatusBadge status={event.status} />
      <p>Submitted: {event.submittedAt ? new Date(event.submittedAt).toLocaleString('en-SG', { timeZone: 'Asia/Singapore' }) + ' SGT' : 'Not recorded'}</p>
      {event.decision?.decidedAt && <p>Decision: {event.decision.status} on {new Date(event.decision.decidedAt).toLocaleString('en-SG', { timeZone: 'Asia/Singapore' })} SGT</p>}
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

      {event.status === 'Approved' && <>
        <h3>Registrations</h3>
        {registrationsLoading ? <p role="status">Loading registrations…</p> : registrationsError ? <p role="alert">{registrationsError}</p> : <>
          {(() => {
            const confirmedCount = registrations.filter((registration) => registration.status === 'Confirmed').length
            const capacity = Number(event.expectedAttendance)
            const hasCapacity = event.expectedAttendance.trim() !== '' && !Number.isNaN(capacity)
            return <dl className="event-details">
              <div className="event-detail"><dt>Total registrations</dt><dd>{registrations.length}</dd></div>
              <div className="event-detail"><dt>Capacity</dt><dd>{hasCapacity ? capacity : 'Not set'}</dd></div>
              <div className="event-detail"><dt>Remaining spots</dt><dd>{hasCapacity ? capacity - confirmedCount : 'Not set'}</dd></div>
            </dl>
          })()}
          {registrations.length === 0 ? <p>No registrations yet.</p> : <div className="table-scroll">
            <table>
              <thead><tr><th>Name</th><th>Email</th><th>Organisation</th><th>Registered</th><th>Status</th></tr></thead>
              <tbody>{registrations.map((registration) => <tr key={registration.id}>
                <td>{registration.attendeeName}</td>
                <td>{registration.attendeeEmail}</td>
                <td>{registration.attendeeOrganization || '—'}</td>
                <td>{registration.registrationDate ? new Date(registration.registrationDate).toLocaleString('en-SG', { timeZone: 'Asia/Singapore' }) : 'Not recorded'}</td>
                <td>{registration.status}</td>
              </tr>)}</tbody>
            </table>
          </div>}
        </>}
      </>}
    </article>}
  </div>
}
