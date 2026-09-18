import { useEffect, useState } from 'react'
import type { Role } from '../types'
import { assignmentApi, eventApi } from '../features/event/submission'
import type { Coordinator, SubmittedEvent } from '../features/event/submission'
import { StatusBadge } from '../components/FormControls'
import { SubmissionPopup } from '../components/SubmissionPopup'
import { RejectionDialog } from '../components/RejectionDialog'
import { users } from '../mockData'

export function SubmittedRequestsPage({ role }: { role: Role }) {
  const [events, setEvents] = useState<SubmittedEvent[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)
  const [decisionId, setDecisionId] = useState<string | null>(null)
  const [rejecting, setRejecting] = useState<SubmittedEvent | null>(null)
  const [reason, setReason] = useState('')
  const [coordinators, setCoordinators] = useState<Coordinator[]>([])
  const [assigningId, setAssigningId] = useState<string | null>(null)
  const [selectedCoordinator, setSelectedCoordinator] = useState<Record<string, string>>({})
  const [reassigning, setReassigning] = useState<Record<string, boolean>>({})
  const [assignmentError, setAssignmentError] = useState<Record<string, string>>({})
  const [popup, setPopup] = useState<{ title: string; messages: string[] } | null>(null)

  const currentCoordinator = {
    ...users[0],
    id: import.meta.env.VITE_CURRENT_COORDINATOR_ID || users[0].id,
    name: import.meta.env.VITE_CURRENT_COORDINATOR_NAME || users[0].name,
  }

  useEffect(() => {
    if (role !== 'Event Coordinator') return
    let active = true
    Promise.all([eventApi('/events/submitted'), assignmentApi('/coordinators')]).then(([eventBody, coordinatorBody]) => {
      if (!active) return
      setEvents(eventBody.events)
      setCoordinators(coordinatorBody.coordinators)
    }).catch((cause: Error) => {
      if (active) setError(cause.message)
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [role, refresh])

  const assign = async (event: SubmittedEvent) => {
    const coordinatorId = selectedCoordinator[event.id]
    if (!coordinatorId || coordinatorId === event.coordinatorId) {
      setAssignmentError((current) => ({
        ...current,
        [event.id]: 'Choose a different coordinator before confirming.',
      }))
      return
    }

    setAssigningId(event.id)
    setAssignmentError((current) => ({ ...current, [event.id]: '' }))

    try {
      const result = await assignmentApi(`/events/${event.id}/assign-coordinator/${coordinatorId}`, 'POST')
      const assignedId = result.assignedCoordinatorId || coordinatorId
      setEvents((current) => current.map((item) => item.id === event.id
        ? { ...item, coordinatorId: assignedId }
        : item))
      setReassigning((current) => ({ ...current, [event.id]: false }))
    } catch (cause) {
      setAssignmentError((current) => ({
        ...current,
        [event.id]: cause instanceof Error ? cause.message : 'Unable to assign the coordinator.',
      }))
    } finally {
      setAssigningId(null)
    }
  }

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

  const availableReassignmentCoordinators = (event: SubmittedEvent) =>
    coordinators.filter((coordinator) => coordinator.user_id !== event.coordinatorId)

  if (role !== 'Event Coordinator') return <p className="role-warning">Submitted event requests are visible to Event Coordinators.</p>

  return <div className="page-stack">
    {popup && <SubmissionPopup {...popup} onClose={() => setPopup(null)} />}
    <section className="intro"><h1>Submitted event requests</h1><p className="muted">Signed in for this prototype as {currentCoordinator.name}. Preferred times are Singapore time (SGT).</p>
      <button className="button" onClick={() => { setLoading(true); setError(''); setRefresh((value) => value + 1) }}>Refresh requests</button></section>
    {loading ? <p role="status">Loading submitted requests…</p> : error ? <p role="alert">{error}</p> :
      events.length === 0 ? <p>No submitted event requests yet.</p> :
      events.map((event) => <article key={event.id} className="panel event-card">
        <header className="event-card-header"><div><p className="eyebrow">EVENT REQUEST</p><h2>{event.eventName}</h2></div><StatusBadge status={event.status} /></header>
        <p className="event-card-submitted">Submitted {event.submittedAt ? new Date(event.submittedAt).toLocaleString('en-SG', { timeZone: 'Asia/Singapore' }) + ' SGT' : 'Not recorded'}</p>
        <dl className="event-details">{[
          ['Description', event.description], ['Purpose', event.purpose],
          ['Preferred start', event.preferredStartDate.replace('T', ' ')],
          ['Preferred end', event.preferredEndDate.replace('T', ' ')],
          ['Expected attendance', event.expectedAttendance],
          ['Venue requirements', event.venueRequirements], ['Accessibility needs', event.accessibilityNeeds],
          ['Equipment requirements', event.equipmentRequirements], ['Registration needs', event.registrationNeeds],
        ].map(([label, value]) => <div className="event-detail" key={label}><dt>{label}</dt><dd>{value || 'Not specified'}</dd></div>)}</dl>

        {event.coordinatorId
          ? <div className="event-card-actions">
              <p className="muted">Assigned to {coordinators.find((coordinator) => coordinator.user_id === event.coordinatorId)?.username || event.coordinatorId}.</p>
              <button className="button secondary" onClick={() => {
                const candidates = availableReassignmentCoordinators(event)
                const fallbackCoordinatorId = candidates[0]?.user_id || ''
                setSelectedCoordinator((current) => ({ ...current, [event.id]: fallbackCoordinatorId }))
                setReassigning((current) => ({ ...current, [event.id]: true }))
              }}>Reassign Coordinator</button>

              {reassigning[event.id] && <div className="assignment-picker">
                <label htmlFor={`reassign-coordinator-${event.id}`}>New coordinator</label>
                <select id={`reassign-coordinator-${event.id}`} value={selectedCoordinator[event.id] || availableReassignmentCoordinators(event)[0]?.user_id || ''} onChange={(change) => setSelectedCoordinator((current) => ({ ...current, [event.id]: change.target.value }))}>
                  {availableReassignmentCoordinators(event).map((coordinator) => <option key={coordinator.user_id} value={coordinator.user_id}>{coordinator.username} · {coordinator.email}</option>)}
                </select>
                <button className="button approve" disabled={assigningId === event.id} onClick={() => assign(event)}>{assigningId === event.id ? 'Reassigning…' : 'Confirm Reassignment'}</button>
                {assignmentError[event.id] && <p className="assignment-error" role="alert">{assignmentError[event.id]}</p>}
              </div>}

              {event.coordinatorId === currentCoordinator.id && <div className="table-actions">
                <button className="button approve" disabled={decisionId === event.id} onClick={() => approve(event)}>{decisionId === event.id ? 'Processing…' : 'Approve Request'}</button>
                <button className="button reject" disabled={decisionId === event.id} onClick={() => { setRejecting(event); setReason('') }}>Reject Request</button>
              </div>}
            </div>
          : <div className="event-card-actions">
              <button className="button primary" onClick={() => setSelectedCoordinator((current) => ({ ...current, [event.id]: current[event.id] || coordinators[0]?.user_id || '' }))}>Assign Coordinator</button>
              {selectedCoordinator[event.id] && <div className="assignment-picker">
                <label htmlFor={`coordinator-${event.id}`}>Coordinator</label>
                <select id={`coordinator-${event.id}`} value={selectedCoordinator[event.id]} onChange={(change) => setSelectedCoordinator((current) => ({ ...current, [event.id]: change.target.value }))}>
                  {coordinators.map((coordinator) => <option key={coordinator.user_id} value={coordinator.user_id}>{coordinator.username} · {coordinator.email}</option>)}
                </select>
                <button className="button approve" disabled={assigningId === event.id} onClick={() => assign(event)}>{assigningId === event.id ? 'Assigning…' : 'Confirm Assignment'}</button>
                {assignmentError[event.id] && <p className="assignment-error" role="alert">{assignmentError[event.id]}</p>}
              </div>}
            </div>}
      </article>)}
    {rejecting && <RejectionDialog eventName={rejecting.eventName} reason={reason} submitting={decisionId === rejecting.id} onReasonChange={setReason} onCancel={() => { setRejecting(null); setReason('') }} onConfirm={reject} />}
  </div>
}

