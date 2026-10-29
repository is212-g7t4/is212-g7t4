import { useEffect, useState } from 'react'
import './venueDetail.css'
import { VenueClosuresPanel } from '../features/venue/VenueClosuresPanel'
import type { Role, User } from '../types'
import { fetchVenue } from '../features/venue/venues'
import type { Venue } from '../features/venue/venues'
import { fetchActiveVenueHolds, placeVenueHold, showVenueHoldStatus } from '../features/venue/venueHolds'
import type { VenueHold } from '../features/venue/venueHolds'
import { VENUE_ACCESS_NOTICE, canViewVenues } from '../features/venue/permissions'
import { fetchLegacyConflicts } from '../features/venue/legacyConflicts'
import type { LegacyConflict } from '../features/venue/legacyConflicts'
import { ArrowLeftIcon, EditIcon, RefreshIcon } from '../components/Icon'
import { RoleWarning } from '../components/FormControls'
import { DetailPanelSkeleton } from '../components/Loading'

function statusClass(status: string): string {
  return status.toLowerCase().replace(/\s+/g, '-')
}

// Service returns Singapore-local naive timestamps, so display them without timezone conversion.
function formatExpiry(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('en-SG', { dateStyle: 'medium', timeStyle: 'short' })
}

function formatLocal(value: string): string {
  return value.slice(0, 16).replace('T', ' ')
}

function conflictMemberLabel(booking: LegacyConflict['firstBooking']): string {
  if (!booking.eventId) return 'Venue hold'
  return booking.eventName || `Event ${booking.eventId}`
}

function formatDuration(totalMinutes: number): string {
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return [
    hours ? `${hours} hour${hours === 1 ? '' : 's'}` : '',
    minutes ? `${minutes} minute${minutes === 1 ? '' : 's'}` : '',
  ].filter(Boolean).join(' ')
}

function overlapSummary(conflict: LegacyConflict): string {
  const first = conflict.firstBooking
  const second = conflict.secondBooking
  const start = Date.parse(first.effectiveStartTime) >= Date.parse(second.effectiveStartTime)
    ? first.effectiveStartTime : second.effectiveStartTime
  const end = Date.parse(first.effectiveEndTime) <= Date.parse(second.effectiveEndTime)
    ? first.effectiveEndTime : second.effectiveEndTime
  const minutes = Math.round((Date.parse(end) - Date.parse(start)) / 60_000)
  return Number.isFinite(minutes) && minutes > 0
    ? `Venue occupancy overlaps by ${formatDuration(minutes)}, from ${formatLocal(start)} to ${formatLocal(end)} SGT.`
    : 'The venue occupancy periods overlap.'
}

function ConflictSchedule({ booking }: { booking: LegacyConflict['firstBooking'] }) {
  return <section className="legacy-conflict-event">
    <h4 title={booking.eventId ? `Event ID: ${booking.eventId}` : `Hold ID: ${booking.id}`}>
      {conflictMemberLabel(booking)}
    </h4>
    <dl>
      <div><dt>Event time</dt><dd>{formatLocal(booking.requestedStartTime)}–{formatLocal(booking.requestedEndTime)} SGT</dd></div>
      <div><dt>Venue occupied</dt><dd>{formatLocal(booking.effectiveStartTime)}–{formatLocal(booking.effectiveEndTime)} SGT</dd></div>
    </dl>
  </section>
}

// SCRUM-167: the service sends an offset timestamp, so this shows it in local time.
function formatUpdatedAt(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('en-SG', { dateStyle: 'medium', timeStyle: 'short' })
}

function SafetyInformation({ venue, users }: { venue: Venue; users: Pick<User, 'id' | 'username'>[] }) {
  const editor = users.find((candidate) => candidate.id === venue.safetyInfoUpdatedBy)
  return <section className="venue-safety-info" aria-labelledby="venue-safety-info-title">
    <h3 id="venue-safety-info-title">Safety information</h3>
    <dl>
      <div className="event-detail"><dt>Emergency access details</dt><dd>{venue.emergencyAccessDetails?.trim() || 'Not provided'}</dd></div>
      <div className="event-detail"><dt>Known restrictions</dt><dd>{venue.knownRestrictions?.trim() || 'Not provided'}</dd></div>
    </dl>
    {venue.safetyInfoUpdatedAt && <p className="muted">
      Last updated {formatUpdatedAt(venue.safetyInfoUpdatedAt)} by {editor?.username || 'a Venue Staff member'}
    </p>}
  </section>
}

function Chips({ values }: { values: string[] }) {
  if (values.length === 0) return <>Not specified</>
  return <span className="chip-list">{values.map((value) => <span key={value} className="chip">{value}</span>)}</span>
}

type VenueDetailPageProps = { venueId: string; role: Role; user?: Pick<User, 'id' | 'role'>; coordinators?: Pick<User, 'id' | 'username'>[]; users?: Pick<User, 'id' | 'username'>[]; onBack: () => void; onEdit: () => void }

export function VenueDetailPage(props: VenueDetailPageProps) {
  // Route changes reset cached detail and drafts; refreshes keep the same mounted panel.
  return <VenueDetailContent key={props.venueId} {...props} />
}

function VenueDetailContent({ venueId, role, user, coordinators = [], users = [], onBack, onEdit }: VenueDetailPageProps) {
  const [venue, setVenue] = useState<Venue | null>(null)
  const [hold, setHold] = useState<VenueHold | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)
  const [holdFormOpen, setHoldFormOpen] = useState(false)
  const [holdExpiry, setHoldExpiry] = useState('')
  const [holdCoordinator, setHoldCoordinator] = useState('')
  const [holdError, setHoldError] = useState('')
  const [holdSaving, setHoldSaving] = useState(false)
  const [legacyConflicts, setLegacyConflicts] = useState<LegacyConflict[]>([])
  const [conflictError, setConflictError] = useState('')

  useEffect(() => {
    if (!canViewVenues(role)) return
    let active = true
    Promise.all([fetchVenue(venueId), fetchActiveVenueHolds()]).then(([fetched, holds]) => {
      if (active) {
        setVenue(showVenueHoldStatus([fetched], holds)[0])
        setHold(holds.find((item) => item.venueId === venueId) ?? null)
        setError('')
      }
    }).catch((cause: Error) => {
      if (active) {
        setError(cause.message)
      }
    }).finally(() => {
      if (active) setLoading(false)
    })
    if (role === 'Venue Staff') {
      fetchLegacyConflicts(venueId).then((result) => {
        if (active) {
          setLegacyConflicts(result.conflicts)
          setConflictError('')
        }
      }).catch((cause: Error) => {
        if (active) setConflictError(cause.message)
      })
    }
    const interval = window.setInterval(() => setRefresh((value) => value + 1), 30_000)
    return () => { active = false; window.clearInterval(interval) }
  }, [venueId, role, user, refresh])

  async function submitHold(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!user) {
      setHoldError('Unable to identify the selected Venue Staff user.')
      return
    }
    setHoldSaving(true)
    setHoldError('')
    try {
      setHold(await placeVenueHold(
        venueId,
        holdExpiry,
        holdCoordinator || undefined,
        venue ?? {},
      ))
      setVenue((current) => current ? { ...current, status: 'On Hold' } : current)
      setHoldFormOpen(false)
      setHoldExpiry('')
      setHoldCoordinator('')
    } catch (cause) {
      setHoldError(cause instanceof Error ? cause.message : 'Unable to place a hold on this venue.')
    } finally {
      setHoldSaving(false)
    }
  }

  if (!canViewVenues(role)) return <RoleWarning>{VENUE_ACCESS_NOTICE}</RoleWarning>

  return <div className="page-stack venue-detail-page">
    <section className="venue-detail-toolbar" aria-label="Venue navigation">
      <button className="button small" onClick={onBack}><ArrowLeftIcon size={13} /> Back to venue catalogue</button>{' '}
      <button className="button small" onClick={() => { setLoading(true); setError(''); setRefresh((value) => value + 1) }}><RefreshIcon size={13} /> Refresh</button>
    </section>
    {venue && error && <p className="field-error" role="alert">Unable to refresh venue: {error}. Showing the last loaded details.</p>}
    {!venue && loading ? <DetailPanelSkeleton /> : !venue && error ? <p className="field-error" role="alert">{error}</p> : venue && <article className="panel venue-detail-card">
      <header className="venue-detail-header">
        <div><p className="venue-detail-eyebrow">Venue overview</p><h2>{venue.name || 'Not specified'}</h2></div>
        <span className={`venue-status ${statusClass(venue.status)}`}>{venue.status}</span>
      </header>
      <dl className="venue-detail-metadata">
        <div className="event-detail"><dt>Location</dt><dd>{venue.location || 'Not specified'}</dd></div>
        <div className="event-detail"><dt>Capacity</dt><dd>{venue.capacity === null ? 'Not specified' : `${venue.capacity} people`}</dd></div>
        <div className="event-detail"><dt>Accessibility</dt><dd>{venue.accessibility || 'Not specified'}</dd></div>
        <div className="event-detail"><dt>Operating status</dt><dd>{venue.status || 'Not specified'}</dd></div>
        <div className="event-detail"><dt>Setup time</dt><dd>{venue.setupTimeMinutes ?? 0} minutes</dd></div>
        <div className="event-detail"><dt>Turnaround time</dt><dd>{venue.turnaroundTimeMinutes ?? 0} minutes</dd></div>
        <div className="event-detail"><dt>Facilities</dt><dd><Chips values={venue.facilities} /></dd></div>
        <div className="event-detail"><dt>Supported layouts</dt><dd><Chips values={venue.supportedLayouts} /></dd></div>
        {hold && <div className="event-detail"><dt>Hold expires</dt><dd>{formatExpiry(hold.expiresAt)}</dd></div>}
      </dl>
      <SafetyInformation venue={venue} users={users} />
      {role === 'Venue Staff' && <section className="legacy-conflicts" aria-labelledby="legacy-conflicts-title">
        <h3 id="legacy-conflicts-title">Scheduling conflicts</h3>
        {conflictError ? <p className="field-error" role="alert">{conflictError}</p> : legacyConflicts.length === 0 ?
          <p>No existing bookings conflict under this venue&apos;s buffer rules.</p> : <>
            <p role="status">{legacyConflicts.length} buffer conflict{legacyConflicts.length === 1 ? ' requires' : 's require'} manual review. No booking has been cancelled or changed.</p>
            <ul className="legacy-conflict-list">
              {legacyConflicts.map((conflict) => {
                const first = conflict.firstBooking
                const second = conflict.secondBooking
                return <li className="legacy-conflict-item" key={`${first.id}:${second.id}`}>
                  <div className="legacy-conflict-events">
                    <ConflictSchedule booking={first} />
                    <ConflictSchedule booking={second} />
                  </div>
                  <p className="legacy-conflict-overlap"><strong>{overlapSummary(conflict)}</strong></p>
                </li>
              })}
            </ul>
          </>}
      </section>}
      {role === 'Venue Staff' && <footer className="venue-detail-actions">
        <div className="venue-detail-action-buttons">
          <button className="button hold" disabled={venue.status !== 'Available'} onClick={() => { setHoldFormOpen((open) => !open); setHoldError('') }}>Hold</button>
          <button className="button primary" onClick={onEdit}><EditIcon size={14} /> Edit Venue</button>
        </div>
      </footer>}
      {role === 'Venue Staff' && holdFormOpen && <form className="venue-hold-form" onSubmit={submitHold}>
        <label htmlFor="venue-hold-expiry">Hold expiry date and time</label>
        <input id="venue-hold-expiry" type="datetime-local" required value={holdExpiry} onChange={(event) => setHoldExpiry(event.target.value)} />
        {coordinators.length > 0 && <>
          <label htmlFor="venue-hold-coordinator">Event Coordinator to remind (optional)</label>
          <select id="venue-hold-coordinator" value={holdCoordinator} onChange={(event) => setHoldCoordinator(event.target.value)}>
            <option value="">No reminder</option>
            {coordinators.map((coordinator) => <option key={coordinator.id} value={coordinator.id}>{coordinator.username}</option>)}
          </select>
        </>}
        <div className="venue-detail-action-buttons">
          <button className="button" type="button" onClick={() => setHoldFormOpen(false)}>Cancel</button>
          <button className="button hold" type="submit" disabled={holdSaving}>{holdSaving ? 'Placing hold…' : 'Confirm hold'}</button>
        </div>
        {holdError && <p className="field-error" role="alert">{holdError}</p>}
      </form>}
      {role === 'Venue Staff' && user?.role === 'Venue Staff' && venue.id === venueId && <VenueClosuresPanel key={`${venueId}:${user.id}`} venueId={venueId} venueName={venue.name} />}
    </article>}
  </div>
}
