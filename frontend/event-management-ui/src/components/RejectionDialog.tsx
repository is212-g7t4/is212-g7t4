import { useEffect, useRef } from 'react'
import { AlertIcon } from './Icon'

export function RejectionDialog({ eventName, reason, submitting, onReasonChange, onCancel, onConfirm, title = 'Reject event request?', error }: {
  eventName: string
  reason: string
  submitting: boolean
  onReasonChange: (value: string) => void
  onCancel: () => void
  onConfirm: () => void
  title?: string
  error?: string
}) {
  const dialog = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const element = dialog.current!
    element.showModal()
    return () => element.close()
  }, [])

  return <dialog ref={dialog} className="rejection-dialog" aria-labelledby="rejection-dialog-title" onCancel={(event) => { event.preventDefault(); onCancel() }}>
    <div className="rejection-dialog-header">
      <span className="rejection-icon"><AlertIcon size={18} /></span>
      <h2 id="rejection-dialog-title">{title}</h2>
    </div>
    <p className="rejection-dialog-copy">You are rejecting <strong>{eventName}</strong>. Add a clear reason so the requester understands what needs to change.</p>
    <label className="rejection-field" htmlFor="rejection-reason">Reason for rejection <span>Required</span>
      <textarea id="rejection-reason" value={reason} onChange={(change) => onReasonChange(change.target.value)} placeholder="Explain why this request cannot proceed as submitted." autoFocus maxLength={500} disabled={submitting} />
      <small>{reason.length}/500 characters</small>
    </label>
    {error && <p className="field-error" role="alert">{error}</p>}
    <div className="rejection-dialog-actions">
      <button className="button secondary" type="button" disabled={submitting} onClick={onCancel}>Cancel</button>
      <button className="button reject" type="button" disabled={!reason.trim() || submitting} onClick={onConfirm}>{submitting ? 'Rejecting...' : 'Confirm rejection'}</button>
    </div>
  </dialog>
}