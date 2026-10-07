import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import type { Role } from '../types'
import { eventApi } from '../features/event/submission'
import type { SubmittedEvent } from '../features/event/submission'
import { canViewAllInternalEvents, canViewInternalEvents, INTERNAL_EVENT_ACCESS_MESSAGE } from '../features/event/permissions'
import { fetchVenues } from '../features/venue/venues'
import type { Venue } from '../features/venue/venues'
import { Field, RoleWarning, StatusBadge } from '../components/FormControls'
import { ArrowRightIcon, SearchIcon } from '../components/Icon'
import { EventCardSkeletonList } from '../components/Loading'
import { formatSchedule, getDateTile } from '../features/event/dateFormat'
import { OrganiserEventsPage } from './OrganiserEventsPage'

const STATUS_OPTIONS = [
  '', 'Submitted', 'Under Review', 'Approved', 'Rejected',
  'Pending Safety Check', 'Confirmed', 'Safety Changes Requested', 'Cancelled',
]

type MyEventsProps = { role: Role; isManager: boolean; currentCoordinatorId?: string; currentCoordinatorName?: string; onViewDetails: (id: string) => void }

// `currentCoordinatorId` / `currentCoordinatorName` carry the active user, whatever their role.
export function MyEventsPage(props: MyEventsProps) {
  if (props.role === 'Event Organiser') {
    return <OrganiserEventsPage organiserId={props.currentCoordinatorId} organiserName={props.currentCoordinatorName} onViewDetails={props.onViewDetails} />
  }
  return <InternalMyEvents {...props} />
}

function InternalMyEvents({ role, isManager, currentCoordinatorId, currentCoordinatorName, onViewDetails }: MyEventsProps) {
  const [events, setEvents] = useState<SubmittedEvent[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [venues, setVenues] = useState<Venue[]>([])
  const [accessibleVenueIds, setAccessibleVenueIds] = useState<string[]>([])
  const [venuesLoading, setVenuesLoading] = useState(true)
  const [venuesError, setVenuesError] = useState('')
  const [status, setStatus] = useState('')
  const [venueId, setVenueId] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [query, setQuery] = useState({ status: '', venueId: '', dateFrom: '', dateTo: '' })
  const currentCoordinator = {
    id: currentCoordinatorId || import.meta.env.VITE_CURRENT_COORDINATOR_ID || '',
    name: currentCoordinatorName || import.meta.env.VITE_CURRENT_COORDINATOR_NAME || '',
  }

  useEffect(() => {
    if (!canViewInternalEvents(role) || !currentCoordinator.id) return
    let active = true
    const params = new URLSearchParams({ coordinatorId: currentCoordinator.id })
    if (canViewAllInternalEvents(role, isManager)) params.set('isManager', 'true')
    if (role === 'Venue Staff' || role === 'Technical Support') params.set('viewerRole', role)
    if (query.status) params.set('status', query.status)
    if (query.venueId) params.set('venueId', query.venueId)
    if (query.dateFrom) params.set('dateFrom', query.dateFrom)
    if (query.dateTo) params.set('dateTo', query.dateTo)
    eventApi(`/events?${params.toString()}`).then((body) => {
      if (active) {
        setEvents(body.events)
        if (!query.status && !query.venueId && !query.dateFrom && !query.dateTo) {
          setAccessibleVenueIds(Array.from(new Set(
            (body.events as SubmittedEvent[]).map((event) => event.venueId).filter(Boolean),
          )))
        }
      }
    }).catch((cause: Error) => {
      if (active) setError(cause.message)
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [role, isManager, query, currentCoordinator.id])

  useEffect(() => {
    if (!canViewInternalEvents(role)) return
    let active = true
    fetchVenues().then((items) => {
      if (active) setVenues(items)
    }).catch((cause: Error) => {
      if (active) setVenuesError(cause.message)
    }).finally(() => {
      if (active) setVenuesLoading(false)
    })
    return () => { active = false }
  }, [role])

  const applyFilters = (formEvent: FormEvent) => {
    formEvent.preventDefault()
    setLoading(true)
    setError('')
    setQuery({ status, venueId, dateFrom, dateTo })
  }

  if (!canViewInternalEvents(role)) return <RoleWarning>{INTERNAL_EVENT_ACCESS_MESSAGE}</RoleWarning>

  const scopeMessage = canViewAllInternalEvents(role, isManager)
    ? 'Showing all events in the planning process.'
    : 'Showing events assigned to you.'
  const accessibleVenues = venues.filter((venue) => accessibleVenueIds.includes(venue.id))

  return <div className="page-stack">
    <section className="intro"><h1>My events</h1><p className="muted">Signed in for this prototype as {currentCoordinator.name}. {scopeMessage}</p></section>
    <form className="panel" onSubmit={applyFilters}>
      <div className="field-row">
        <label className="field"><span>Status</span>
          <select value={status} onChange={(change) => setStatus(change.target.value)}>
            {STATUS_OPTIONS.map((option) => <option key={option} value={option}>{option || 'All statuses'}</option>)}
          </select>
        </label>
        <label className="field"><span>Venue</span>
          <select value={venueId} onChange={(change) => setVenueId(change.target.value)} disabled={venuesLoading || Boolean(venuesError)}>
            <option value="">{venuesLoading ? 'Loading venues…' : venuesError ? 'Venues unavailable' : 'All venues'}</option>
            {!venuesLoading && !venuesError && accessibleVenues.length === 0
              ? <option value="" disabled>No venues in your events</option>
              : accessibleVenues.map((venue) => <option key={venue.id} value={venue.id}>{venue.name}</option>)}
          </select>
          {venuesError && <span className="field-error" role="alert">{venuesError}</span>}
        </label>
        <Field label="From" value={dateFrom} onChange={setDateFrom} type="date" />
        <Field label="To" value={dateTo} onChange={setDateTo} type="date" />
      </div>
      <button className="button primary" type="submit"><SearchIcon size={14} /> Apply filters</button>
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
