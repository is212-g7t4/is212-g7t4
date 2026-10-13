import { useEffect, useState } from 'react'
import { eventApi } from '../features/event/submission'
import type { SubmittedEvent } from '../features/event/submission'
import { ArrowRightIcon } from '../components/Icon'
import { EventCardSkeletonList } from '../components/Loading'
import { formatSchedule, getDateTile } from '../features/event/dateFormat'

type Props = { safetyOfficerId?: string; onViewDetails: (id: string) => void }

/**
 * SCRUM-150: the minimal list of events awaiting a safety check.
 *
 * Deliberately small: name, date/time and attendance with an Open button.
 * SCRUM-162 (Claire) owns the full queue — venues, submission date, nearest
 * first, resubmission label — and replaces or extends this page.
 */
export function SafetyChecksPage({ safetyOfficerId, onViewDetails }: Props) {
  const [events, setEvents] = useState<SubmittedEvent[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const officerId = safetyOfficerId || import.meta.env.VITE_CURRENT_COORDINATOR_ID || ''

  useEffect(() => {
    if (!officerId) return
    let active = true
    const params = new URLSearchParams({
      coordinatorId: officerId,
      viewerRole: 'Safety Officer',
      status: 'Pending Safety Check',
    })
    eventApi(`/events?${params.toString()}`).then((body) => {
      if (active) setEvents(body.events)
    }).catch((cause: Error) => {
      if (active) setError(cause.message)
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [officerId])

  return <div className="page-stack">
    <section className="intro"><h1>Safety checks</h1><p className="muted">Events waiting for an Operational Safety Check decision.</p></section>
    {loading ? <EventCardSkeletonList /> : error ? <p className="field-error" role="alert">{error}</p> :
      events.length === 0 ? <p>No events are waiting for a safety check.</p> :
      events.map((event) => {
        const tile = getDateTile(event.preferredStartDate)
        return (
          <button key={event.id} type="button" className="panel event-row-card" onClick={() => onViewDetails(event.id)}>
            <span className="event-row-date">
              <span className="event-row-date-month">{tile.month}</span>
              <span className="event-row-date-day">{tile.day}</span>
            </span>

            <span className="event-row-body">
              <span className="event-row-heading"><strong>{event.eventName}</strong></span>
              <span className="event-row-schedule muted">{formatSchedule(event.preferredStartDate, event.preferredEndDate)}</span>
              <span className="event-row-venue muted">{event.expectedAttendance || '0'} attendees</span>
            </span>

            <ArrowRightIcon size={16} className="icon" />
          </button>
        )
      })}
  </div>
}
