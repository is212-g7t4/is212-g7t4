import { useEffect, useState } from 'react'
import type { Role } from '../types'
import { fetchVenues } from '../features/venue/venues'
import type { Venue } from '../features/venue/venues'
import { VENUE_ACCESS_NOTICE, canManageVenues, canViewVenues } from '../features/venue/permissions'
import { ArrowRightIcon, PlusIcon } from '../components/Icon'
import { RoleWarning } from '../components/FormControls'
import { VenueCardGridSkeleton } from '../components/Loading'

const MAX_CHIPS = 3

function statusClass(status: string): string {
  return status.toLowerCase().replace(/\s+/g, '-')
}

export function VenueCataloguePage({ role, onViewVenue, onAddVenue }: { role: Role; onViewVenue: (venueId: string) => void; onAddVenue: () => void }) {
  const [venues, setVenues] = useState<Venue[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  useEffect(() => {
    if (!canViewVenues(role)) return
    let active = true
    const load = () => {
      fetchVenues().then((items) => {
        if (active) {
          setVenues(items)
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
  }, [role])

  if (!canViewVenues(role)) return <RoleWarning>{VENUE_ACCESS_NOTICE}</RoleWarning>

  return <div className="page-stack">
    <section className="intro">
      <h1>Venue catalogue</h1>
      <p className="muted">Review venue profiles and their current operational status. The catalogue refreshes automatically every 30 seconds.</p>
      {canManageVenues(role) && <button type="button" className="button primary" onClick={onAddVenue}><PlusIcon size={14} /> Add Venue</button>}
    </section>
    {lastUpdated && <p className="muted" role="status">Last updated {lastUpdated.toLocaleTimeString()}</p>}
    {loading ? <VenueCardGridSkeleton /> : error ? <p className="field-error" role="alert">{error}</p> : venues.length === 0 ? <p>No venues are available.</p> : <section className="venue-card-grid">
      {venues.map((venue) => {
        const shown = venue.facilities.slice(0, MAX_CHIPS)
        const extra = venue.facilities.length - shown.length
        return <button key={venue.id} type="button" className="venue-card" onClick={() => onViewVenue(venue.id)} aria-label={`View details for ${venue.name}`}>
          <span className="venue-card-header">
            <strong>{venue.name}</strong>
            <span className={`venue-status ${statusClass(venue.status)}`}>{venue.status}</span>
          </span>
          <span className="venue-card-line">{venue.location || 'Not specified'}</span>
          <span className="venue-card-line">{venue.capacity === null ? 'Capacity not specified' : `${venue.capacity} people`}</span>
          <span className="chip-list">
            {shown.length === 0 ? <span className="muted">No facilities listed</span> : shown.map((facility) => <span key={facility} className="chip">{facility}</span>)}
            {extra > 0 && <span className="chip chip-more">+{extra} more</span>}
          </span>
          <span className="venue-card-link">View details <ArrowRightIcon size={13} /></span>
        </button>
      })}
    </section>}
  </div>
}
