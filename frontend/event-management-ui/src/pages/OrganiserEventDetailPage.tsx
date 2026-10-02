import { useEffect, useState } from 'react'
import { eventApi } from '../features/event/submission'
import type { SubmittedEvent } from '../features/event/submission'
import { fetchRegistrations } from '../features/registration/registrations'
import type { Registration } from '../features/registration/registrations'
import { RegistrationTable } from '../features/registration/RegistrationTable'
import { EventOverview } from '../features/event/EventOverview'
import { StatusBadge } from '../components/FormControls'
import { ArrowLeftIcon, RefreshIcon } from '../components/Icon'
import { DetailPanelSkeleton, TableSkeleton } from '../components/Loading'

export function OrganiserEventDetailPage({ eventId, organiserId, resolveUserName, backLabel, onBack }: { eventId: string; organiserId?: string; resolveUserName?: (userId: string | null | undefined) => string | null; backLabel: string; onBack: () => void }) {
  const [event, setEvent] = useState<SubmittedEvent | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)
  const [registrations, setRegistrations] = useState<Registration[]>([])
  const [registrationsError, setRegistrationsError] = useState('')
  const [registrationsLoading, setRegistrationsLoading] = useState(true)

  useEffect(() => {
    if (!organiserId) return
    let active = true
    // The event service refuses (403) events this organiser did not create, so registrations are only requested after it succeeds.
    eventApi(`/events/${eventId}?organiserId=${organiserId}`).then((body) => {
      if (active) setEvent(body)
    }).catch((cause: Error) => {
      if (active) setError(cause.message)
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [eventId, organiserId, refresh])

  useEffect(() => {
    if (event?.status !== 'Approved') return
    let active = true
    fetchRegistrations(eventId).then((fetched) => {
      if (active) {
        setRegistrations(fetched)
        setRegistrationsError('')
      }
    }).catch((cause: Error) => {
      if (active) setRegistrationsError(cause.message)
    }).finally(() => { if (active) setRegistrationsLoading(false) })
    return () => { active = false }
  }, [eventId, event?.status, refresh])

  const confirmed = registrations.filter((registration) => registration.status === 'Confirmed').length
  const withdrawn = registrations.filter((registration) => registration.status === 'Withdrawn').length

  return <div className="page-stack">
    <section className="intro">
      <button className="button small" onClick={onBack}><ArrowLeftIcon size={13} /> Back to {backLabel}</button>{' '}
      <button className="button small" onClick={() => { setLoading(true); setError(''); setRegistrationsLoading(true); setRefresh((value) => value + 1) }}><RefreshIcon size={13} /> Refresh</button>
    </section>
    {loading ? <DetailPanelSkeleton /> : error ? <p className="field-error" role="alert">{error}</p> : event && <article className="panel event-card">
      <header className="event-card-header"><h2>{event.eventName}</h2><StatusBadge status={event.status} /></header>
      <EventOverview event={event} coordinatorName={resolveUserName?.(event.coordinatorId)} />

      <div className="event-card-section">
        <h3>Registrations</h3>
        {event.status !== 'Approved' ? <p>Registrations are only available for approved events.</p> :
          registrationsLoading ? <TableSkeleton rows={3} columns={5} /> : registrationsError ? <p className="field-error" role="alert">{registrationsError}</p> : <>
          <dl className="event-details">
            <div className="event-detail"><dt>Total registrations</dt><dd>{registrations.length}</dd></div>
            <div className="event-detail"><dt>Confirmed</dt><dd>{confirmed}</dd></div>
            <div className="event-detail"><dt>Withdrawn</dt><dd>{withdrawn}</dd></div>
          </dl>
          <RegistrationTable registrations={registrations} />
        </>}
      </div>
    </article>}
  </div>
}
