import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import type { Role } from '../types'
import { eventApi } from '../features/event/submission'
import type { EventStatus, SubmittedEvent } from '../features/event/submission'
import { ALLOWED_TRANSITIONS, safetyBlockMessage, showsSafetyHint } from '../features/event/eventStatus'
import { EventOverview } from '../features/event/EventOverview'
import { canViewAllInternalEvents, canViewInternalEvents, INTERNAL_EVENT_ACCESS_MESSAGE } from '../features/event/permissions'
import { fetchRegistrations } from '../features/registration/registrations'
import type { Registration } from '../features/registration/registrations'
import { RegistrationTable } from '../features/registration/RegistrationTable'
import { RoleWarning, StatusBadge } from '../components/FormControls'
import { ArrowLeftIcon, RefreshIcon } from '../components/Icon'
import { DetailPanelSkeleton, TableSkeleton } from '../components/Loading'
import { OrganiserEventDetailPage } from './OrganiserEventDetailPage'
import { VenueBookingsPanel } from '../features/venue/VenueBookingsPanel'
import { SafetySubmitPanel } from '../features/safety/SafetySubmitPanel'
import { SafetyDecisionPanel } from '../features/safety/SafetyDecisionPanel'
import { submittedForSafetyCheckAt } from '../features/safety/safetyCheck'

type EventDetailProps = { eventId: string; role: Role; isManager: boolean; currentCoordinatorId?: string; currentCoordinatorName?: string; resolveUserName?: (userId: string | null | undefined) => string | null; backLabel: string; onBack: () => void }

// `currentCoordinatorId` carries the active user, whatever their role.
export function EventDetailPage(props: EventDetailProps) {
  if (props.role === 'Event Organiser') {
    return <OrganiserEventDetailPage eventId={props.eventId} organiserId={props.currentCoordinatorId} resolveUserName={props.resolveUserName} backLabel={props.backLabel} onBack={props.onBack} />
  }
  return <CoordinatorEventDetail {...props} />
}

function CoordinatorEventDetail({ eventId, role, isManager, currentCoordinatorId, currentCoordinatorName, resolveUserName, backLabel, onBack }: EventDetailProps) {
  const [event, setEvent] = useState<SubmittedEvent | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)
  const [registrations, setRegistrations] = useState<Registration[]>([])
  const [registrationsError, setRegistrationsError] = useState('')
  const [registrationsLoading, setRegistrationsLoading] = useState(true)
  const [draftStatus, setDraftStatus] = useState<EventStatus>('Submitted')
  const [actionDetails, setActionDetails] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [saveMessage, setSaveMessage] = useState('')
  // SCRUM-149: a venue booking change can make the event ready (or not), so
  // the safety panel re-reads its readiness whenever one is saved or cancelled.
  const [bookingsChanged, setBookingsChanged] = useState(0)
  const currentCoordinator = {
    id: currentCoordinatorId || import.meta.env.VITE_CURRENT_COORDINATOR_ID || '',
    name: currentCoordinatorName || import.meta.env.VITE_CURRENT_COORDINATOR_NAME || '',
  }
  useEffect(() => {
    if (!canViewInternalEvents(role) || !currentCoordinator.id) return
    let active = true
    const params = new URLSearchParams({ coordinatorId: currentCoordinator.id })
    if (canViewAllInternalEvents(role, isManager)) params.set('isManager', 'true')
    if (role === 'Venue Staff' || role === 'Technical Support' || role === 'Safety Officer') params.set('viewerRole', role)
    eventApi(`/events/${eventId}?${params.toString()}`).then((body) => {
      if (active) {
        setEvent(body)
        setDraftStatus(body.status)
        setActionDetails(body.actionDetails || '')
        setSaveError('')
        setSaveMessage('')
      }
    }).catch((cause: Error) => {
      if (active) setError(cause.message)
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [eventId, role, isManager, refresh, currentCoordinator.id])

  useEffect(() => {
    if (role !== 'Event Coordinator' || event?.status !== 'Approved') return
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
  }, [eventId, role, event?.status, refresh])

  const hasUnsavedChanges = Boolean(event) && (
    draftStatus !== event?.status || actionDetails !== (event?.actionDetails || '')
  )
  const canUpdate = Boolean(role === 'Event Coordinator' && event && event.coordinatorId === currentCoordinator.id)
  const availableStatuses = event ? ALLOWED_TRANSITIONS[event.status] : []
  // SCRUM-152 AC1: 'Confirmed' is never offered to a coordinator — only the
  // safety workflow sets it — so instead of a dead option the field explains
  // what has to happen for the event to progress.
  const safetyHint = event && showsSafetyHint(event.status) ? safetyBlockMessage(event.status) : ''

  const saveProgress = async (formEvent: FormEvent) => {
    formEvent.preventDefault()
    if (!event || !canUpdate || !hasUnsavedChanges || !actionDetails.trim()) return
    setSaving(true)
    setSaveError('')
    setSaveMessage('')
    try {
      const updated = await eventApi(
        `/events/${event.id}/progress`,
        {
          coordinatorId: currentCoordinator.id,
          status: draftStatus,
          actionDetails: actionDetails.trim(),
        },
        'PATCH',
      )
      setEvent(updated)
      setDraftStatus(updated.status)
      setActionDetails(updated.actionDetails || '')
      setSaveMessage('Event progress updated successfully.')
    } catch (cause) {
      setSaveError(cause instanceof Error ? cause.message : 'Unable to update event progress.')
    } finally {
      setSaving(false)
    }
  }

  if (!canViewInternalEvents(role)) return <RoleWarning>{INTERNAL_EVENT_ACCESS_MESSAGE}</RoleWarning>

  return <div className="page-stack">
    <section className="intro">
      <button className="button small" onClick={onBack}><ArrowLeftIcon size={13} /> Back to {backLabel}</button>{' '}
      <button className="button small" onClick={() => { setLoading(true); setError(''); setRefresh((value) => value + 1) }}><RefreshIcon size={13} /> Refresh</button>
    </section>
    {loading ? <DetailPanelSkeleton /> : error ? <p className="field-error" role="alert">{error}</p> : event && <article className="panel event-card">
      <header className="event-card-header"><h2>{event.eventName}</h2><StatusBadge status={event.status} /></header>
      <EventOverview event={event} coordinatorName={resolveUserName?.(event.coordinatorId)} />
      <p className="muted event-card-section">Venue and equipment are shown as requested — confirmed assignment isn't tracked yet.</p>

      {canUpdate && event.status !== 'Cancelled' && <VenueBookingsPanel
        eventId={event.id}
        coordinatorId={currentCoordinator.id}
        eventStart={event.preferredStartDate}
        eventEnd={event.preferredEndDate}
        eventExpectedAttendance={event.expectedAttendance}
        eventVenueRequirements={event.venueRequirements}
        onBookingsChanged={() => setBookingsChanged((value) => value + 1)}
      />}

      <section className="event-card-section">
        <h3>Event progress</h3>
        {canUpdate ? <form onSubmit={saveProgress}>
          <div className="field-row">
            {/* Explicitly associated rather than wrapping, so the safety hint
                below can live in the same field without becoming label text. */}
            <div className="field">
              <label htmlFor="event-progress-status">Status</label>
              <select id="event-progress-status" value={draftStatus} onChange={(change) => {
                setDraftStatus(change.target.value as typeof draftStatus)
                setSaveMessage('')
              }}>
                {availableStatuses.map((status) => <option key={status} value={status}>{status}</option>)}
              </select>
              {safetyHint && <span className="muted" role="note">{safetyHint}</span>}
            </div>
            <label className="field"><span>Action details</span>
              <textarea value={actionDetails} maxLength={1000} required onChange={(change) => {
                setActionDetails(change.target.value)
                setSaveMessage('')
              }} placeholder="Describe the action completed or the latest progress." />
            </label>
          </div>
          {hasUnsavedChanges && <p className="muted" role="status">Unsaved changes</p>}
          {saveError && <p className="field-error" role="alert">{saveError}</p>}
          {saveMessage && <p role="status">{saveMessage}</p>}
          <button className="button primary" type="submit" disabled={!hasUnsavedChanges || !actionDetails.trim() || saving}>
            {saving ? 'Saving…' : 'Save progress'}
          </button>
        </form> : <p className="muted">Only the assigned Event Coordinator can update this event.</p>}

        {/* SCRUM-149: the next step the safety hint above points at. Only the
            event's own assigned coordinator sees it (AC5), and only while the
            event is Approved — once submitted it becomes the note below. */}
        {canUpdate && event.status === 'Approved' && <SafetySubmitPanel
          eventId={event.id}
          coordinatorId={currentCoordinator.id}
          refreshKey={bookingsChanged}
          onSubmitted={() => { setLoading(true); setRefresh((value) => value + 1) }}
        />}
        {/* SCRUM-150: the Safety Officer's decision, offered only while the
            event is actually awaiting one (AC3, UI side). */}
        {role === 'Safety Officer' && event.status === 'Pending Safety Check' && <SafetyDecisionPanel
          eventId={event.id}
          eventName={event.eventName}
          safetyOfficerId={currentCoordinator.id}
          onDecided={() => { setLoading(true); setRefresh((value) => value + 1) }}
        />}
        {event.status === 'Pending Safety Check' && role !== 'Safety Officer' && (() => {
          const submittedAt = submittedForSafetyCheckAt(event)
          return <p className="muted" role="status">
            {submittedAt
              ? `Submitted for safety check on ${new Date(submittedAt).toLocaleString('en-SG', { timeZone: 'Asia/Singapore' })} SGT.`
              : 'Submitted for safety check.'}
          </p>
        })()}

        <h3>Action history</h3>
        {event.actionHistory.length === 0 ? <p className="muted">No actions recorded yet.</p> :
          <dl className="event-details">
            {event.actionHistory.map((action, index) => <div className="event-detail full" key={`${action.recordedAt}-${index}`}>
              <dt>{action.status} · {new Date(action.recordedAt).toLocaleString('en-SG', { timeZone: 'Asia/Singapore' })} SGT</dt>
              <dd>
                {action.details}
                {action.areas && action.areas.length > 0 && <>
                  <br /><span className="muted">Areas: {action.areas.join(', ')}</span>
                </>}
                {action.remarks && <>
                  <br /><span className="muted">Reason: {action.remarks}</span>
                </>}
              </dd>
            </div>)}
          </dl>}
      </section>

      {event.status === 'Approved' && <div className="event-card-section">
        <h3>Registrations</h3>
        {registrationsLoading ? <TableSkeleton rows={3} columns={5} /> : registrationsError ? <p className="field-error" role="alert">{registrationsError}</p> : <>
          {(() => {
            const confirmedCount = registrations.filter((registration) => registration.status === 'Confirmed').length
            const capacity = Number(event.expectedAttendance)
            const hasCapacity = event.expectedAttendance.trim() !== '' && !Number.isNaN(capacity)
            return <dl className="event-details">
              <div className="event-detail"><dt>Total registrations</dt><dd>{registrations.length}</dd></div>
              <div className="event-detail"><dt>Capacity</dt><dd>{hasCapacity ? capacity : 'Not set'}</dd></div>
              <div className="event-detail"><dt>Remaining spots</dt><dd>{hasCapacity ? capacity - confirmedCount : 'Not set'}</dd></div>
            </dl>
          })()}
          <RegistrationTable registrations={registrations} />
        </>}
      </div>}
    </article>}
  </div>
}
