import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { eventApi } from '../features/event/submission'
import type { SubmittedEvent } from '../features/event/submission'
import { fetchRegistrations } from '../features/registration/registrations'
import type { Registration } from '../features/registration/registrations'
import { RegistrationTable } from '../features/registration/RegistrationTable'
import { EventOverview } from '../features/event/EventOverview'
import { StatusBadge } from '../components/FormControls'
import { ArrowLeftIcon, RefreshIcon } from '../components/Icon'
import { DetailPanelSkeleton, TableSkeleton } from '../components/Loading'
import { ClarificationHistory } from '../features/event/ClarificationHistory'
import { ChangeRequestDialog } from '../features/event/ChangeRequestDialog'

const CHANGE_REQUEST_STATUSES = ['Submitted', 'Under Review', 'Approved'] as const

export function OrganiserEventDetailPage({ eventId, organiserId, resolveUserName, backLabel, onBack }: { eventId: string; organiserId?: string; resolveUserName?: (userId: string | null | undefined) => string | null; backLabel: string; onBack: () => void }) {
  const [event, setEvent] = useState<SubmittedEvent | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)
  const [registrations, setRegistrations] = useState<Registration[]>([])
  const [registrationsError, setRegistrationsError] = useState('')
  const [registrationsLoading, setRegistrationsLoading] = useState(true)
  const [response, setResponse] = useState('')
  const [responding, setResponding] = useState(false)
  const [responseError, setResponseError] = useState('')
  const [responseMessage, setResponseMessage] = useState('')
  const [requestingChanges, setRequestingChanges] = useState(false)
  const [changeRequestSubmitted, setChangeRequestSubmitted] = useState(false)

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

  const submitClarificationResponse = async (formEvent: FormEvent) => {
    formEvent.preventDefault()
    if (!event || !organiserId || !response.trim()) return
    setResponding(true)
    setResponseError('')
    setResponseMessage('')
    try {
      const updated = await eventApi(
        `/events/${event.id}/clarification-response`,
        { organiserId, response: response.trim() },
        'PATCH',
      )
      setEvent(updated)
      setResponse('')
      setResponseMessage('Your clarification response was submitted. The request is back with the same Event Coordinator.')
    } catch (cause) {
      setResponseError(cause instanceof Error ? cause.message : 'Unable to submit your clarification response.')
    } finally {
      setResponding(false)
    }
  }

  return <div className="page-stack">
    <section className="intro">
      <button className="button small" onClick={onBack}><ArrowLeftIcon size={13} /> Back to {backLabel}</button>{' '}
      <button className="button small" onClick={() => { setLoading(true); setError(''); setRegistrationsLoading(true); setRefresh((value) => value + 1) }}><RefreshIcon size={13} /> Refresh</button>
    </section>
    {loading ? <DetailPanelSkeleton /> : error ? <p className="field-error" role="alert">{error}</p> : event && <article className="panel event-card">
      <header className="event-card-header"><h2>{event.eventName}</h2><div className="event-card-header-actions">
        <StatusBadge status={event.status} />
        {!changeRequestSubmitted && !requestingChanges && CHANGE_REQUEST_STATUSES.includes(event.status as typeof CHANGE_REQUEST_STATUSES[number]) && organiserId &&
          <button className="button primary small" type="button" onClick={() => setRequestingChanges(true)}>Request changes</button>}
      </div></header>
      {event.decision?.status === 'Rejected' && <section className="event-card-section">
        <h3>Event request decision</h3>
        <p>Rejected</p>
        <h4>Rejection reason</h4>
        <p style={{ whiteSpace: 'pre-wrap' }}>{event.decision.reason}</p>
      </section>}
      <EventOverview event={event} coordinatorName={resolveUserName?.(event.coordinatorId)} assignedByName={resolveUserName?.(event.assignedBy)} previousCoordinatorName={resolveUserName?.(event.previousCoordinatorId)} />

      {requestingChanges && organiserId && <ChangeRequestDialog event={event} organiserId={organiserId}
        onCancel={() => setRequestingChanges(false)} onSubmitted={() => { setRequestingChanges(false); setChangeRequestSubmitted(true) }} />}
      {changeRequestSubmitted && <p className="event-card-section" role="status">Your change request was submitted and is pending review.</p>}

      {event.status === 'Clarification Requested' && <section className="event-card-section">
        <h3>Response required</h3>
        <p>The assigned Event Coordinator needs more information. Reply below; the original request fields remain unchanged.</p>
        <form onSubmit={submitClarificationResponse}>
          <label className="field"><span>Clarification response <span className="required">*</span></span>
            <textarea value={response} onChange={(change) => { setResponse(change.target.value); setResponseError(''); setResponseMessage('') }} maxLength={1000} required placeholder="Provide the information requested by the coordinator." disabled={responding} />
            <small>{response.length}/1000 characters</small>
          </label>
          {responseError && <p className="field-error" role="alert">{responseError}</p>}
          <button className="button primary" type="submit" disabled={!response.trim() || responding}>{responding ? 'Submitting…' : 'Submit response'}</button>
        </form>
      </section>}
      {responseMessage && <p className="event-card-section" role="status">{responseMessage}</p>}
      <ClarificationHistory clarifications={event.clarificationHistory || []} resolveUserName={resolveUserName} />

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
