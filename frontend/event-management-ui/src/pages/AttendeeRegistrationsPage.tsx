import { useEffect, useState } from 'react'
import { RoleWarning, StatusBadge } from '../components/FormControls'
import { ArrowLeftIcon, ArrowRightIcon, RefreshIcon } from '../components/Icon'
import { EventCardSkeletonList } from '../components/Loading'
import { formatSchedule, getDateTile } from '../features/event/dateFormat'
import type { AttendeeRegistration } from '../features/registration/attendeeRegistrations'
import { loadAttendeeRegistrations } from '../features/registration/attendeeRegistrations'
import type { Role } from '../types'

function formatRegistrationDate(value: string | null) {
  if (!value) return 'Not recorded'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString('en-SG', {
    timeZone: 'Asia/Singapore', day: 'numeric', month: 'short', year: 'numeric',
    hour: 'numeric', minute: '2-digit', hour12: true,
  })
}

export function AttendeeRegistrationsPage({ role, attendeeId }: { role: Role; attendeeId?: string }) {
  const [registrations, setRegistrations] = useState<AttendeeRegistration[]>([])
  const [selected, setSelected] = useState<AttendeeRegistration | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    if (role !== 'Attendee' || !attendeeId) return
    let active = true
    loadAttendeeRegistrations(attendeeId).then((items) => {
      if (active) setRegistrations(items)
    }).catch((cause: Error) => {
      if (active) setError(cause.message)
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [role, attendeeId, revision])

  if (role !== 'Attendee') return <RoleWarning>Registration status is visible only to Attendees.</RoleWarning>
  if (!attendeeId) return <p className="field-error" role="alert">Select an attendee to view registrations.</p>
  if (selected) return <RegistrationDetail registration={selected} onBack={() => setSelected(null)} />

  return <div className="page-stack">
    <section className="intro">
      <h1>My registrations</h1>
      <p className="muted">Review your registered events and confirm your current registration status.</p>
      <button className="button small" onClick={() => { setLoading(true); setError(''); setRevision((value) => value + 1) }}>
        <RefreshIcon size={13} /> Refresh registrations
      </button>
    </section>

    {loading ? <EventCardSkeletonList /> : error ? <p className="field-error" role="alert">{error}</p> :
      registrations.length === 0 ? <section className="panel"><p>You have not registered for any events.</p></section> :
      <section className="page-stack" aria-label="My registered events">
        {registrations.map((registration) => {
          const tile = getDateTile(registration.event.preferredStartDate)
          return <button key={registration.id} type="button" className="panel event-row-card" onClick={() => setSelected(registration)}>
            <span className="event-row-date"><span className="event-row-date-month">{tile.month}</span><span className="event-row-date-day">{tile.day}</span></span>
            <span className="event-row-body">
              <span className="event-row-heading"><strong>{registration.event.eventName}</strong><StatusBadge status={registration.status} /></span>
              <span className="event-row-schedule muted">{formatSchedule(registration.event.preferredStartDate, registration.event.preferredEndDate)}</span>
              {registration.venue && <span className="event-row-venue muted">{registration.venue.name} · {registration.venue.location}</span>}
              <span className="muted">Registered: {formatRegistrationDate(registration.registrationDate)}</span>
            </span>
            <ArrowRightIcon size={16} className="icon" />
          </button>
        })}
      </section>}
  </div>
}

function RegistrationDetail({ registration, onBack }: { registration: AttendeeRegistration; onBack: () => void }) {
  return <div className="page-stack">
    <section className="intro"><button className="button small" onClick={onBack}><ArrowLeftIcon size={13} /> Back to registrations</button></section>
    <article className="panel event-card">
      <header className="event-card-header"><h2>{registration.event.eventName}</h2><StatusBadge status={registration.status} /></header>

      <section className="event-card-section">
        <h3>Registration details</h3>
        <dl className="event-details">
          <div className="event-detail"><dt>Status</dt><dd>{registration.status}</dd></div>
          <div className="event-detail"><dt>Registration date</dt><dd>{formatRegistrationDate(registration.registrationDate)}</dd></div>
          <div className="event-detail"><dt>Name</dt><dd>{registration.attendeeName}</dd></div>
          <div className="event-detail"><dt>Email</dt><dd>{registration.attendeeEmail}</dd></div>
          <div className="event-detail full"><dt>Organisation</dt><dd>{registration.attendeeOrganization || '—'}</dd></div>
        </dl>
      </section>

      <section className="event-card-section">
        <h3>Event details</h3>
        <dl className="event-details">
          <div className="event-detail full"><dt>Date and time</dt><dd>{formatSchedule(registration.event.preferredStartDate, registration.event.preferredEndDate)}</dd></div>
          {registration.venue && <>
            <div className="event-detail"><dt>Venue</dt><dd>{registration.venue.name}</dd></div>
            <div className="event-detail"><dt>Location</dt><dd>{registration.venue.location}</dd></div>
          </>}
          <div className="event-detail full"><dt>Description</dt><dd>{registration.event.description}</dd></div>
          {registration.event.purpose && <div className="event-detail full"><dt>Purpose</dt><dd>{registration.event.purpose}</dd></div>}
        </dl>
      </section>
    </article>
  </div>
}
