import { useEffect, useRef } from 'react'

export function ClarificationDialog({ eventName, message, submitting, error, onMessageChange, onCancel, onConfirm }: {
  eventName: string
  message: string
  submitting: boolean
  error?: string
  onMessageChange: (value: string) => void
  onCancel: () => void
  onConfirm: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const element = dialog.current!
    element.showModal()
    return () => element.close()
  }, [])

  return <dialog ref={dialog} className="rejection-dialog" aria-labelledby="clarification-dialog-title" onCancel={(event) => { event.preventDefault(); onCancel() }}>
    <div className="rejection-dialog-header">
      <h2 id="clarification-dialog-title">Request clarification</h2>
    </div>
    <p className="rejection-dialog-copy">Ask the Event Organiser a question about <strong>{eventName}</strong>. The submitted request itself will remain unchanged.</p>
    <label className="rejection-field" htmlFor="clarification-question">Question or message <span>Required</span>
      <textarea id="clarification-question" value={message} onChange={(change) => onMessageChange(change.target.value)} placeholder="Explain what information you need before deciding." autoFocus maxLength={1000} disabled={submitting} />
      <small>{message.length}/1000 characters</small>
    </label>
    {error && <p className="field-error" role="alert">{error}</p>}
    <div className="rejection-dialog-actions">
      <button className="button secondary" type="button" disabled={submitting} onClick={onCancel}>Cancel</button>
      <button className="button primary" type="button" disabled={!message.trim() || submitting} onClick={onConfirm}>{submitting ? 'Sending…' : 'Send request'}</button>
    </div>
  </dialog>
}
