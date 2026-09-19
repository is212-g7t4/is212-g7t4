import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import type { Role } from '../types'
import { eventApi } from '../features/event/submission'
import type { SubmittedEvent } from '../features/event/submission'
import { Field, StatusBadge } from '../components/FormControls'
import { users } from '../mockData'
import { ManagePage } from './ManagePage'

const STATUS_OPTIONS = ['', 'Submitted', 'Approved', 'Rejected']

export function MyEventsPage({ role, currentCoordinatorId, currentCoordinatorName, onViewDetails }: { role: Role; currentCoordinatorId?: string; currentCoordinatorName?: string; onViewDetails: (id: string) => void }) {
  const [events, setEvents] = useState<SubmittedEvent[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState('')
  const [venue, setVenue] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [query, setQuery] = useState({ status: '', venue: '', dateFrom: '', dateTo: '' })
  const [editingEvent, setEditingEvent] = useState<SubmittedEvent | null>(null)
  const currentCoordinator = {
    ...users[0],
    id: currentCoordinatorId || import.meta.env.VITE_CURRENT_COORDINATOR_ID || users[0].id,
    name: currentCoordinatorName || import.meta.env.VITE_CURRENT_COORDINATOR_NAME || users[0].name,
  }

  useEffect(() => {
    if (role !== 'Event Coordinator') return
    let active = true
    const params = new URLSearchParams({ coordinatorId: currentCoordinator.id })
    if (query.status) params.set('status', query.status)
    if (query.venue) params.set('venue', query.venue)
    if (query.dateFrom) params.set('dateFrom', query.dateFrom)
    if (query.dateTo) params.set('dateTo', query.dateTo)
    eventApi(`/events?${params.toString()}`).then((body) => {
      if (active) setEvents(body.events)
    }).catch((cause: Error) => {
      if (active) setError(cause.message)
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [role, query, currentCoordinator.id])

  const applyFilters = (formEvent: FormEvent) => {
    formEvent.preventDefault()
    setLoading(true)
    setError('')
    setQuery({ status, venue, dateFrom, dateTo })
  }

  if (role !== 'Event Coordinator') return <p className="role-warning">My events is visible to Event Coordinators.</p>

  return <div className="page-stack">
    {editingEvent && <ManagePage event={editingEvent} coordinatorId={currentCoordinator.id} onClose={() => setEditingEvent(null)} onSaved={(saved) => {
      setEvents((current) => current.map((item) => item.id === saved.id ? saved : item))
      setEditingEvent(null)
    }} />}
    <section className="intro"><h1>My events</h1><p className="muted">Signed in for this prototype as {currentCoordinator.name}.</p></section>
    <form className="panel" onSubmit={applyFilters}>
      <div className="field-row">
        <label className="field"><span>Status</span>
          <select value={status} onChange={(change) => setStatus(change.target.value)}>
            {STATUS_OPTIONS.map((option) => <option key={option} value={option}>{option || 'All statuses'}</option>)}
          </select>
        </label>
        <Field label="Venue" value={venue} onChange={setVenue} placeholder="Search venue requirements" />
        <Field label="From" value={dateFrom} onChange={setDateFrom} type="date" />
        <Field label="To" value={dateTo} onChange={setDateTo} type="date" />
      </div>
      <button className="button" type="submit">Apply filters</button>
    </form>
    {loading ? <p role="status">Loading events…</p> : error ? <p role="alert">{error}</p> :
      events.length === 0 ? <p>No events match these filters.</p> :
      events.map((event) => <article key={event.id} className="panel">
        <h2>{event.eventName}</h2><StatusBadge status={event.status} />
        <p>{event.preferredStartDate.replace('T', ' ')} – {event.preferredEndDate.replace('T', ' ')}</p>
        <p className="muted">{event.venueRequirements || 'No venue requirements specified'}</p>
        <div className="table-actions"><button className="button small" onClick={() => onViewDetails(event.id)}>View details →</button><button className="button small secondary" onClick={() => setEditingEvent(event)}>Edit event</button></div>
      </article>)}
  </div>
}
