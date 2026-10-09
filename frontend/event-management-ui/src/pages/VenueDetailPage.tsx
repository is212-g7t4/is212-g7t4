import { useEffect, useState } from 'react'
import type { Role, User } from '../types'
import { fetchVenue } from '../features/venue/venues'
import type { Venue } from '../features/venue/venues'
import { fetchActiveVenueHolds, placeVenueHold, showVenueHoldStatus } from '../features/venue/venueHolds'
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

export function VenueDetailPage({ venueId, role, user, onBack, onEdit }: { venueId: string; role: Role; user?: Pick<User, 'id' | 'role'>; onBack: () => void; onEdit: () => void }) {
  const [venue, setVenue] = useState<Venue | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)
  const [holdFormOpen, setHoldFormOpen] = useState(false)
  const [holdExpiry, setHoldExpiry] = useState('')
  const [holdError, setHoldError] = useState('')
  const [holdSaving, setHoldSaving] = useState(false)

  useEffect(() => {
    if (!canViewVenues(role)) return
    let active = true
    Promise.all([fetchVenue(venueId), fetchActiveVenueHolds()]).then(([fetched, holds]) => {
      if (active) {
        setVenue(showVenueHoldStatus([fetched], holds)[0])
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
    const interval = window.setInterval(() => setRefresh((value) => value + 1), 30_000)
    return () => { active = false; window.clearInterval(interval) }
  }, [venueId, role, refresh])

  async function submitHold(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!user) {
      setHoldError('Unable to identify the selected Venue Staff user.')
      return
    }
    setHoldSaving(true)
    setHoldError('')
    try {
      await placeVenueHold(venueId, holdExpiry, user)
      setVenue((current) => current ? { ...current, status: 'On Hold' } : current)
      setHoldFormOpen(false)
      setHoldExpiry('')
    } catch (cause) {
      setHoldError(cause instanceof Error ? cause.message : 'Unable to place a hold on this venue.')
    } finally {
      setHoldSaving(false)
    }
  }

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
        <div className="venue-detail-action-buttons">
          <button className="button hold" disabled={venue.status !== 'Available'} onClick={() => { setHoldFormOpen((open) => !open); setHoldError('') }}>Hold</button>
          <button className="button primary" onClick={onEdit}><EditIcon size={14} /> Edit Venue</button>
        </div>
      </footer>}
      {role === 'Venue Staff' && holdFormOpen && <form className="venue-hold-form" onSubmit={submitHold}>
        <label htmlFor="venue-hold-expiry">Hold expiry date and time</label>
        <input id="venue-hold-expiry" type="datetime-local" required value={holdExpiry} onChange={(event) => setHoldExpiry(event.target.value)} />
        <div className="venue-detail-action-buttons">
          <button className="button" type="button" onClick={() => setHoldFormOpen(false)}>Cancel</button>
          <button className="button hold" type="submit" disabled={holdSaving}>{holdSaving ? 'Placing hold…' : 'Confirm hold'}</button>
        </div>
        {holdError && <p className="field-error" role="alert">{holdError}</p>}
      </form>}
    </article>}
  </div>
}
