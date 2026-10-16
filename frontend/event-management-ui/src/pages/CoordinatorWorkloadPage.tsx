import { useEffect, useState } from 'react'
import type { Role } from '../types'
import { isLead } from '../roles'
import { assignmentApi } from '../features/event/submission'
import type { Coordinator, SubmittedEvent } from '../features/event/submission'
import { formatDateTime } from '../features/event/formatDates'
import { RoleWarning, StatusBadge } from '../components/FormControls'
import { RefreshIcon } from '../components/Icon'
import { Spinner } from '../components/Loading'

interface CoordinatorWorkload extends Coordinator {
  events: SubmittedEvent[]
}

// The Event Coordinator Lead's read-only view of who is working on what:
// every coordinator with their active events (Confirmed, Rejected and
// Cancelled are left out by event-service), plus the events nobody has been
// assigned yet. Nothing here edits an event — reassignment stays on the
// event's detail page. Coordinator-assignment-service enforces the Lead-only
// rule; the role gate here just avoids a request that would 403.
export function CoordinatorWorkloadPage({ role, currentUserId, resolveUserName, onViewDetails }: { role: Role; currentUserId?: string; resolveUserName?: (userId: string | null | undefined) => string | null; onViewDetails: (id: string) => void }) {
  const [coordinators, setCoordinators] = useState<CoordinatorWorkload[]>([])
  const [unassigned, setUnassigned] = useState<SubmittedEvent[]>([])
  const [otherAssigned, setOtherAssigned] = useState<SubmittedEvent[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    if (!isLead(role) || !currentUserId) return
    let active = true
    const params = new URLSearchParams({ actingUserId: currentUserId })
    assignmentApi(`/workload?${params.toString()}`).then((body) => {
      if (!active) return
      setCoordinators(body.coordinators)
      setUnassigned(body.unassigned)
      setOtherAssigned(body.otherAssigned ?? [])
    }).catch((cause: Error) => {
      if (active) setError(cause.message)
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [role, currentUserId, refresh])

  if (!isLead(role)) return <RoleWarning>Coordinator workload is visible only to the Event Coordinator Lead.</RoleWarning>

  const eventTable = (events: SubmittedEvent[], label: string) => events.length === 0
    ? <p className="muted">No active events.</p>
    : <div className="table-scroll"><table aria-label={label}>
      <thead><tr><th>Event</th><th>Organiser</th><th>Date/time</th><th>Status</th></tr></thead>
      <tbody>{events.map((event) => <tr key={event.id}>
        <td><strong>{event.eventName}</strong><button className="button small" onClick={() => onViewDetails(event.id)}>View details</button></td>
        <td>{resolveUserName?.(event.organiserId) ?? 'Unknown organiser'}</td>
        <td>{formatDateTime(event.preferredStartDate)} – {formatDateTime(event.preferredEndDate)}</td>
        <td><StatusBadge status={event.status} /></td>
      </tr>)}</tbody>
    </table></div>

  return <div className="page-stack">
    <section className="intro"><h1>Coordinator workload</h1><p className="muted">Active events by coordinator. Confirmed, rejected and cancelled events are not shown. Times are Singapore time (SGT).</p>
      <button className="button" onClick={() => { setLoading(true); setError(''); setRefresh((value) => value + 1) }}><RefreshIcon size={14} /> Refresh</button></section>
    {loading ? <p className="muted"><Spinner size={12} /> Loading workload…</p> : error ? <p className="field-error" role="alert">{error}</p> : <>
      <section className="panel table-panel workload-panel" aria-labelledby="workload-unassigned">
        <header className="workload-header"><h2 id="workload-unassigned">Unassigned</h2><StatusBadge status="Unassigned" /><span className="muted">{countLabel(unassigned.length)}</span></header>
        {eventTable(unassigned, 'Unassigned events')}
      </section>
      {coordinators.map((coordinator) => <section key={coordinator.user_id} className="panel table-panel workload-panel" aria-labelledby={`workload-${coordinator.user_id}`}>
        <header className="workload-header">
          <h2 id={`workload-${coordinator.user_id}`}>{coordinator.username}{isLead(coordinator.role as Role) && ' (Lead)'}</h2>
          <span className="muted">{coordinator.email} · {countLabel(coordinator.events.length)}</span>
        </header>
        {eventTable(coordinator.events, `${coordinator.username}'s events`)}
      </section>)}
      {otherAssigned.length > 0 && <section className="panel table-panel workload-panel" aria-labelledby="workload-other">
        <header className="workload-header"><h2 id="workload-other">Assigned to someone who is no longer a coordinator</h2><span className="muted">{countLabel(otherAssigned.length)}</span></header>
        {eventTable(otherAssigned, 'Events assigned to a former coordinator')}
      </section>}
    </>}
  </div>
}

function countLabel(count: number) {
  return `${count} active event${count === 1 ? '' : 's'}`
}
