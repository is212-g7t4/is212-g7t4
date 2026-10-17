import { useCallback, useEffect, useState } from 'react'
import type { Role, User } from '../types'
import { formatSchedule } from '../features/event/dateFormat'
import { REQUEST_STATUSES, fetchEventReservations, reviewAllEventEquipmentRequests, reviewEquipmentRequest } from '../features/equipment/requests'
import type { EquipmentRequestStatus, EventReservation, ReviewedRequest } from '../features/equipment/requests'
import { RoleWarning, StatusBadge } from '../components/FormControls'
import { EventCardSkeletonList, Spinner } from '../components/Loading'
import { RefreshIcon, PlusIcon } from '../components/Icon'
import { isCoordinator } from '../roles'
import { RejectionDialog } from '../components/RejectionDialog'

type StatusFilter = EquipmentRequestStatus | 'All'

export const EQUIPMENT_REQUESTS_ACCESS_NOTICE = 'Equipment requests are visible to Technical Support and assigned Event Coordinators.'
const INSUFFICIENT_HINT = 'Not enough stock for this window. Reject it, or wait for stock to free up.'

export function EquipmentRequestsPage({ role, user, resolveUserName, onCreate }: {
  role: Role
  user: User | null
  resolveUserName?: (userId: string | null | undefined) => string | null
  onCreate?: () => void
}) {
  const [events, setEvents] = useState<EventReservation[]>([])
  const [filter, setFilter] = useState<StatusFilter>('All')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [actionError, setActionError] = useState('')
  const [reviewingId, setReviewingId] = useState<string | null>(null)
  const [rejection, setRejection] = useState<{ id: string; name: string; bulk: boolean } | null>(null)
  const [rejectionReason, setRejectionReason] = useState('')

  const allowed = (role === 'Technical Support' || isCoordinator(role)) && user !== null
  const canReview = role === 'Technical Support'

  const load = useCallback((activeFilter: StatusFilter, reviewer: User) => {
    return fetchEventReservations(reviewer, activeFilter === 'All' ? undefined : activeFilter)
      .then((list) => {
        setEvents(list)
        setError('')
      }).catch((cause: Error) => setError(cause.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (allowed) void load(filter, user)
  }, [allowed, filter, load, user])

  if (!allowed) return <RoleWarning>{EQUIPMENT_REQUESTS_ACCESS_NOTICE}</RoleWarning>

  const applyDecisions = (updated: ReviewedRequest[]) => {
    const byId = new Map(updated.map((item) => [item.id, item]))
    // A decided request leaves the Pending view; otherwise update it in place.
    setEvents((current) => current
      .map((event) => ({
        ...event,
        requests: filter === 'Pending'
          ? event.requests.filter((item) => !byId.has(item.id))
          : event.requests.map((item) => ({ ...item, ...byId.get(item.id) })),
      }))
      .filter((event) => event.requests.length > 0))
  }

  const review = async (id: string, status: 'Approved' | 'Rejected', reason?: string) => {
    setReviewingId(id)
    setActionError('')
    try {
      const updated = reason === undefined
        ? await reviewEquipmentRequest(id, status, user)
        : await reviewEquipmentRequest(id, status, user, reason)
      applyDecisions([updated])
      setRejection(null)
    } catch (cause) {
      setActionError((cause as Error).message)
    } finally {
      setReviewingId(null)
    }
  }

  const reviewAll = async (eventId: string, status: 'Approved' | 'Rejected', reason?: string) => {
    setReviewingId(`all:${eventId}`)
    setActionError('')
    try {
      const updated = reason === undefined
        ? await reviewAllEventEquipmentRequests(eventId, status, user)
        : await reviewAllEventEquipmentRequests(eventId, status, user, reason)
      applyDecisions(updated)
      setRejection(null)
    } catch (cause) {
      setActionError((cause as Error).message)
    } finally {
      setReviewingId(null)
    }
  }

  const openRejection = (id: string, name: string, bulk: boolean) => {
    setActionError('')
    setRejectionReason('')
    setRejection({ id, name, bulk })
  }

  return <div className="page-stack">
    {rejection && <RejectionDialog
      title={rejection.bulk ? 'Reject all equipment requests?' : 'Reject equipment request?'}
      eventName={rejection.name}
      reason={rejectionReason}
      submitting={reviewingId !== null}
      error={actionError}
      onReasonChange={setRejectionReason}
      onCancel={() => { if (reviewingId === null) { setRejection(null); setActionError('') } }}
      onConfirm={() => {
        if (!rejectionReason.trim() || reviewingId !== null) return
        if (rejection.bulk) void reviewAll(rejection.id, 'Rejected', rejectionReason.trim())
        else void review(rejection.id, 'Rejected', rejectionReason.trim())
      }}
    />}
    <section className="intro">
      <h1>Equipment requests</h1>
      <p className="muted">{canReview ? 'Review the equipment each event has asked for and approve or reject it. Event Coordinators see the new status straight away.' : 'Equipment requests for events currently assigned to you.'}</p>
      <div className="table-actions toolbar">
        <label className="field">
          <span>Show</span>
          <select value={filter} onChange={(event) => { setLoading(true); setFilter(event.target.value as StatusFilter) }} aria-label="Filter by status">
            <option value="All">All requests</option>
            {REQUEST_STATUSES.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <button className="button small" onClick={() => { setLoading(true); void load(filter, user) }}><RefreshIcon size={14} /> Refresh requests</button>
        {isCoordinator(role) && onCreate && <button className="button small primary" onClick={onCreate}><PlusIcon size={14} /> New request</button>}
      </div>
      {actionError && !rejection && <p className="field-error" role="alert">{actionError}</p>}
    </section>

    {loading ? <EventCardSkeletonList /> : error ? <p className="field-error" role="alert">{error}</p> :
      events.length === 0 ? <p>No equipment requests found.</p> :
      events.map(({ eventId, eventName, eventStatus, startTime, endTime, coordinatorId, requests: items }) => {
        // Availability and actions only matter while a decision is still open.
        const pendingItems = items.filter((request) => request.status === 'Pending')
        const reviewStage = eventStatus === 'Under Review' || eventStatus === 'Safety Changes Requested'
        const showStock = pendingItems.length > 0 && (eventStatus === 'Submitted' || reviewStage)
        const showActions = showStock && canReview && reviewStage
        const showSafetyFeedback = canReview && eventStatus === 'Safety Changes Requested'
        const showRejectReason = items.some((request) => request.status === 'Rejected')
        const extendedTable = showSafetyFeedback || showRejectReason
        const anyInsufficient = pendingItems.some((request) => request.availability?.isInsufficient)
        const baseWidths = showStock
          ? showActions ? [27, 13, 12, 14, 19, 15] : [30, 15, 15, 18, 22]
          : [29, 16, 15, 40]
        const widths = extendedTable
          ? [...baseWidths.map((width) => width * 10), ...(showRejectReason ? [240] : []), ...(showSafetyFeedback ? [240] : [])]
          : baseWidths
        return <article key={eventId} className="panel event-card">
          <header className="event-card-header">
            <div className="event-card-title">
              <h2>{eventName}</h2>
              {eventStatus && <StatusBadge status={eventStatus} />}
              {startTime && endTime && <span className="event-card-date muted">{formatSchedule(startTime, endTime)}</span>}
            </div>
            <span className="equipment-request-coordinator">
              Coordinator: {resolveUserName?.(coordinatorId) ?? (coordinatorId ? 'Unknown' : 'Unassigned')}
            </span>
          </header>
          <div className="table-scroll" role="region" aria-label={`${eventName} equipment requests`} tabIndex={0}>
            <table className={`equipment-request-table${showSafetyFeedback ? ' with-safety-feedback' : ''}${showRejectReason ? ' with-reject-reason' : ''}`}>
              <colgroup>{widths.map((width, index) => <col key={index} style={{ width: `${width}${extendedTable ? 'px' : '%'}` }} />)}</colgroup>
              <thead><tr><th>Equipment</th><th>Type</th><th>Requested</th>{showStock && <th>Available</th>}<th>Requirements</th>{showActions && <th>Action</th>}{showRejectReason && <th>Reject Reason</th>}{showSafetyFeedback && <th>Safety change reason</th>}</tr></thead>
              <tbody>
                {items.map((request) => {
                  const insufficient = request.availability?.isInsufficient ?? false
                  const busy = reviewingId === request.id || reviewingId === `all:${eventId}`
                  return <tr key={request.id}>
                    <td><div className="equipment-request-item">
                      <span>{request.equipment?.description ?? 'Unknown equipment'}</span>
                      <StatusBadge status={request.status} />
                    </div></td>
                    <td>{request.equipment?.type ?? '—'}</td>
                    <td>{request.quantityRequested}</td>
                    {showStock && <td>{request.status !== 'Pending' ? <span className="muted">—</span> : <div className="equipment-request-item">
                      <span>{request.availability?.availableStock ?? '—'}</span>
                      {request.equipment?.status === 'Unavailable'
                        ? <span className="status-badge rejected">Unavailable</span>
                        : insufficient && <span className="status-badge rejected">Insufficient</span>}
                    </div>}</td>}
                    <td>{request.technicalRequirements || <span className="muted">None</span>}</td>
                    {showActions && <td>{request.status === 'Pending'
                      ? <div className="table-actions">
                        <button className="button small approve" disabled={busy || insufficient} title={insufficient ? INSUFFICIENT_HINT : undefined} onClick={() => review(request.id, 'Approved')}>{busy && <Spinner size={12} />}Approve</button>
                        <button className="button small reject" disabled={reviewingId !== null} onClick={() => openRejection(request.id, `${request.equipment?.description ?? 'Unknown equipment'} for ${eventName}`, false)}>Reject</button>
                      </div>
                      : <span className="muted">Reviewed</span>}</td>}
                    {showRejectReason && <td className="equipment-reject-reason">{request.status === 'Rejected' && request.rejectionReason
                      ? request.rejectionReason : <span className="muted">—</span>}</td>}
                    {showSafetyFeedback && <td>{request.safetyFeedback
                      ? <div className="equipment-safety-feedback">
                        {request.safetyFeedback.requestedChanges.map((change, index) => <p key={index}>{change}</p>)}
                        {request.safetyFeedback.reason && <p className="muted">Reason: {request.safetyFeedback.reason}</p>}
                      </div>
                      : <span className="muted">Not flagged</span>}</td>}
                  </tr>
                })}
              </tbody>
            </table>
          </div>
          {showActions && <footer className="equipment-request-bulk-actions">
            <button className="button small approve" disabled={reviewingId !== null || anyInsufficient} title={anyInsufficient ? INSUFFICIENT_HINT : undefined} onClick={() => reviewAll(eventId, 'Approved')}>
              {reviewingId === `all:${eventId}` && <Spinner size={12} />}Approve All
            </button>
            <button className="button small reject" disabled={reviewingId !== null} onClick={() => openRejection(eventId, `all Pending equipment requests for ${eventName}`, true)}>
              Reject All
            </button>
          </footer>}
        </article>
      })}
  </div>
}
