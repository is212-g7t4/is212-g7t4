import { useEffect, useRef } from 'react'

export function RejectionDialog({ eventName, reason, submitting, onReasonChange, onCancel, onConfirm }: {
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

  return <dialog ref={dialog} className="rejection-dialog" aria-labelledby="rejection-dialog-title" onCancel={(event) => { event.preventDefault(); onCancel() }}>
    <div className="rejection-dialog-header">
      <span className="rejection-icon" aria-hidden="true">!</span>
      <div><p className="eyebrow">Decision required</p><h2 id="rejection-dialog-title">Reject event request?</h2></div>
    </div>
    <p className="rejection-dialog-copy">You are rejecting <strong>{eventName}</strong>. Add a clear reason so the requester understands what needs to change.</p>
    <label className="rejection-field" htmlFor="rejection-reason">Reason for rejection <span>Required</span>
      <textarea id="rejection-reason" value={reason} onChange={(change) => onReasonChange(change.target.value)} placeholder="Explain why this request cannot proceed as submitted." autoFocus maxLength={500} />
      <small>{reason.length}/500 characters</small>
    </label>
    <div className="rejection-dialog-actions">
      <button className="button secondary" type="button" onClick={onCancel}>Cancel</button>
      <button className="button reject" type="button" disabled={!reason.trim() || submitting} onClick={onConfirm}>{submitting ? 'Rejecting...' : 'Confirm rejection'}</button>
    </div>
  </dialog>
}