import { useEffect, useState } from 'react'
import type { Role } from '../types'
import { eventApi } from '../features/event/submission'
import type { SubmittedEvent } from '../features/event/submission'
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
  const [popup, setPopup] = useState<{ title: string; messages: string[] } | null>(null)
  const currentCoordinator = {
    ...users[0],
    id: import.meta.env.VITE_CURRENT_COORDINATOR_ID || users[0].id,
    name: import.meta.env.VITE_CURRENT_COORDINATOR_NAME || users[0].name,
  }
  useEffect(() => {
    if (role !== 'Event Coordinator') return
    let active = true
    eventApi('/events/submitted').then((body) => {
      if (active) setEvents(body.events)
    }).catch((cause: Error) => {
      if (active) setError(cause.message)
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [role, refresh])
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
  if (role !== 'Event Coordinator') return <p className="role-warning">Submitted event requests are visible to Event Coordinators.</p>
  return <div className="page-stack">
    {popup && <SubmissionPopup {...popup} onClose={() => setPopup(null)} />}
    <section className="intro"><h1>Submitted event requests</h1><p className="muted">Signed in for this prototype as {currentCoordinator.name}. Preferred times are Singapore time (SGT).</p>
      <button className="button" onClick={() => { setLoading(true); setError(''); setRefresh((value) => value + 1) }}>Refresh requests</button></section>
    {loading ? <p role="status">Loading submitted requests…</p> : error ? <p role="alert">{error}</p> :
      events.length === 0 ? <p>No submitted event requests yet.</p> :
      events.map((event) => <article key={event.id} className="panel">
        <h2>{event.eventName}</h2><StatusBadge status={event.status} />
        <p>Submitted: {event.submittedAt ? new Date(event.submittedAt).toLocaleString('en-SG', { timeZone: 'Asia/Singapore' }) + ' SGT' : 'Not recorded'}</p>
        <dl>{[
          ['Description', event.description], ['Purpose', event.purpose],
          ['Preferred start', event.preferredStartDate.replace('T', ' ')],
          ['Preferred end', event.preferredEndDate.replace('T', ' ')],
          ['Expected attendance', event.expectedAttendance],
          ['Venue requirements', event.venueRequirements], ['Accessibility needs', event.accessibilityNeeds],
          ['Equipment requirements', event.equipmentRequirements], ['Registration needs', event.registrationNeeds],
        ].map(([label, value]) => <div key={label}><dt><strong>{label}</strong></dt><dd style={{ whiteSpace: 'pre-wrap' }}>{value || 'Not specified'}</dd></div>)}</dl>
        {event.coordinatorId === currentCoordinator.id
          ? <div className="table-actions"><button className="button approve" disabled={decisionId === event.id} onClick={() => approve(event)}>{decisionId === event.id ? 'Processing…' : 'Approve Request'}</button><button className="button reject" disabled={decisionId === event.id} onClick={() => { setRejecting(event); setReason('') }}>Reject Request</button></div>
          : <p className="muted">Actions are unavailable because this request is not assigned to {currentCoordinator.name}.</p>}
      </article>)}
    {rejecting && <RejectionDialog eventName={rejecting.eventName} reason={reason} submitting={decisionId === rejecting.id} onReasonChange={setReason} onCancel={() => { setRejecting(null); setReason('') }} onConfirm={reject} />}
  </div>
}

