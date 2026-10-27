import { useEffect, useState } from 'react'
import type { Role } from '../types'
import { isLead } from '../roles'
import { assignmentApi } from '../features/event/submission'
import type { Coordinator, SubmittedEvent } from '../features/event/submission'
import { formatDateTime } from '../features/event/formatDates'
import { RoleWarning } from '../components/FormControls'
import { RefreshIcon } from '../components/Icon'
import { Spinner } from '../components/Loading'

// The Event Coordinator Lead's assignment worklist: unassigned Submitted
// requests plus assigned Under Review requests. Coordinator-assignment-service
// enforces the Lead-only rule; this role gate avoids a request that would 403.
export function UnassignedQueuePage({ role, currentUserId, resolveUserName, onViewDetails }: { role: Role; currentUserId?: string; resolveUserName?: (userId: string | null | undefined) => string | null; onViewDetails: (id: string) => void }) {
  const [events, setEvents] = useState<SubmittedEvent[]>([])
  const [coordinators, setCoordinators] = useState<Coordinator[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)
  const [selectedCoordinator, setSelectedCoordinator] = useState<Record<string, string>>({})
  const [assigningId, setAssigningId] = useState<string | null>(null)
  const [assignmentError, setAssignmentError] = useState<Record<string, string>>({})
  const [notice, setNotice] = useState('')

  useEffect(() => {
    if (!isLead(role) || !currentUserId) return
    let active = true
    const params = new URLSearchParams({ actingUserId: currentUserId })
    Promise.all([assignmentApi(`/queue?${params.toString()}`), assignmentApi('/coordinators')]).then(([queueBody, coordinatorBody]) => {
      if (!active) return
      setEvents(queueBody.events)
      setCoordinators(coordinatorBody.coordinators)
    }).catch((cause: Error) => {
      if (active) setError(cause.message)
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [role, currentUserId, refresh])

  const assign = async (event: SubmittedEvent) => {
    const coordinatorId = selectedCoordinator[event.id]
    if (!coordinatorId) {
      setAssignmentError((current) => ({ ...current, [event.id]: 'Choose a coordinator before assigning.' }))
      return
    }

    setAssigningId(event.id)
    setAssignmentError((current) => ({ ...current, [event.id]: '' }))

    try {
      const updated = await assignmentApi(`/events/${event.id}/assign-coordinator/${coordinatorId}`, 'POST', { actingUserId: currentUserId ?? '' })
      setEvents((current) => current.map((item) => item.id === event.id ? {
        ...item,
        ...updated,
        coordinatorId: updated.coordinatorId ?? updated.assignedCoordinatorId ?? coordinatorId,
      } : item))
      setSelectedCoordinator((current) => ({ ...current, [event.id]: '' }))
      const coordinatorName = coordinators.find((coordinator) => coordinator.user_id === coordinatorId)?.username ?? 'the coordinator'
      setNotice(`${event.eventName} was ${event.coordinatorId ? 'reassigned' : 'assigned'} to ${coordinatorName}.`)
    } catch (cause) {
      setAssignmentError((current) => ({
        ...current,
        [event.id]: cause instanceof Error ? cause.message : 'Unable to assign the coordinator.',
      }))
    } finally {
      setAssigningId(null)
    }
  }

  if (!isLead(role)) return <RoleWarning>Coordinator assignments are visible only to the Event Coordinator Lead.</RoleWarning>

  return <div className="page-stack">
    <section className="intro"><h1>Coordinator assignments</h1><p className="muted">Submitted event requests and their current assignment status, oldest first. Times are Singapore time (SGT).</p>
      <button className="button" onClick={() => { setLoading(true); setError(''); setNotice(''); setRefresh((value) => value + 1) }}><RefreshIcon size={14} /> Refresh assignments</button></section>
    {notice && <p className="notice success" role="status">{notice}</p>}
    {loading ? <p className="muted"><Spinner size={12} /> Loading assignments…</p> : error ? <p className="field-error" role="alert">{error}</p> :
      events.length === 0 ? <p>No submitted event requests yet.</p> :
      <section className="panel table-panel"><div className="table-scroll"><table>
        <thead><tr><th>Event</th><th>Event Organiser</th><th>Proposed date/time</th><th>Assignment status</th><th>Coordinator</th><th>Assign / reassign</th></tr></thead>
        <tbody>{events.map((event) => <tr key={event.id}>
          <td><strong>{event.eventName}</strong><button className="button small" onClick={() => onViewDetails(event.id)}>View details</button></td>
          <td>{resolveUserName?.(event.organiserId) ?? 'Unknown organiser'}</td>
          <td>{formatDateTime(event.preferredStartDate)} – {formatDateTime(event.preferredEndDate)}</td>
          <td><span className={`status-badge ${event.coordinatorId ? 'approved' : 'pending'}`}>{event.coordinatorId ? 'Assigned' : 'Unassigned'}</span></td>
          <td>{event.coordinatorId ? (coordinators.find((coordinator) => coordinator.user_id === event.coordinatorId)?.username ?? resolveUserName?.(event.coordinatorId) ?? 'Unknown coordinator') : '—'}</td>
          <td><div className="assignment-picker">
            <label htmlFor={`queue-coordinator-${event.id}`}>{event.coordinatorId ? 'New coordinator' : 'Coordinator'}</label>
            <select id={`queue-coordinator-${event.id}`} value={selectedCoordinator[event.id] ?? ''} onChange={(change) => setSelectedCoordinator((current) => ({ ...current, [event.id]: change.target.value }))}>
              <option value="">{event.coordinatorId ? 'Choose a different coordinator' : 'Choose a coordinator'}</option>
              {coordinators.map((coordinator) => <option key={coordinator.user_id} value={coordinator.user_id}>{coordinator.username} · {coordinator.email}{coordinator.user_id === event.coordinatorId ? ' (current)' : ''}</option>)}
            </select>
            <button className="button approve" disabled={assigningId === event.id} onClick={() => assign(event)}>{assigningId === event.id && <Spinner size={12} />}{assigningId === event.id ? 'Saving…' : event.coordinatorId ? 'Reassign' : 'Assign'}</button>
            {assignmentError[event.id] && <p className="assignment-error" role="alert">{assignmentError[event.id]}</p>}
          </div></td>
        </tr>)}</tbody>
      </table></div></section>}
  </div>
}
