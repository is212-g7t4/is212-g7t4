import { useEffect, useState } from 'react'
import type { Role } from '../types'
import { ArrowRightIcon } from '../components/Icon'
import { RoleWarning } from '../components/FormControls'
import { EventCardSkeletonList } from '../components/Loading'
import { formatSchedule, getDateTile } from '../features/event/dateFormat'
import { canReviewSafetyChecks, SAFETY_CHECKS_ACCESS_NOTICE } from '../features/safety/permissions'
import { fetchSafetyQueue } from '../features/safety/safetyCheck'
import type { SafetyQueueItem } from '../features/safety/safetyCheck'

type Props = { role: Role; safetyOfficerId?: string; onViewDetails: (id: string) => void }

function formatSubmitted(value: string | null): string {
  const parsed = value ? new Date(value) : null
  if (!parsed || Number.isNaN(parsed.getTime())) return 'Submission date unknown'
  return `Submitted ${parsed.toLocaleString('en-SG', {
    timeZone: 'Asia/Singapore', day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true,
  })}`
}

/**
 * SCRUM-162: the Safety Officer's queue of events awaiting an Operational
 * Safety Check (AC1), nearest event date first, each with its venues,
 * attendance and submission date (AC2) and a resubmission label (AC3).
 * Safety Check Service builds and sorts the list; a decided event has left
 * 'Pending Safety Check', so it is simply absent from the next read (AC4).
 */
export function SafetyChecksPage({ role, safetyOfficerId, onViewDetails }: Props) {
  const [events, setEvents] = useState<SafetyQueueItem[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const officerId = safetyOfficerId || import.meta.env.VITE_CURRENT_COORDINATOR_ID || ''
  // The sidebar only offers this page to a Safety Officer, but the route is
  // reachable directly, so the check belongs here too. The service checks
  // the role again on its side.
  const allowed = canReviewSafetyChecks(role)

  useEffect(() => {
    if (!allowed || !officerId) return
    let active = true
    fetchSafetyQueue(officerId).then((queue) => {
      if (active) setEvents(queue)
    }).catch((cause: Error) => {
      if (active) setError(cause.message)
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [allowed, officerId])

  if (!allowed) return <RoleWarning>{SAFETY_CHECKS_ACCESS_NOTICE}</RoleWarning>

  return <div className="page-stack">
    <section className="intro"><h1>Safety checks</h1><p className="muted">Events waiting for an Operational Safety Check decision.</p></section>
    {loading ? <EventCardSkeletonList /> : error ? <p className="field-error" role="alert">{error}</p> :
      events.length === 0 ? <p>No events are waiting for a safety check.</p> :
      events.map((event) => {
        const tile = getDateTile(event.preferredStartDate)
        const venues = event.venues.map((venue) => venue.name).join(', ') || 'No venue booked'
        return (
          <button key={event.eventId} type="button" className="panel event-row-card" onClick={() => onViewDetails(event.eventId)}>
            <span className="event-row-date">
              <span className="event-row-date-month">{tile.month}</span>
              <span className="event-row-date-day">{tile.day}</span>
            </span>

            <span className="event-row-body">
              <span className="event-row-heading">
                <strong>{event.eventName}</strong>
                {event.resubmission && <span className="status-badge under-review">Resubmission</span>}
              </span>
              <span className="event-row-schedule muted">{formatSchedule(event.preferredStartDate, event.preferredEndDate)}</span>
              <span className="event-row-venue muted">{venues} · {event.expectedAttendance || '0'} attendees</span>
              <span className="event-row-venue muted">{formatSubmitted(event.submittedAt)}</span>
            </span>

            <ArrowRightIcon size={16} className="icon" />
          </button>
        )
      })}
  </div>
}
