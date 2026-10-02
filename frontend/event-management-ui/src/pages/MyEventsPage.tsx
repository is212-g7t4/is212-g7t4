import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import type { Role } from '../types'
import { eventApi } from '../features/event/submission'
import type { SubmittedEvent } from '../features/event/submission'
import { Field, RoleWarning, StatusBadge } from '../components/FormControls'
import { ArrowRightIcon } from '../components/Icon'
import { EventCardSkeletonList } from '../components/Loading'
import { formatSchedule, getDateTile } from '../features/event/dateFormat'
import { OrganiserEventsPage } from './OrganiserEventsPage'

const STATUS_OPTIONS = ['', 'Submitted', 'Under Review', 'Approved', 'Confirmed', 'Rejected']

type MyEventsProps = { role: Role; isManager: boolean; currentCoordinatorId?: string; currentCoordinatorName?: string; onViewDetails: (id: string) => void }

// `currentCoordinatorId` / `currentCoordinatorName` carry the active user, whatever their role.
export function MyEventsPage(props: MyEventsProps) {
  if (props.role === 'Event Organiser') {
    return <OrganiserEventsPage organiserId={props.currentCoordinatorId} organiserName={props.currentCoordinatorName} onViewDetails={props.onViewDetails} />
  }
  return <CoordinatorMyEvents {...props} />
}

function CoordinatorMyEvents({ role, isManager, currentCoordinatorId, currentCoordinatorName, onViewDetails }: MyEventsProps) {
  const [events, setEvents] = useState<SubmittedEvent[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState('')
  const [venue, setVenue] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [query, setQuery] = useState({ status: '', venue: '', dateFrom: '', dateTo: '' })
  const currentCoordinator = {
    id: currentCoordinatorId || import.meta.env.VITE_CURRENT_COORDINATOR_ID || '',
    name: currentCoordinatorName || import.meta.env.VITE_CURRENT_COORDINATOR_NAME || '',
  }

  useEffect(() => {
    if (role !== 'Event Coordinator' || !currentCoordinator.id) return
    let active = true
    const params = new URLSearchParams({ coordinatorId: currentCoordinator.id })
    if (isManager) params.set('isManager', 'true')
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
  }, [role, isManager, query, currentCoordinator.id])

  const applyFilters = (formEvent: FormEvent) => {
    formEvent.preventDefault()
    setLoading(true)
    setError('')
    setQuery({ status, venue, dateFrom, dateTo })
  }

  if (role !== 'Event Coordinator') return <RoleWarning>My events is visible to Event Coordinators and Event Organisers.</RoleWarning>

  return <div className="page-stack">
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
    {loading ? <EventCardSkeletonList /> : error ? <p className="field-error" role="alert">{error}</p> :
      events.length === 0 ? <p>No events match these filters.</p> :
      events.map((event) => {
        const tile = getDateTile(event.preferredStartDate)
        return (
          <button key={event.id} type="button" className="panel event-row-card" onClick={() => onViewDetails(event.id)}>
            <span className="event-row-date">
              <span className="event-row-date-month">{tile.month}</span>
              <span className="event-row-date-day">{tile.day}</span>
            </span>

            <span className="event-row-body">
              <span className="event-row-heading">
                <strong>{event.eventName}</strong>
                <StatusBadge status={event.status} />
              </span>
              <span className="event-row-schedule muted">{formatSchedule(event.preferredStartDate, event.preferredEndDate)}</span>
              <span className="event-row-venue muted">{event.venueRequirements || 'No venue requirements specified'}</span>
            </span>

            <ArrowRightIcon size={16} className="icon" />
          </button>
        )
      })}
  </div>
}
