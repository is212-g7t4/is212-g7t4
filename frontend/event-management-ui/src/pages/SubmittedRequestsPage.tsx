import { useEffect, useState } from 'react'
import type { Role } from '../types'
import { isCoordinator, isLead } from '../roles'
import { assignmentApi, eventApi } from '../features/event/submission'
import type { Coordinator, SubmittedEvent } from '../features/event/submission'
import { EventOverview } from '../features/event/EventOverview'
import { ReassignCoordinatorPanel } from '../features/event/ReassignCoordinatorPanel'
import { canReassign } from '../features/event/eventStatus'
import { RoleWarning, StatusBadge } from '../components/FormControls'
import { SubmissionPopup } from '../components/SubmissionPopup'
import { RejectionDialog } from '../components/RejectionDialog'
import { ArrowRightIcon, RefreshIcon } from '../components/Icon'
import { EventCardSkeletonList, Spinner } from '../components/Loading'

export function SubmittedRequestsPage({ role, currentCoordinatorId, currentCoordinatorName, resolveUserName, onViewDetails }: { role: Role; currentCoordinatorId?: string; currentCoordinatorName?: string; resolveUserName?: (userId: string | null | undefined) => string | null; onViewDetails: (id: string) => void }) {
  const [events, setEvents] = useState<SubmittedEvent[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)
  const [decisionId, setDecisionId] = useState<string | null>(null)
  const [rejecting, setRejecting] = useState<SubmittedEvent | null>(null)
  const [reason, setReason] = useState('')
  const [coordinators, setCoordinators] = useState<Coordinator[]>([])
  const [popup, setPopup] = useState<{ title: string; messages: string[] } | null>(null)

  const currentCoordinator = {
    id: currentCoordinatorId || import.meta.env.VITE_CURRENT_COORDINATOR_ID || '',
    name: currentCoordinatorName || import.meta.env.VITE_CURRENT_COORDINATOR_NAME || '',
  }

  useEffect(() => {
    if (!isCoordinator(role) || !currentCoordinator.id) return
    let active = true
    const params = new URLSearchParams({ coordinatorId: currentCoordinator.id })
    if (isLead(role)) params.set('viewerRole', role)
    Promise.all([eventApi(`/events/submitted?${params.toString()}`), assignmentApi('/coordinators')]).then(([eventBody, coordinatorBody]) => {
      if (!active) return
      setEvents(eventBody.events)
      setCoordinators(coordinatorBody.coordinators)
    }).catch((cause: Error) => {
      if (active) setError(cause.message)
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [role, currentCoordinator.id, refresh])

  const approve = async (event: SubmittedEvent) => {
    setDecisionId(event.id)
    try {
      const approved = await eventApi(
        `/events/${event.id}/approve`,
        { coordinatorId: currentCoordinator.id },
        'PATCH',
      )
      setEvents((current) => current.filter((item) => item.id !== event.id))
      setPopup({
        title: 'Event Request Approved',
        messages: [approved.decision?.decidedAt
          ? `${approved.eventName} was approved on ${new Date(approved.decision.decidedAt).toLocaleString('en-SG', { timeZone: 'Asia/Singapore' })} SGT.`
          : `${approved.eventName} was approved.`],
      })
    } catch (cause) {
      setPopup({
        title: 'Approval Failed',
        messages: [cause instanceof Error ? cause.message : 'Unable to approve the event request.'],
      })
    } finally {
      setDecisionId(null)
    }
  }

  const reject = async () => {
    if (!rejecting || !reason.trim()) return
    const event = rejecting
    setDecisionId(event.id)
    try {
      const rejected = await eventApi(
        `/events/${event.id}/reject`,
        { coordinatorId: currentCoordinator.id, reason: reason.trim() },
        'PATCH',
      )
      setEvents((current) => current.filter((item) => item.id !== event.id))
      setRejecting(null)
      setReason('')
      setPopup({
        title: 'Event Request Rejected',
        messages: [rejected.decision?.reason || 'The event request was rejected.'],
      })
    } catch (cause) {
      setPopup({
        title: 'Rejection Failed',
        messages: [cause instanceof Error ? cause.message : 'Unable to reject the event request.'],
      })
    } finally {
      setDecisionId(null)
    }
  }

  if (!isCoordinator(role)) return <RoleWarning>Submitted event requests are visible to Event Coordinators.</RoleWarning>

  return <div className="page-stack">
    {popup && <SubmissionPopup {...popup} onClose={() => setPopup(null)} />}
    <section className="intro"><h1>Submitted event requests</h1><p className="muted">Signed in for this prototype as {currentCoordinator.name}. Preferred times are Singapore time (SGT).</p>
      <button className="button" onClick={() => { setLoading(true); setError(''); setRefresh((value) => value + 1) }}><RefreshIcon size={14} /> Refresh requests</button></section>
    {loading ? <EventCardSkeletonList /> : error ? <p className="field-error" role="alert">{error}</p> :
      events.length === 0 ? <p>No submitted event requests yet.</p> :
      events.map((event) => <article key={event.id} className="panel event-card">
        <header className="event-card-header">
          <h2>{event.eventName}</h2>
          <div className="event-card-header-actions">
            <StatusBadge status={event.status} />
            <button className="button small" onClick={() => onViewDetails(event.id)}>View details <ArrowRightIcon size={13} /></button>
          </div>
        </header>
        <EventOverview event={event} coordinatorName={coordinators.find((coordinator) => coordinator.user_id === event.coordinatorId)?.username ?? resolveUserName?.(event.coordinatorId)} assignedByName={resolveUserName?.(event.assignedBy)} previousCoordinatorName={resolveUserName?.(event.previousCoordinatorId)} />

        {event.coordinatorId
          ? <div className="event-card-actions">
              {isLead(role) && canReassign(event) && <ReassignCoordinatorPanel
                event={event}
                leadId={currentCoordinator.id}
                coordinators={coordinators}
                onReassigned={(updated) => setEvents((current) => current.map((item) => item.id === updated.id ? updated : item))}
              />}

              {event.coordinatorId === currentCoordinator.id && <div className="table-actions">
                <button className="button approve" disabled={decisionId === event.id} onClick={() => approve(event)}>{decisionId === event.id && <Spinner size={12} />}{decisionId === event.id ? 'Processing…' : 'Approve Request'}</button>
                <button className="button reject" disabled={decisionId === event.id} onClick={() => { setRejecting(event); setReason('') }}>Reject Request</button>
              </div>}
            </div>
          : isLead(role) && <p className="muted">Not assigned yet. Assign it from Unassigned requests.</p>}
      </article>)}
    {rejecting && <RejectionDialog eventName={rejecting.eventName} reason={reason} submitting={decisionId === rejecting.id} onReasonChange={setReason} onCancel={() => { setRejecting(null); setReason('') }} onConfirm={reject} />}
  </div>
}

