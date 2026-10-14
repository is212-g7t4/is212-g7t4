import { useState } from 'react'
import {
  FLAG_AREAS,
  NOTES_LIMIT,
  approveSafetyCheck,
  rejectSafetyCheck,
  requestSafetyChanges,
} from './safetyCheck'
import type { SafetyFlagArea } from './safetyCheck'
import { SafetyRejectDialog } from './SafetyRejectDialog'

type Props = {
  eventId: string
  eventName: string
  safetyOfficerId: string
  /** Called after any successful decision so the page reloads the event. */
  onDecided: () => void
}

type View = 'idle' | 'request-changes' | 'reject'

/**
 * SCRUM-150/151: the Safety Officer's three decisions on an event's
 * Operational Safety Check — Approve, Request changes, Reject.
 *
 * Rendered only for a Safety Officer while the event is 'Pending Safety
 * Check' — the page decides that (AC7, UI side). Approve stays the default
 * view (its remarks field and button are always there, as before SCRUM-151);
 * Request changes and Reject replace it with their own form until cancelled.
 */
export function SafetyDecisionPanel({ eventId, eventName, safetyOfficerId, onDecided }: Props) {
  const [view, setView] = useState<View>('idle')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const idle = () => setView('idle')
  const decided = (text: string) => { setMessage(text); setError(''); idle(); onDecided() }
  const open = (next: View) => { setError(''); setMessage(''); setView(next) }

  return <div className="safety-decision">
    <h4>Operational Safety Check</h4>

    {error && <p className="field-error" role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}

    {view !== 'request-changes' && <>
      <ApproveAction
        eventId={eventId}
        safetyOfficerId={safetyOfficerId}
        onError={setError}
        onDecided={decided}
      />
      <div className="safety-decision-actions">
        <button className="button" type="button" onClick={() => open('request-changes')}>
          Request changes
        </button>{' '}
        <button className="button reject" type="button" onClick={() => open('reject')}>
          Reject
        </button>
      </div>
    </>}

    {view === 'request-changes' && <RequestChangesAction
      eventId={eventId}
      safetyOfficerId={safetyOfficerId}
      onCancel={idle}
      onError={setError}
      onDecided={decided}
    />}

    {view === 'reject' && <RejectAction
      eventId={eventId}
      eventName={eventName}
      safetyOfficerId={safetyOfficerId}
      onCancel={idle}
      onError={setError}
      onDecided={decided}
    />}
  </div>
}

type ActionProps = {
  eventId: string
  safetyOfficerId: string
  onError: (message: string) => void
  onDecided: (message: string) => void
}

function ApproveAction({ eventId, safetyOfficerId, onError, onDecided }: ActionProps) {
  const [remarks, setRemarks] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [approving, setApproving] = useState(false)

  const approve = async () => {
    if (approving) return
    setApproving(true)
    onError('')
    try {
      await approveSafetyCheck({
        eventId,
        safetyOfficerId,
        remarks: remarks.trim() || undefined,
      })
      onDecided('Approved. The event has moved to Confirmed.')
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : 'Unable to approve this safety check.')
    } finally {
      setApproving(false)
    }
  }

  return <div className="safety-decision-form">
    <div className="field">
      <label htmlFor="safety-decision-remarks">Remarks</label>
      <textarea
        id="safety-decision-remarks"
        value={remarks}
        maxLength={NOTES_LIMIT}
        onChange={(change) => { setRemarks(change.target.value) }}
        placeholder="Anything worth recording with this decision (optional)."
      />
      <span className="muted">{remarks.length} / {NOTES_LIMIT}</span>
    </div>

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

function RequestChangesAction({ eventId, safetyOfficerId, onCancel, onError, onDecided }: ActionProps & { onCancel: () => void }) {
  const [selected, setSelected] = useState<Record<SafetyFlagArea, string>>({
    'venue arrangement': '',
    'technical arrangement': '',
    'event details': '',
  })
  const [checked, setChecked] = useState<Record<SafetyFlagArea, boolean>>({
    'venue arrangement': false,
    'technical arrangement': false,
    'event details': false,
  })
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const areas = FLAG_AREAS.filter((area) => checked[area.value])
  // Shown live rather than on submit: the button stays disabled until the
  // request is valid, so a message that only appeared on click never would
  // (AC1's "select at least one area" / "describe the change needed").
  const blocker = areas.length === 0
    ? 'Select at least one affected area.'
    : areas.some((area) => !selected[area.value].trim())
      ? 'Describe the change needed for every selected area.'
      : !reason.trim()
        ? 'Add a reason for the change request.'
        : ''

  const submit = async () => {
    if (submitting || blocker) return
    setSubmitting(true)
    onError('')
    try {
      await requestSafetyChanges({
        eventId,
        safetyOfficerId,
        reason: reason.trim(),
        flags: areas.map((area) => ({
          area: area.value,
          changeRequired: selected[area.value].trim(),
        })),
      })
      onDecided('Changes requested. The event has moved to Safety Changes Requested.')
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : 'Unable to request changes to this safety check.')
    } finally {
      setSubmitting(false)
    }
  }

  return <div className="safety-decision-form">
    <h5>Request changes</h5>
    <p className="muted">
      The event returns to the coordinator at <strong>Safety Changes Requested</strong>. Its venue
      bookings and equipment requests are kept as they are.
    </p>
    <fieldset className="safety-decision-areas">
      <legend>Affected areas</legend>
      {FLAG_AREAS.map((area) => <div key={area.value} className="safety-decision-area">
        <label className="checkbox-option">
          <input
            type="checkbox"
            checked={checked[area.value]}
            onChange={(change) => setChecked({ ...checked, [area.value]: change.target.checked })}
          />
          {area.label}
        </label>
        {checked[area.value] && <textarea
          aria-label={`Change needed for ${area.label}`}
          value={selected[area.value]}
          maxLength={NOTES_LIMIT}
          onChange={(change) => setSelected({ ...selected, [area.value]: change.target.value })}
          placeholder="Describe the change needed."
          required
        />}
      </div>)}
    </fieldset>

    <div className="field">
      <label htmlFor="safety-request-changes-reason">Reason</label>
      <textarea
        id="safety-request-changes-reason"
        value={reason}
        maxLength={NOTES_LIMIT}
        onChange={(change) => setReason(change.target.value)}
        placeholder="Why these changes are needed."
        required
      />
      <span className="muted">{reason.length} / {NOTES_LIMIT}</span>
    </div>

    {blocker && <p className="muted" role="note">{blocker}</p>}

    <button className="button primary" type="button" disabled={submitting || Boolean(blocker)} onClick={submit}>
      {submitting ? 'Requesting changes…' : 'Request changes'}
    </button>{' '}
    <button className="button small" type="button" disabled={submitting} onClick={onCancel}>Cancel</button>
  </div>
}

function RejectAction({ eventId, eventName, safetyOfficerId, onCancel, onError, onDecided }: ActionProps & { eventName: string; onCancel: () => void }) {
  const [reason, setReason] = useState('')
  const [rejecting, setRejecting] = useState(false)

  const reject = async () => {
    if (rejecting) return
    setRejecting(true)
    onError('')
    try {
      const result = await rejectSafetyCheck({ eventId, safetyOfficerId, reason: reason.trim() })
      let text = 'Rejected. The event is cancelled and its venue bookings were released.'
      if (result.release.venueBookingsNotReleased.length > 0) {
        text += ' Some bookings could not be released and must be cancelled by Venue Staff.'
      }
      onDecided(text)
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : 'Unable to reject this safety check.')
    } finally {
      setRejecting(false)
    }
  }

  return <SafetyRejectDialog
    eventName={eventName}
    reason={reason}
    submitting={rejecting}
    onReasonChange={setReason}
    onCancel={onCancel}
    onConfirm={reject}
  />
}
