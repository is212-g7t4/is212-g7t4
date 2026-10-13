import { useState } from 'react'
import { NOTES_LIMIT, approveSafetyCheck } from './safetyCheck'

type Props = {
  eventId: string
  safetyOfficerId: string
  /** Called after a successful approval so the page reloads the event. */
  onApproved: () => void
}

/**
 * SCRUM-150: approve an event's Operational Safety Check.
 *
 * Rendered only for a Safety Officer while the event is 'Pending Safety
 * Check' — the page decides that (AC3, UI side). SCRUM-151 later adds Reject
 * and Request changes beside Approve.
 */
export function SafetyDecisionPanel({ eventId, safetyOfficerId, onApproved }: Props) {
  const [remarks, setRemarks] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [approving, setApproving] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const approve = async () => {
    if (approving) return
    setApproving(true)
    setError('')
    try {
      await approveSafetyCheck({
        eventId,
        safetyOfficerId,
        remarks: remarks.trim() || undefined,
      })
      setConfirming(false)
      setMessage('Approved. The event has moved to Confirmed.')
      onApproved()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to approve this safety check.')
    } finally {
      setApproving(false)
    }
  }

  return <div className="safety-decision">
    <h4>Operational Safety Check</h4>
    <div className="field">
      <label htmlFor="safety-decision-remarks">Remarks</label>
      <textarea
        id="safety-decision-remarks"
        value={remarks}
        maxLength={NOTES_LIMIT}
        onChange={(change) => { setRemarks(change.target.value); setMessage('') }}
        placeholder="Anything worth recording with this decision (optional)."
      />
      <span className="muted">{remarks.length} / {NOTES_LIMIT}</span>
    </div>

    {error && <p className="field-error" role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}

    {confirming ? <div className="safety-decision-confirm">
      <p>Approve this event's safety arrangements? It will move to Confirmed.</p>
      <button className="button primary" type="button" disabled={approving} onClick={approve}>
        {approving ? 'Approving…' : 'Yes, approve'}
      </button>{' '}
      <button className="button small" type="button" disabled={approving} onClick={() => setConfirming(false)}>
        Cancel
      </button>
    </div> : <button className="button primary" type="button" onClick={() => setConfirming(true)}>
      Approve
    </button>}
  </div>
}
