import { useEffect, useRef } from 'react'
import { AlertIcon } from '../../components/Icon'
import { NOTES_LIMIT } from './safetyCheck'

/**
 * SCRUM-151 AC3: rejecting needs a reason, and the officer must confirm
 * before it is saved. Both live in this dialog, so the destructive decision
 * can't be mistaken for the approve form behind it.
 *
 * Deliberately separate from `components/RejectionDialog` (an Event
 * Coordinator rejecting an event *request*): same visual language, different
 * consequence and copy.
 */
export function SafetyRejectDialog({ eventName, reason, submitting, onReasonChange, onCancel, onConfirm }: {
  eventName: string
  reason: string
  submitting: boolean
  onReasonChange: (value: string) => void
  onCancel: () => void
  onConfirm: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const element = dialog.current!
    element.showModal()
    return () => element.close()
  }, [])

  return <dialog ref={dialog} className="rejection-dialog" aria-labelledby="safety-reject-title" onCancel={(event) => { event.preventDefault(); onCancel() }}>
    <div className="rejection-dialog-header">
      <span className="rejection-icon"><AlertIcon size={18} /></span>
      <h2 id="safety-reject-title">Reject and cancel this event?</h2>
    </div>
    <p className="rejection-dialog-copy">
      Rejecting the safety arrangement cancels <strong>{eventName}</strong> for good. Its venue
      bookings are released so they stop blocking other events, and it can't be resubmitted for a
      safety check. This can't be undone.
    </p>
    <label className="rejection-field" htmlFor="safety-reject-reason">Reason for rejection <span>Required</span>
      <textarea id="safety-reject-reason" value={reason} onChange={(change) => onReasonChange(change.target.value)} placeholder="Explain what makes this safety arrangement unsafe." autoFocus maxLength={NOTES_LIMIT} />
      <small>{reason.length}/{NOTES_LIMIT} characters</small>
    </label>
    <div className="rejection-dialog-actions">
      <button className="button secondary" type="button" disabled={submitting} onClick={onCancel}>Cancel</button>
      <button className="button reject" type="button" disabled={!reason.trim() || submitting} onClick={onConfirm}>
        {submitting ? 'Rejecting…' : 'Confirm rejection'}
      </button>
    </div>
  </dialog>
}
