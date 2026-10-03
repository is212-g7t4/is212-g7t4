import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import type { Role } from '../types'
import { eventApi } from '../features/event/submission'
import type { EventStatus, SubmittedEvent } from '../features/event/submission'
import { EventOverview } from '../features/event/EventOverview'
import { fetchRegistrations } from '../features/registration/registrations'
import type { Registration } from '../features/registration/registrations'
import { RoleWarning, StatusBadge } from '../components/FormControls'
import { ArrowLeftIcon, RefreshIcon } from '../components/Icon'
import { DetailPanelSkeleton, TableSkeleton } from '../components/Loading'

export function EventDetailPage({ eventId, role, isManager, currentCoordinatorId, currentCoordinatorName, resolveUserName, backLabel, onBack }: { eventId: string; role: Role; isManager: boolean; currentCoordinatorId?: string; currentCoordinatorName?: string; resolveUserName?: (userId: string | null | undefined) => string | null; backLabel: string; onBack: () => void }) {
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
  const currentCoordinator = {
    id: currentCoordinatorId || import.meta.env.VITE_CURRENT_COORDINATOR_ID || '',
    name: currentCoordinatorName || import.meta.env.VITE_CURRENT_COORDINATOR_NAME || '',
  }
  useEffect(() => {
    if (role !== 'Event Coordinator' || !currentCoordinator.id) return
    let active = true
    const params = new URLSearchParams({ coordinatorId: currentCoordinator.id })
    if (isManager) params.set('isManager', 'true')
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
  const canUpdate = Boolean(event && event.coordinatorId === currentCoordinator.id)
  const transitions: Record<EventStatus, EventStatus[]> = {
    Submitted: ['Submitted', 'Under Review'],
    'Under Review': ['Under Review', 'Approved', 'Rejected'],
    Approved: ['Approved', 'Confirmed'],
    Confirmed: ['Confirmed'],
    Rejected: ['Rejected'],
  }
  const availableStatuses = event ? transitions[event.status] : []

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

  if (role !== 'Event Coordinator') return <RoleWarning>Event details are visible to Event Coordinators.</RoleWarning>

  return <div className="page-stack">
    <section className="intro">
      <button className="button small" onClick={onBack}><ArrowLeftIcon size={13} /> Back to {backLabel}</button>{' '}
      <button className="button small" onClick={() => { setLoading(true); setError(''); setRefresh((value) => value + 1) }}><RefreshIcon size={13} /> Refresh</button>
    </section>
    {loading ? <DetailPanelSkeleton /> : error ? <p className="field-error" role="alert">{error}</p> : event && <article className="panel event-card">
      <header className="event-card-header"><h2>{event.eventName}</h2><StatusBadge status={event.status} /></header>
      <EventOverview event={event} coordinatorName={resolveUserName?.(event.coordinatorId)} />
      <p className="muted event-card-section">Venue and equipment are shown as requested — confirmed assignment isn't tracked yet.</p>

      <section className="event-card-section">
        <h3>Event progress</h3>
        {canUpdate ? <form onSubmit={saveProgress}>
          <div className="field-row">
            <label className="field"><span>Status</span>
              <select value={draftStatus} onChange={(change) => {
                setDraftStatus(change.target.value as typeof draftStatus)
                setSaveMessage('')
              }}>
                {availableStatuses.map((status) => <option key={status} value={status}>{status}</option>)}
              </select>
            </label>
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

        <h3>Action history</h3>
        {event.actionHistory.length === 0 ? <p className="muted">No actions recorded yet.</p> :
          <dl className="event-details">
            {event.actionHistory.map((action, index) => <div className="event-detail full" key={`${action.recordedAt}-${index}`}>
              <dt>{action.status} · {new Date(action.recordedAt).toLocaleString('en-SG', { timeZone: 'Asia/Singapore' })} SGT</dt>
              <dd>{action.details}</dd>
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
          {registrations.length === 0 ? <p>No registrations yet.</p> : <div className="table-scroll">
            <table>
              <thead><tr><th>Name</th><th>Email</th><th>Organisation</th><th>Registered</th><th>Status</th></tr></thead>
              <tbody>{registrations.map((registration) => <tr key={registration.id}>
                <td>{registration.attendeeName}</td>
                <td>{registration.attendeeEmail}</td>
                <td>{registration.attendeeOrganization || '—'}</td>
                <td>{registration.registrationDate ? new Date(registration.registrationDate).toLocaleString('en-SG', { timeZone: 'Asia/Singapore' }) : 'Not recorded'}</td>
                <td>{registration.status}</td>
              </tr>)}</tbody>
            </table>
          </div>}
        </>}
      </div>}
    </article>}
  </div>
}
