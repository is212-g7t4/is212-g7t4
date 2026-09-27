import { useEffect, useState } from 'react'
import type { Role } from '../types'
import { fetchVenues } from '../features/venue/venues'
import type { Venue } from '../features/venue/venues'
import { eventApi } from '../features/event/submission'
import type { SubmittedEvent } from '../features/event/submission'
import { StatusBadge } from '../components/FormControls'

function displayList(value: Venue['facilities']): string {
  if (Array.isArray(value)) return value.map(String).join(', ')
  return Object.entries(value).map(([key, item]) => `${key}: ${String(item)}`).join(', ')
}

// Matched by the real venue_id FK on Event now that one exists (see
// database/supabase/migrations/20260927100000_add_venue_id_to_event.sql).
function eventsForVenue(events: SubmittedEvent[], venue: Venue): SubmittedEvent[] {
  return events.filter((event) => event.venueId === venue.id)
}

export function VenueCataloguePage({ role, currentUserId }: { role: Role; currentUserId?: string }) {
  const [venues, setVenues] = useState<Venue[]>([])
  const [events, setEvents] = useState<SubmittedEvent[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  useEffect(() => {
    if (role !== 'Venue Staff' || !currentUserId) return
    let active = true
    const load = () => {
      Promise.all([
        fetchVenues(),
        eventApi(`/events?${new URLSearchParams({ coordinatorId: currentUserId, isManager: 'true' })}`),
      ]).then(([venueItems, eventBody]) => {
        if (active) {
          setVenues(venueItems)
          setEvents(eventBody.events)
          setError('')
          setLastUpdated(new Date())
        }
      }).catch((cause: Error) => {
        if (active) setError(cause.message)
      }).finally(() => {
        if (active) setLoading(false)
      })
    }
    load()
    const interval = window.setInterval(load, 30_000)
    return () => {
      active = false
      window.clearInterval(interval)
    }
  }, [role, currentUserId])

  if (role !== 'Venue Staff') return <p className="role-warning">The Venue Catalogue is visible to Venue Staff.</p>

  return <div className="page-stack">
    <section className="intro"><h1>Venue catalogue</h1><p className="muted">Review venue profiles, their current operational status, and the events requesting each venue. The catalogue refreshes automatically every 30 seconds.</p></section>
    {lastUpdated && <p className="muted" role="status">Last updated {lastUpdated.toLocaleTimeString()}</p>}
    {loading ? <p role="status">Loading venues...</p> : error ? <p role="alert">{error}</p> : venues.length === 0 ? <p>No venues are available.</p> : <section className="panel venue-table-panel"><div className="table-scroll"><table className="venue-table"><thead><tr><th>Venue</th><th>Location</th><th>Capacity</th><th>Accessibility</th><th>Facilities</th><th>Layouts</th><th>Status</th><th>Events</th></tr></thead><tbody>
      {venues.map((venue) => <tr key={venue.id}><td><strong>{venue.name}</strong></td><td>{venue.location || 'Not specified'}</td><td>{venue.capacity ?? 'Not specified'}</td><td>{venue.accessibility || 'Not specified'}</td><td>{displayList(venue.facilities) || 'Not specified'}</td><td>{displayList(venue.supportedLayouts) || 'Not specified'}</td><td><span className={`venue-status ${venue.status.toLowerCase().replace(/\s+/g, '-')}`}>{venue.status}</span></td><td>
        {eventsForVenue(events, venue).length === 0 ? <span className="muted">No events</span> : <ul className="venue-events-list">
          {eventsForVenue(events, venue).map((event) => <li key={event.id}>{event.eventName} <StatusBadge status={event.status} /></li>)}
        </ul>}
      </td></tr>)}
    </tbody></table></div></section>}
  </div>
}

