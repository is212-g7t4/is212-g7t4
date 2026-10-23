import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { AlertIcon } from './Icon'

// In-app replacement for window.confirm on destructive actions; reuses the rejection dialog styling.
export function ConfirmDialog({ title, children, confirmLabel, pendingLabel, submitting, onCancel, onConfirm }: {
  title: string
  children: ReactNode
  confirmLabel: string
  pendingLabel: string
  submitting: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const element = dialog.current!
    element.showModal()
    return () => element.close()
  }, [])

  return <dialog ref={dialog} className="rejection-dialog" aria-labelledby="confirm-dialog-title" onCancel={(event) => { event.preventDefault(); if (!submitting) onCancel() }}>
    <div className="rejection-dialog-header">
      <span className="rejection-icon"><AlertIcon size={18} /></span>
      <h2 id="confirm-dialog-title">{title}</h2>
    </div>
    <p className="rejection-dialog-copy">{children}</p>
    <div className="rejection-dialog-actions">
      <button className="button secondary" type="button" autoFocus disabled={submitting} onClick={onCancel}>Cancel</button>
      <button className="button reject" type="button" disabled={submitting} onClick={onConfirm}>{submitting ? pendingLabel : confirmLabel}</button>
    </div>
  </dialog>
}
