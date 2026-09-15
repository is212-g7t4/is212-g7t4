import { useEffect, useRef } from 'react'

export function SubmissionPopup({ title, messages, onClose }: { title: string; messages: string[]; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const element = dialog.current!
    element.showModal()
    return () => element.close()
  }, [])
  return <dialog ref={dialog} className="submission-dialog" aria-labelledby="submission-popup-title" onCancel={(event) => { event.preventDefault(); onClose() }}>
    <h2 id="submission-popup-title">{title}</h2>
    <ul>{messages.map((message) => <li key={message}>{message}</li>)}</ul>
    <button className="button primary" autoFocus onClick={onClose}>OK</button>
  </dialog>
}

