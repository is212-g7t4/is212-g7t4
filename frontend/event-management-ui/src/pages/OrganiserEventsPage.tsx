import { useEffect, useState } from 'react'
import { eventApi } from '../features/event/submission'
import type { SubmittedEvent } from '../features/event/submission'
import { fetchRegistrationCounts } from '../features/registration/registrations'
import type { RegistrationCount } from '../features/registration/registrations'
import { StatusBadge } from '../components/FormControls'
import { ArrowRightIcon } from '../components/Icon'
import { EventCardSkeletonList } from '../components/Loading'
import { formatSchedule, getDateTile } from '../features/event/dateFormat'

export function OrganiserEventsPage({ organiserId, organiserName, onViewDetails }: { organiserId?: string; organiserName?: string; onViewDetails: (id: string) => void }) {
  const [events, setEvents] = useState<SubmittedEvent[]>([])
  const [counts, setCounts] = useState<Record<string, RegistrationCount>>({})
  const [countsError, setCountsError] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!organiserId) return
    let active = true
    eventApi(`/events?organiserId=${organiserId}`).then(async (body) => {
      const fetched = body.events as SubmittedEvent[]
      const approvedIds = fetched.filter((event) => event.status === 'Approved').map((event) => event.id)
      // Counts are secondary: if they fail, still show the events.
      const fetchedCounts = await fetchRegistrationCounts(approvedIds).catch(() => {
        if (active) setCountsError(true)
        return {}
      })
      if (active) {
        setEvents(fetched)
        setCounts(fetchedCounts)
      }
    }).catch((cause: Error) => {
      if (active) setError(cause.message)
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [organiserId])

  return <div className="page-stack">
    <section className="intro"><h1>My events</h1><p className="muted">Events created by {organiserName || 'you'}. Open an event to see its details; registrations are shown for approved events.</p></section>
    {loading ? <EventCardSkeletonList /> : error ? <p className="field-error" role="alert">{error}</p> :
      events.length === 0 ? <p>You have not created any events yet.</p> : <>
      {countsError && <p className="field-error" role="alert">Unable to load registration counts.</p>}
      {events.map((event) => {
        const tile = getDateTile(event.preferredStartDate)
        const approved = event.status === 'Approved'
        const content = <>
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
            <span className="event-row-venue muted">
              {approved
                ? counts[event.id] ? `${counts[event.id].total} registration${counts[event.id].total === 1 ? '' : 's'}` : 'Registrations unavailable'
                : event.status === 'Rejected'
                  ? 'The event has been rejected. Submit a new request.'
                  : 'Registrations are available once the event is approved'}
            </span>
          </span>
          <ArrowRightIcon size={16} className="icon" />
        </>
        return <button key={event.id} type="button" className="panel event-row-card" onClick={() => onViewDetails(event.id)}>{content}</button>
      })}
    </>}
  </div>
}
