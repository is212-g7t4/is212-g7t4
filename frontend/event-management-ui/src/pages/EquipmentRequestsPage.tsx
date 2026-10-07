import { useCallback, useEffect, useState } from 'react'
import type { Role, User } from '../types'
import { REQUEST_STATUSES, fetchEventReservations, reviewAllEventEquipmentRequests, reviewEquipmentRequest } from '../features/equipment/requests'
import type { EquipmentRequestStatus, EventReservation, ReviewedRequest } from '../features/equipment/requests'
import { RoleWarning, StatusBadge } from '../components/FormControls'
import { EventCardSkeletonList, Spinner } from '../components/Loading'
import { RefreshIcon } from '../components/Icon'

type StatusFilter = EquipmentRequestStatus | 'All'

export const EQUIPMENT_REQUESTS_ACCESS_NOTICE = 'Equipment requests are visible to Technical Support staff.'
const INSUFFICIENT_HINT = 'Not enough stock for this window. Reject it, or wait for stock to free up.'

export function EquipmentRequestsPage({ role, user }: { role: Role; user: User | null }) {
  const [events, setEvents] = useState<EventReservation[]>([])
  const [filter, setFilter] = useState<StatusFilter>('Pending')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [actionError, setActionError] = useState('')
  const [reviewingId, setReviewingId] = useState<string | null>(null)

  const allowed = role === 'Technical Support' && user !== null

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

  const review = async (id: string, status: 'Approved' | 'Rejected') => {
    setReviewingId(id)
    setActionError('')
    try {
      applyDecisions([await reviewEquipmentRequest(id, status, user)])
    } catch (cause) {
      setActionError((cause as Error).message)
    } finally {
      setReviewingId(null)
    }
  }

  const reviewAll = async (eventId: string, status: 'Approved' | 'Rejected') => {
    setReviewingId(`all:${eventId}`)
    setActionError('')
    try {
      applyDecisions(await reviewAllEventEquipmentRequests(eventId, status, user))
    } catch (cause) {
      setActionError((cause as Error).message)
    } finally {
      setReviewingId(null)
    }
  }

  return <div className="page-stack">
    <section className="intro">
      <h1>Equipment requests</h1>
      <p className="muted">Review the equipment each event has asked for and approve or reject it. Event Coordinators see the new status straight away.</p>
      <div className="table-actions toolbar">
        <label className="field">
          <span>Show</span>
          <select value={filter} onChange={(event) => { setLoading(true); setFilter(event.target.value as StatusFilter) }} aria-label="Filter by status">
            <option value="All">All requests</option>
            {REQUEST_STATUSES.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <button className="button small" onClick={() => { setLoading(true); void load(filter, user) }}><RefreshIcon size={14} /> Refresh requests</button>
      </div>
      {actionError && <p className="field-error" role="alert">{actionError}</p>}
    </section>

    {loading ? <EventCardSkeletonList /> : error ? <p className="field-error" role="alert">{error}</p> :
      events.length === 0 ? <p>No equipment requests found.</p> :
      events.map(({ eventId, eventName, requests: items }) => {
        // Availability and actions only matter while a decision is still open.
        const pendingItems = items.filter((request) => request.status === 'Pending')
        const showStock = pendingItems.length > 0
        const anyInsufficient = pendingItems.some((request) => request.availability?.isInsufficient)
        const widths = showStock ? [27, 13, 12, 14, 19, 15] : [29, 16, 15, 40]
        return <article key={eventId} className="panel event-card">
          <header className="event-card-header">
            <h2>{eventName}</h2>
          </header>
          <div className="table-scroll">
            <table className="equipment-request-table">
              <colgroup>{widths.map((width, index) => <col key={index} style={{ width: `${width}%` }} />)}</colgroup>
              <thead><tr><th>Equipment</th><th>Type</th><th>Requested</th>{showStock && <th>Available</th>}<th>Requirements</th>{showStock && <th>Action</th>}</tr></thead>
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
                      {insufficient && <span className="status-badge rejected">Insufficient</span>}
                    </div>}</td>}
                    <td>{request.technicalRequirements || <span className="muted">None</span>}</td>
                    {showStock && <td>{request.status === 'Pending'
                      ? <div className="table-actions">
                        <button className="button small approve" disabled={busy || insufficient} title={insufficient ? INSUFFICIENT_HINT : undefined} onClick={() => review(request.id, 'Approved')}>{busy && <Spinner size={12} />}Approve</button>
                        <button className="button small reject" disabled={busy} onClick={() => review(request.id, 'Rejected')}>Reject</button>
                      </div>
                      : <span className="muted">Reviewed</span>}</td>}
                  </tr>
                })}
              </tbody>
            </table>
          </div>
          {showStock && <footer className="equipment-request-bulk-actions">
            <button className="button small approve" disabled={reviewingId !== null || anyInsufficient} title={anyInsufficient ? INSUFFICIENT_HINT : undefined} onClick={() => reviewAll(eventId, 'Approved')}>
              {reviewingId === `all:${eventId}` && <Spinner size={12} />}Approve All
            </button>
            <button className="button small reject" disabled={reviewingId !== null} onClick={() => reviewAll(eventId, 'Rejected')}>
              Reject All
            </button>
          </footer>}
        </article>
      })}
  </div>
}
