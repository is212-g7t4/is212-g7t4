import { useEffect, useState } from 'react'
import type { Role } from '../types'
import { loadAttendeeEvents } from '../features/event/attendeeEvents'
import type { AttendeeEvent } from '../features/event/attendeeEvents'
import { formatSchedule, getDateTile } from '../features/event/dateFormat'
import { RoleWarning, StatusBadge } from '../components/FormControls'
import { ArrowLeftIcon, ArrowRightIcon, RefreshIcon } from '../components/Icon'
import { EventCardSkeletonList } from '../components/Loading'

function optionalDate(value?: string) {
  if (!value) return ''
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('en-SG', {
    timeZone: 'Asia/Singapore', day: 'numeric', month: 'short', year: 'numeric',
    hour: 'numeric', minute: '2-digit', hour12: true,
  })
}

export function AttendeeEventsPage({ role }: { role: Role }) {
  const [events, setEvents] = useState<AttendeeEvent[]>([])
  const [selected, setSelected] = useState<AttendeeEvent | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    if (role !== 'Attendee') return
    let active = true
    loadAttendeeEvents().then((items) => {
      if (active) setEvents(items)
    }).catch((cause: Error) => {
      if (active) setError(cause.message)
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [role, revision])

  if (role !== 'Attendee') return <RoleWarning>Confirmed events open for registration are visible to Attendees.</RoleWarning>

  if (selected) return <AttendeeEventDetail event={selected} onBack={() => setSelected(null)} />

  return <div className="page-stack">
    <section className="intro">
      <h1>Browse events</h1>
      <p className="muted">Explore upcoming confirmed events and check whether registration is open.</p>
      <button className="button small" onClick={() => { setLoading(true); setError(''); setRevision((value) => value + 1) }}>
        <RefreshIcon size={13} /> Refresh events
      </button>
    </section>

    {loading ? <EventCardSkeletonList /> : error ? <p className="field-error" role="alert">{error}</p> :
      events.length === 0 ? <section className="panel"><p>There are no upcoming confirmed events available for registration.</p></section> :
      <section className="page-stack" aria-label="Upcoming confirmed events">
        {events.map((event) => {
          const tile = getDateTile(event.preferredStartDate)
          return <button key={event.id} type="button" className="panel event-row-card" onClick={() => setSelected(event)}>
            <span className="event-row-date"><span className="event-row-date-month">{tile.month}</span><span className="event-row-date-day">{tile.day}</span></span>
            <span className="event-row-body">
              <span className="event-row-heading"><strong>{event.eventName}</strong><StatusBadge status={event.registrationStatus} /></span>
              <span className="event-row-schedule muted">{formatSchedule(event.preferredStartDate, event.preferredEndDate)}</span>
              {event.venue && <span className="event-row-venue muted">{event.venue.name} · {event.venue.location}</span>}
              <span>{event.description}</span>
              {event.purpose && <span className="muted">{event.purpose}</span>}
              {event.registrationDeadline && <span className="muted">Registration deadline: {optionalDate(event.registrationDeadline)}</span>}
            </span>
            <ArrowRightIcon size={16} className="icon" />
          </button>
        })}
      </section>}
  </div>
}

function AttendeeEventDetail({ event, onBack }: { event: AttendeeEvent; onBack: () => void }) {
  return <div className="page-stack">
    <section className="intro"><button className="button small" onClick={onBack}><ArrowLeftIcon size={13} /> Back to events</button></section>
    <article className="panel event-card">
      <header className="event-card-header"><h2>{event.eventName}</h2><StatusBadge status={event.registrationStatus} /></header>
      <div className="event-facts">
        <span><strong>{formatSchedule(event.preferredStartDate, event.preferredEndDate)}</strong>Date and time</span>
        <span><strong>{event.confirmedRegistrations} / {event.expectedAttendance}</strong>Registered</span>
      </div>
      <dl className="event-details">
        <div className="event-detail full"><dt>Description</dt><dd>{event.description}</dd></div>
        {event.purpose && <div className="event-detail full"><dt>Purpose</dt><dd>{event.purpose}</dd></div>}
      </dl>

      {event.programme && <section className="event-card-section"><h3>Programme and agenda</h3><p>{event.programme}</p></section>}

      {event.venue && <section className="event-card-section">
        <h3>Venue</h3>
        <dl className="event-details">
          <div className="event-detail"><dt>Name</dt><dd>{event.venue.name}</dd></div>
          <div className="event-detail"><dt>Location</dt><dd>{event.venue.location}</dd></div>
          {event.venue.facilities.length > 0 && <div className="event-detail full"><dt>Facilities</dt><dd>{event.venue.facilities.join(', ')}</dd></div>}
          {event.venue.accessibility && <div className="event-detail full"><dt>Accessibility</dt><dd>{event.venue.accessibility}</dd></div>}
        </dl>
      </section>}

      <section className="event-card-section">
        <h3>Registration</h3>
        <dl className="event-details">
          <div className="event-detail"><dt>Status</dt><dd>{event.registrationStatus}</dd></div>
          {event.registrationDeadline && <div className="event-detail"><dt>Deadline</dt><dd>{optionalDate(event.registrationDeadline)}</dd></div>}
          {event.registrationNeeds && <div className="event-detail full"><dt>Requirements and instructions</dt><dd>{event.registrationNeeds}</dd></div>}
        </dl>
      </section>

      {event.organiser && (event.organiser.email || event.organiser.contactDetails) && <section className="event-card-section">
        <h3>Contact for enquiries</h3>
        <dl className="event-details">
          <div className="event-detail"><dt>Event Organiser</dt><dd>{event.organiser.username}</dd></div>
          {event.organiser.email && <div className="event-detail"><dt>Email</dt><dd><a href={`mailto:${event.organiser.email}`}>{event.organiser.email}</a></dd></div>}
          {event.organiser.contactDetails && <div className="event-detail"><dt>Contact</dt><dd>{event.organiser.contactDetails}</dd></div>}
        </dl>
      </section>}
    </article>
  </div>
}
