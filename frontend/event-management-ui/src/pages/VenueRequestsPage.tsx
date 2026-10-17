import { useEffect, useState } from 'react'
import type { Role, User } from '../types'
import { RoleWarning, StatusBadge } from '../components/FormControls'
import { InlineLoading } from '../components/Loading'
import { RefreshIcon } from '../components/Icon'
import { formatSchedule } from '../features/event/dateFormat'
import { fetchVenueRequests, reviewVenueRequest } from '../features/venue/venueBookings'
import type { VenueRequestEvent } from '../features/venue/venueBookings'

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
            ? ['Pending', 'Pending Review'].includes(booking.status) : booking.status === filter)),
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
            {['All', 'Pending', 'Approved', 'Rejected'].map((status) => <option key={status} value={status}>{status === 'All' ? 'All requests' : status}</option>)}
          </select>
        </label>
        <button className="button small" onClick={() => { setLoading(true); setRefresh((value) => value + 1) }}><RefreshIcon size={14} /> Refresh requests</button>
      </div>
      {error && <p className="field-error" role="alert">{error}</p>}
    </section>
    {loading ? <InlineLoading label="Loading venue requests..." /> : events.length === 0 ? <p>No venue requests found.</p> : events.map((event) => {
      const safety = event.eventStatus === 'Safety Changes Requested'
      const canReview = ['Under Review', 'Approved', 'Safety Changes Requested'].includes(event.eventStatus)
      return <article className="panel event-card" key={event.eventId}>
        <header className="event-card-header">
          <div className="event-card-title"><h2>{event.eventName}</h2><StatusBadge status={event.eventStatus} /></div>
          <span className="equipment-request-coordinator">Coordinator: {resolveUserName?.(event.coordinatorId) ?? 'Unknown'}</span>
        </header>
        <div className="table-scroll" role="region" aria-label={`${event.eventName} venue requests`} tabIndex={0}>
          <table className={`equipment-request-table venue-request-table${safety ? ' with-safety-feedback' : ''}`}>
            <colgroup>{[220, 220, 100, 220, 180, ...(safety ? [240] : [])].map((width, index) => <col key={index} style={{ width }} />)}</colgroup>
            <thead><tr><th>Venue</th><th>Schedule</th><th>Capacity</th><th>Requirements</th><th>Action</th>{safety && <th>Safety change reason</th>}</tr></thead>
            <tbody>{event.bookings.map((booking) => <tr key={booking.id}>
              <td><div className="equipment-request-item"><span>{booking.venueName}</span><StatusBadge status={booking.status} /></div></td>
              <td>{formatSchedule(booking.requestedStartTime, booking.requestedEndTime)}</td>
              <td>{booking.requiredCapacity}</td><td>{booking.venueRequirements || 'None'}</td>
              <td>{canReview && ['Pending', 'Pending Review'].includes(booking.status) ? <div className="table-actions">
                <button className="button small approve" disabled={reviewing !== null} onClick={() => { void review(booking.id, 'Approved') }}>Approve</button>
                <button className="button small reject" disabled={reviewing !== null} onClick={() => { void review(booking.id, 'Rejected') }}>Reject</button>
              </div> : <span className="muted">Reviewed</span>}</td>
              {safety && <td>{booking.safetyFeedback ? <div className="equipment-safety-feedback">
                {booking.safetyFeedback.requestedChanges.map((change, index) => <p key={index}>{change}</p>)}
                {booking.safetyFeedback.reason && <p className="muted">Reason: {booking.safetyFeedback.reason}</p>}
              </div> : <span className="muted">Not flagged</span>}</td>}
            </tr>)}</tbody>
          </table>
        </div>
      </article>
    })}
  </div>
}