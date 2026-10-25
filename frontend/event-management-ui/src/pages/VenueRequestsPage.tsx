import { useEffect, useState } from 'react'
import type { Role, User } from '../types'
import { RoleWarning, StatusBadge } from '../components/FormControls'
import { InlineLoading } from '../components/Loading'
import { RefreshIcon } from '../components/Icon'
import { formatSchedule } from '../features/event/dateFormat'
import { fetchVenueRequests, reviewVenueRequest } from '../features/venue/venueBookings'
import type { VenueRequestEvent } from '../features/venue/venueBookings'
import { VENUE_REQUEST_REVIEWABLE_STATUSES, isAwaitingVenueReview } from '../features/venue/permissions'

const FILTERS: Record<string, string> = { All: 'All requests', Pending: 'Awaiting review', Approved: 'Approved', Rejected: 'Rejected' }

const submittedAt = (value: string) => {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('en-SG', {
    timeZone: 'Asia/Singapore', day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true,
  })
}

/** SCRUM-28 AC4: what the Action cell says when there is no decision to make. */
const noActionText = (awaiting: boolean, eventStatus: string) => {
  if (!awaiting) return 'Reviewed'
  if (eventStatus === 'Submitted') return 'Opens for review when the event is Under Review'
  return `Not open for review while the event is ${eventStatus}`
}

export function VenueRequestsPage({ role, user, resolveUserName }: {
  role: Role; user: User | null; resolveUserName?: (id: string | null) => string | null
}) {
  const [events, setEvents] = useState<VenueRequestEvent[]>([])
  const [filter, setFilter] = useState('All')
  const [refresh, setRefresh] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reviewing, setReviewing] = useState<string | null>(null)
  const allowed = role === 'Venue Staff' && user !== null

  useEffect(() => {
    if (!allowed || !user) return
    let active = true
    fetchVenueRequests(user, filter === 'All' ? undefined : filter).then((rows) => {
      if (active) { setEvents(rows); setError('') }
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : 'Unable to load venue requests.')
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [allowed, user, filter, refresh])

  const review = async (bookingId: string, status: 'Approved' | 'Rejected') => {
    if (!allowed || !user || reviewing) return
    setReviewing(bookingId)
    setError('')
    try {
      const updated = await reviewVenueRequest(bookingId, status, user)
      setEvents((current) => current.map((event) => ({ ...event,
        bookings: event.bookings.map((booking) => booking.id === bookingId ? { ...booking, ...updated } : booking)
          .filter((booking) => filter === 'All' || (filter === 'Pending'
            ? isAwaitingVenueReview(booking.status) : booking.status === filter)),
      })).filter((event) => event.bookings.length > 0))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to review this venue request.')
    } finally {
      setReviewing(null)
    }
  }

  if (!allowed) return <RoleWarning>Venue requests are visible only to Venue Staff.</RoleWarning>
  return <div className="page-stack">
    <section className="intro">
      <h1>Venue requests</h1>
      <div className="table-actions toolbar">
        <label className="field"><span>Show</span>
          <select aria-label="Filter by status" value={filter} onChange={(change) => { setLoading(true); setFilter(change.target.value) }}>
            {Object.entries(FILTERS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <button className="button small" onClick={() => { setLoading(true); setRefresh((value) => value + 1) }}><RefreshIcon size={14} /> Refresh requests</button>
      </div>
      {error && <p className="field-error" role="alert">{error}</p>}
    </section>
    {loading ? <InlineLoading label="Loading venue requests..." /> : events.length === 0 ? <p>No venue requests found.</p> : events.map((event) => {
      const safety = event.eventStatus === 'Safety Changes Requested'
      const canReview = VENUE_REQUEST_REVIEWABLE_STATUSES.includes(event.eventStatus)
      // Counted here rather than read from awaitingReviewCount so it follows decisions made on this page.
      const awaitingCount = event.bookings.filter((booking) => isAwaitingVenueReview(booking.status)).length
      return <article className="panel event-card" key={event.eventId}>
        <header className="event-card-header">
          <div>
            <div className="event-card-title"><h2>{event.eventName}</h2><StatusBadge status={event.eventStatus} /></div>
            <p className="venue-request-event-timing">
              Event: {event.eventStart && event.eventEnd ? formatSchedule(event.eventStart, event.eventEnd) : 'Event dates not set'}
              {awaitingCount > 0 && <> · <strong>{awaitingCount} awaiting review</strong></>}
            </p>
          </div>
          <span className="equipment-request-coordinator">Coordinator: {resolveUserName?.(event.coordinatorId) ?? 'Unknown'}</span>
        </header>
        <div className="table-scroll" role="region" aria-label={`${event.eventName} venue requests`} tabIndex={0}>
          <table className={`equipment-request-table venue-request-table${safety ? ' with-safety-feedback' : ''}`}>
            <colgroup>{[220, 220, 100, 220, 180, ...(safety ? [240] : [])].map((width, index) => <col key={index} style={{ width }} />)}</colgroup>
            <thead><tr><th>Venue</th><th>Schedule</th><th>Capacity</th><th>Requirements</th><th>Action</th>{safety && <th>Safety change reason</th>}</tr></thead>
            <tbody>{event.bookings.map((booking) => {
              const awaiting = isAwaitingVenueReview(booking.status)
              return <tr key={booking.id}>
              <td><div className="equipment-request-item"><span>{booking.venueName}</span><StatusBadge status={booking.status} label={awaiting ? 'Awaiting review' : undefined} /></div></td>
              <td>{formatSchedule(booking.requestedStartTime, booking.requestedEndTime)}
                {booking.requestedAt && <div className="muted">Submitted {submittedAt(booking.requestedAt)}</div>}</td>
              <td>{booking.requiredCapacity}</td><td>{booking.venueRequirements || 'None'}</td>
              <td>{canReview && awaiting ? <div className="table-actions">
                <button className="button small approve" disabled={reviewing !== null} onClick={() => { void review(booking.id, 'Approved') }}>Approve</button>
                <button className="button small reject" disabled={reviewing !== null} onClick={() => { void review(booking.id, 'Rejected') }}>Reject</button>
              </div> : <span className="muted">{noActionText(awaiting, event.eventStatus)}</span>}</td>
              {safety && <td>{booking.safetyFeedback ? <div className="equipment-safety-feedback">
                {booking.safetyFeedback.requestedChanges.map((change, index) => <p key={index}>{change}</p>)}
                {booking.safetyFeedback.reason && <p className="muted">Reason: {booking.safetyFeedback.reason}</p>}
              </div> : <span className="muted">Not flagged</span>}</td>}
            </tr>
            })}</tbody>
          </table>
        </div>
      </article>
    })}
  </div>
}