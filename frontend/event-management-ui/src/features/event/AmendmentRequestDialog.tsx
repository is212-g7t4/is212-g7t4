import { useEffect, useRef, useState } from 'react'
import { AMENDMENT_OPTIONS } from './eventDetails'
import type { EditableField } from './eventDetails'

// SCRUM-16 AC1/AC2: the assigned coordinator flags which details the Event
// Organiser must change and says why. Built like ClarificationDialog.
export function AmendmentRequestDialog({ eventName, submitting, error, onCancel, onConfirm }: {
  eventName: string
  submitting: boolean
  error?: string
  onCancel: () => void
  onConfirm: (fields: EditableField[], reason: string) => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [flagged, setFlagged] = useState<string[]>([])
  const [reason, setReason] = useState('')

  useEffect(() => {
    const element = dialog.current!
    element.showModal()
    return () => element.close()
  }, [])

  const toggle = (label: string) => setFlagged((current) =>
    current.includes(label) ? current.filter((item) => item !== label) : [...current, label])
  const fields = AMENDMENT_OPTIONS.filter((option) => flagged.includes(option.label)).flatMap((option) => option.fields)

  return <dialog ref={dialog} className="rejection-dialog" aria-labelledby="amendment-dialog-title" onCancel={(event) => { event.preventDefault(); onCancel() }}>
    <div className="rejection-dialog-header">
      <h2 id="amendment-dialog-title">Request amendment</h2>
    </div>
    <p className="rejection-dialog-copy">Send <strong>{eventName}</strong> back to the Event Organiser. They can change only the fields you flag; everything else stays as submitted.</p>
    <fieldset className="rejection-field amendment-fields" disabled={submitting}>
      <legend>Fields that need changes <span>Required</span></legend>
      {AMENDMENT_OPTIONS.map((option) => <label key={option.label}>
        <input type="checkbox" checked={flagged.includes(option.label)} onChange={() => toggle(option.label)} /> {option.label}
      </label>)}
    </fieldset>
    <label className="rejection-field" htmlFor="amendment-reason">Reason or details <span>Required</span>
      <textarea id="amendment-reason" value={reason} onChange={(change) => setReason(change.target.value)} placeholder="Explain what needs to change and why." maxLength={1000} disabled={submitting} />
      <small>{reason.length}/1000 characters</small>
    </label>
    {error && <p className="field-error" role="alert">{error}</p>}
    <div className="rejection-dialog-actions">
      <button className="button secondary" type="button" disabled={submitting} onClick={onCancel}>Cancel</button>
      <button className="button primary" type="button" disabled={fields.length === 0 || !reason.trim() || submitting} onClick={() => onConfirm(fields, reason.trim())}>{submitting ? 'Sending…' : 'Send amendment request'}</button>
    </div>
  </dialog>
}
