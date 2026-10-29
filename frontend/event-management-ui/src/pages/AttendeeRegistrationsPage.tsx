import { useEffect, useState } from 'react'
import { RoleWarning, StatusBadge } from '../components/FormControls'
import { ArrowLeftIcon, ArrowRightIcon, RefreshIcon } from '../components/Icon'
import { EventCardSkeletonList } from '../components/Loading'
import { formatSchedule, getDateTile } from '../features/event/dateFormat'
import type { AttendeeRegistration } from '../features/registration/attendeeRegistrations'
import { loadAttendeeRegistrations, withdrawRegistration } from '../features/registration/attendeeRegistrations'
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

export function AttendeeRegistrationsPage({ role, attendeeId, targetRegistrationId }: { role: Role; attendeeId?: string; targetRegistrationId?: string | null }) {
  const [registrations, setRegistrations] = useState<AttendeeRegistration[]>([])
  const [selected, setSelected] = useState<AttendeeRegistration | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    if (role !== 'Attendee' || !attendeeId) return
    let active = true
    loadAttendeeRegistrations(attendeeId).then((items) => {
      if (active) {
        setRegistrations(items)
        if (targetRegistrationId) setSelected(items.find(item => item.id === targetRegistrationId && item.attendeeId === attendeeId) ?? null)
      }
    }).catch((cause: Error) => {
      if (active) setError(cause.message)
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [role, attendeeId, revision, targetRegistrationId])

  if (role !== 'Attendee') return <RoleWarning>Registration status is visible only to Attendees.</RoleWarning>
  if (!attendeeId) return <p className="field-error" role="alert">Select an attendee to view registrations.</p>
  if (selected && selected.attendeeId === attendeeId) return <RegistrationDetail
    key={selected.id}
    registration={selected}
    onBack={() => setSelected(null)}
    onWithdrawn={(updated) => setRegistrations((items) => items.map((item) => item.id === updated.id ? updated : item))}
  />

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
        {registrations.filter(registration => registration.attendeeId === attendeeId).map((registration) => {
          const tile = getDateTile(registration.event.preferredStartDate)
          return <button key={registration.id} type="button" className="panel event-row-card" onClick={() => setSelected(registration)}>
            <span className="event-row-date"><span className="event-row-date-month">{tile.month}</span><span className="event-row-date-day">{tile.day}</span></span>
            <span className="event-row-body">
              <span className="event-row-heading"><strong>{registration.event.eventName}</strong><StatusBadge status={registration.status} />{registration.event.status === 'Cancelled' && <span>Event Cancelled</span>}</span>
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

function RegistrationDetail({ registration, onBack, onWithdrawn }: {
  registration: AttendeeRegistration
  onBack: () => void
  onWithdrawn: (registration: AttendeeRegistration) => void
}) {
  const [current, setCurrent] = useState(registration)
  const [confirming, setConfirming] = useState(false)
  const [withdrawing, setWithdrawing] = useState(false)
  const [message, setMessage] = useState('')
  const [withdrawalError, setWithdrawalError] = useState('')

  const withdraw = async () => {
    if (withdrawing) return
    setWithdrawing(true)
    setWithdrawalError('')
    try {
      const result = await withdrawRegistration(current.id, current.attendeeId)
      const updated = { ...current, status: result.status, withdrawnAt: result.withdrawnAt }
      setCurrent(updated)
      onWithdrawn(updated)
      setConfirming(false)
      setMessage(result.message)
    } catch (cause) {
      setWithdrawalError(cause instanceof Error ? cause.message : 'Unable to withdraw this registration.')
    } finally {
      setWithdrawing(false)
    }
  }

  return <div className="page-stack">
    <section className="intro"><button className="button small" onClick={onBack}><ArrowLeftIcon size={13} /> Back to registrations</button></section>
    <article className="panel event-card">
      <header className="event-card-header"><h2>{current.event.eventName}</h2><StatusBadge status={current.status} /></header>

      {current.event.status === 'Cancelled' && <p className="notice">Event Cancelled</p>}
      {message && <p className="notice success" role="status">{message}</p>}

      <section className="event-card-section">
        <h3>Registration details</h3>
        <dl className="event-details">
          <div className="event-detail full"><dt>Registration reference</dt><dd>{current.id}</dd></div>
          <div className="event-detail"><dt>Status</dt><dd>{current.status}</dd></div>
          <div className="event-detail"><dt>Registration date</dt><dd>{formatRegistrationDate(current.registrationDate)}</dd></div>
          {current.withdrawnAt && <div className="event-detail"><dt>Withdrawn at</dt><dd>{formatRegistrationDate(current.withdrawnAt)}</dd></div>}
          <div className="event-detail"><dt>Name</dt><dd>{current.attendeeName}</dd></div>
          <div className="event-detail"><dt>Email</dt><dd>{current.attendeeEmail}</dd></div>
          <div className="event-detail full"><dt>Organisation</dt><dd>{current.attendeeOrganization || '—'}</dd></div>
        </dl>
        {current.status === 'Confirmed' && current.event.status === 'Confirmed' && !confirming && <button className="button primary" type="button" onClick={() => { setConfirming(true); setWithdrawalError('') }}>Withdraw registration</button>}
        {confirming && <div className="panel" role="dialog" aria-label="Confirm withdrawal">
          <h4>Withdraw registration?</h4>
          <p>Your place will be released for another attendee.</p>
          {withdrawalError && <p className="field-error" role="alert">{withdrawalError}</p>}
          <div className="button-row">
            <button className="button primary" type="button" disabled={withdrawing} onClick={withdraw}>{withdrawing ? 'Withdrawing…' : 'Confirm withdrawal'}</button>
            <button className="button" type="button" disabled={withdrawing} onClick={() => { setConfirming(false); setWithdrawalError('') }}>Keep registration</button>
          </div>
        </div>}
      </section>

      <section className="event-card-section">
        <h3>Event details</h3>
        <dl className="event-details">
          <div className="event-detail full"><dt>Date and time</dt><dd>{formatSchedule(current.event.preferredStartDate, current.event.preferredEndDate)}</dd></div>
          <div className="event-detail full"><dt>Withdrawal deadline</dt><dd>{formatRegistrationDate(current.event.withdrawalDeadline || current.event.preferredStartDate)}</dd></div>
          {current.venue && <>
            <div className="event-detail"><dt>Venue</dt><dd>{current.venue.name}</dd></div>
            <div className="event-detail"><dt>Location</dt><dd>{current.venue.location}</dd></div>
          </>}
          <div className="event-detail full"><dt>Description</dt><dd>{current.event.description}</dd></div>
          {current.event.purpose && <div className="event-detail full"><dt>Purpose</dt><dd>{current.event.purpose}</dd></div>}
        </dl>
      </section>
    </article>
  </div>
}
