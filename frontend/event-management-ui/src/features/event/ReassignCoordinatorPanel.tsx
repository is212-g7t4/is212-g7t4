import { useEffect, useState } from 'react'
import { assignmentApi } from './submission'
import type { Coordinator, SubmittedEvent } from './submission'
import { Spinner } from '../../components/Loading'
import { NO_CHANGE_MESSAGE } from './eventStatus'

/**
 * The Lead's one reassignment control, used on the event detail page and on
 * each Event requests card. Render it only for the Lead; Coordinator
 * Assignment Service rejects anyone else with 403.
 *
 * Pass `coordinators` when the page already has the list (Event requests
 * loads it once for every card); otherwise it is fetched on first open.
 */
export function ReassignCoordinatorPanel({ event, leadId, coordinators: provided, onReassigned }: { event: SubmittedEvent; leadId: string; coordinators?: Coordinator[]; onReassigned: (updated: SubmittedEvent) => void }) {
  const [fetched, setFetched] = useState<Coordinator[]>([])
  const coordinators = provided ?? fetched
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    if (!open || provided || fetched.length) return
    let active = true
    assignmentApi('/coordinators').then((body) => {
      if (active) setFetched(body.coordinators)
    }).catch((cause: Error) => {
      if (active) setError(cause.message)
    })
    return () => { active = false }
  }, [open, provided, fetched.length])

  const confirm = async () => {
    setNotice('')
    if (!selected) {
      setError('Choose a coordinator before confirming.')
      return
    }
    if (selected === event.coordinatorId) {
      setError(NO_CHANGE_MESSAGE)
      return
    }
    setSaving(true)
    setError('')
    try {
      const updated = await assignmentApi(`/events/${event.id}/assign-coordinator/${selected}`, 'POST', { actingUserId: leadId })
      const name = coordinators.find((coordinator) => coordinator.user_id === selected)?.username ?? 'the new coordinator'
      setOpen(false)
      setSelected('')
      setNotice(`${event.eventName} was reassigned to ${name}.`)
      onReassigned(updated)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to reassign the coordinator.')
    } finally {
      setSaving(false)
    }
  }

  return <>
    {notice && <p className="notice success" role="status">{notice}</p>}
    {!open ? <button className="button secondary" onClick={() => { setOpen(true); setError(''); setNotice('') }}>Reassign Coordinator</button> :
      <div className="assignment-picker">
        <label htmlFor={`reassign-coordinator-${event.id}`}>New coordinator</label>
        <select id={`reassign-coordinator-${event.id}`} value={selected} onChange={(change) => { setSelected(change.target.value); setError('') }}>
          <option value="">Choose a coordinator</option>
          {coordinators.map((coordinator) => <option key={coordinator.user_id} value={coordinator.user_id}>
            {coordinator.username} · {coordinator.email}{coordinator.user_id === event.coordinatorId ? ' (current)' : ''}
          </option>)}
        </select>
        <button className="button approve" disabled={saving} onClick={confirm}>{saving && <Spinner size={12} />}{saving ? 'Reassigning…' : 'Confirm Reassignment'}</button>
        <button className="button" disabled={saving} onClick={() => { setOpen(false); setSelected(''); setError('') }}>Cancel</button>
      </div>}
    {error && <p className="assignment-error" role="alert">{error}</p>}
  </>
}
