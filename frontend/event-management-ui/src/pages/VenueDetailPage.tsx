import { useEffect, useState } from 'react'
import type { Role } from '../types'
import { fetchVenue } from '../features/venue/venues'
import type { Venue } from '../features/venue/venues'
import { VENUE_ACCESS_NOTICE, canViewVenues } from '../features/venue/permissions'
import { ArrowLeftIcon, EditIcon, RefreshIcon } from '../components/Icon'
import { RoleWarning } from '../components/FormControls'
import { DetailPanelSkeleton } from '../components/Loading'

function statusClass(status: string): string {
  return status.toLowerCase().replace(/\s+/g, '-')
}

function Chips({ values }: { values: string[] }) {
  if (values.length === 0) return <>Not specified</>
  return <span className="chip-list">{values.map((value) => <span key={value} className="chip">{value}</span>)}</span>
}

export function VenueDetailPage({ venueId, role, onBack, onEdit }: { venueId: string; role: Role; onBack: () => void; onEdit: () => void }) {
  const [venue, setVenue] = useState<Venue | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    if (!canViewVenues(role)) return
    let active = true
    fetchVenue(venueId).then((fetched) => {
      if (active) {
        setVenue(fetched)
        setError('')
      }
    }).catch((cause: Error) => {
      if (active) {
        setVenue(null)
        setError(cause.message)
      }
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [venueId, role, refresh])

  if (!canViewVenues(role)) return <RoleWarning>{VENUE_ACCESS_NOTICE}</RoleWarning>

  return <div className="page-stack">
    <section className="intro">
      <button className="button small" onClick={onBack}><ArrowLeftIcon size={13} /> Back to venue catalogue</button>{' '}
      <button className="button small" onClick={() => { setLoading(true); setError(''); setRefresh((value) => value + 1) }}><RefreshIcon size={13} /> Refresh</button>
    </section>
    {loading ? <DetailPanelSkeleton /> : error ? <p className="field-error" role="alert">{error}</p> : venue && <article className="panel event-card">
      <header className="event-card-header">
        <h2>{venue.name || 'Not specified'}</h2>
        <span className={`venue-status ${statusClass(venue.status)}`}>{venue.status}</span>
      </header>
      <dl className="event-details">
        <div className="event-detail"><dt>Location</dt><dd>{venue.location || 'Not specified'}</dd></div>
        <div className="event-detail"><dt>Capacity</dt><dd>{venue.capacity === null ? 'Not specified' : `${venue.capacity} people`}</dd></div>
        <div className="event-detail"><dt>Accessibility</dt><dd>{venue.accessibility || 'Not specified'}</dd></div>
        <div className="event-detail"><dt>Operating status</dt><dd>{venue.status || 'Not specified'}</dd></div>
        <div className="event-detail"><dt>Facilities</dt><dd><Chips values={venue.facilities} /></dd></div>
        <div className="event-detail"><dt>Supported layouts</dt><dd><Chips values={venue.supportedLayouts} /></dd></div>
      </dl>
      {role === 'Venue Staff' && <footer className="venue-detail-actions">
        <button className="button primary" onClick={onEdit}><EditIcon size={14} /> Edit Venue</button>
      </footer>}
    </article>}
  </div>
}
