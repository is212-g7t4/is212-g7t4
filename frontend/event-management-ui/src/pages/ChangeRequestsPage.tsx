import { useEffect, useState } from 'react'
import type { Role } from '../types'
import { isCoordinator } from '../roles'
import { FIELD_LABELS } from '../features/event/eventDetails'
import type { EditableField } from '../features/event/eventDetails'
import {
  CHANGE_REQUEST_FIELD_ORDER,
  ChangeRequestReviewError,
  decideChangeRequest,
  fetchPendingChangeRequests,
} from '../features/event/changeRequests'
import type { EventChangeRequest } from '../features/event/changeRequests'
import { RoleWarning, StatusBadge } from '../components/FormControls'
import { RejectionDialog } from '../components/RejectionDialog'
import { RefreshIcon } from '../components/Icon'
import { EventCardSkeletonList, Spinner } from '../components/Loading'

function displayValue(field: EditableField, value: string | undefined) {
  if (!value) return 'Not specified'
  if (field === 'preferredStartDate' || field === 'preferredEndDate') {
    const parsed = new Date(value)
    return Number.isNaN(parsed.getTime())
      ? value
      : parsed.toLocaleString('en-SG', { timeZone: 'Asia/Singapore' }) + ' SGT'
  }
  return value
}

export function ChangeRequestsPage({ role, coordinatorId, coordinatorName }: {
  role: Role
  coordinatorId?: string
  coordinatorName?: string
}) {
  const [requests, setRequests] = useState<EventChangeRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [processingId, setProcessingId] = useState<string | null>(null)
  const [rejecting, setRejecting] = useState<EventChangeRequest | null>(null)
  const [reason, setReason] = useState('')
  const [decisionError, setDecisionError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    if (!isCoordinator(role) || !coordinatorId) {
      setLoading(false)
      return
    }
    let active = true
    setError('')
    fetchPendingChangeRequests(coordinatorId)
      .then((items) => { if (active) setRequests(items) })
      .catch((cause: Error) => { if (active) setError(cause.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [role, coordinatorId, refresh])

  const decide = async (request: EventChangeRequest, decision: 'Approved' | 'Rejected', rejectionReason?: string) => {
    if (!coordinatorId) return
    setProcessingId(request.id)
    setDecisionError('')
    setNotice('')
    try {
      const result = await decideChangeRequest(request.id, coordinatorId, decision, rejectionReason)
      setRequests((current) => current.filter((item) => item.id !== request.id))
      setRejecting(null)
      setReason('')
      setNotice(`${request.event.eventName} change request ${result.status.toLowerCase()}.`)
    } catch (cause) {
      const failure = cause instanceof ChangeRequestReviewError ? cause : null
      const details = failure?.conflicts.map((conflict) => conflict.message).join(' ') || ''
      setDecisionError(`${cause instanceof Error ? cause.message : 'Unable to process the request.'}${details ? ` ${details}` : ''}`)
    } finally {
      setProcessingId(null)
    }
  }

  if (!isCoordinator(role)) {
    return <RoleWarning>Change requests are visible to Event Coordinators.</RoleWarning>
  }

  return <div className="page-stack">
    <section className="intro">
      <h1>Event change requests</h1>
      <p className="muted">Pending requests for events managed by {coordinatorName || 'the current coordinator'}.</p>
      <button className="button" onClick={() => { setLoading(true); setRefresh((value) => value + 1) }}><RefreshIcon size={14} /> Refresh requests</button>
    </section>
    {notice && <p role="status" className="notice success">{notice}</p>}
    {decisionError && !rejecting && <p role="alert" className="field-error">{decisionError}</p>}
    {loading ? <EventCardSkeletonList /> : error ? <p className="field-error" role="alert">{error}</p> :
      requests.length === 0 ? <p>No pending change requests.</p> :
      requests.map((change) => {
        const fields = CHANGE_REQUEST_FIELD_ORDER.filter((field) => field in change.proposedChanges)
        return <article key={change.id} className="panel event-card change-request-card">
          <header className="event-card-header">
            <div><h2>{change.event.eventName}</h2><p className="muted">Requested {new Date(change.requestedAt).toLocaleString('en-SG', { timeZone: 'Asia/Singapore' })} SGT</p></div>
            <StatusBadge status={change.status} />
          </header>
          <div className="change-request-body">
            <dl className="event-details">
              <div className="event-detail full"><dt>Reason for change</dt><dd>{change.reason}</dd></div>
            </dl>
            <div className="table-scroll">
              <table className="change-request-comparison">
                <thead><tr><th>Event detail</th><th>Original value</th><th>Proposed value</th></tr></thead>
                <tbody>{fields.map((field) => <tr key={field}>
                  <th scope="row">{FIELD_LABELS[field]}</th>
                  <td>{displayValue(field, change.event[field])}</td>
                  <td>{displayValue(field, change.proposedChanges[field])}</td>
                </tr>)}</tbody>
              </table>
            </div>
          </div>
          <div className="event-card-actions">
            <div className="table-actions">
              <button className="button approve" disabled={processingId === change.id} onClick={() => decide(change, 'Approved')}>
                {processingId === change.id && <Spinner size={12} />}{processingId === change.id ? 'Processing…' : 'Approve changes'}
              </button>
              <button className="button reject" disabled={processingId === change.id} onClick={() => { setRejecting(change); setReason(''); setDecisionError('') }}>Reject changes</button>
            </div>
          </div>
        </article>
      })}
    {rejecting && <RejectionDialog
      title="Reject change request?"
      eventName={rejecting.event.eventName}
      reason={reason}
      submitting={processingId === rejecting.id}
      error={decisionError}
      onReasonChange={setReason}
      onCancel={() => { setRejecting(null); setReason(''); setDecisionError('') }}
      onConfirm={() => decide(rejecting, 'Rejected', reason.trim())}
    />}
  </div>
}
