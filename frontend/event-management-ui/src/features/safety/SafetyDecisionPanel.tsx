import { useState } from 'react'
import {
  FLAG_AREAS,
  NOTES_LIMIT,
  approveSafetyCheck,
  rejectSafetyCheck,
  requestSafetyChanges,
} from './safetyCheck'
import type { SafetyFlagArea } from './safetyCheck'

type Props = {
  eventId: string
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
export function SafetyDecisionPanel({ eventId, safetyOfficerId, onDecided }: Props) {
  const [view, setView] = useState<View>('idle')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const idle = () => setView('idle')
  const decided = (text: string) => { setMessage(text); setError(''); idle(); onDecided() }

  return <div className="safety-decision">
    <h4>Operational Safety Check</h4>

    {error && <p className="field-error" role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}

    {view === 'idle' && <>
      <ApproveAction
        eventId={eventId}
        safetyOfficerId={safetyOfficerId}
        onError={setError}
        onDecided={decided}
      />
      <div className="safety-decision-actions">
        <button className="button" type="button" onClick={() => { setError(''); setMessage(''); setView('request-changes') }}>
          Request changes
        </button>{' '}
        <button className="button reject" type="button" onClick={() => { setError(''); setMessage(''); setView('reject') }}>
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
  const [validationError, setValidationError] = useState('')

  const areas = FLAG_AREAS.filter((area) => checked[area.value])
  const canSubmit = areas.length > 0
    && areas.every((area) => selected[area.value].trim())
    && reason.trim().length > 0

  const submit = async () => {
    if (submitting) return
    if (areas.length === 0) {
      setValidationError('Select at least one area.')
      return
    }
    if (areas.some((area) => !selected[area.value].trim())) {
      setValidationError('Describe the change needed for every selected area.')
      return
    }
    if (!reason.trim()) {
      setValidationError('A reason is required.')
      return
    }
    setValidationError('')
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
    <fieldset className="field">
      <legend>Affected areas</legend>
      {FLAG_AREAS.map((area) => <div key={area.value} className="safety-decision-area">
        <label>
          <input
            type="checkbox"
            checked={checked[area.value]}
            onChange={(change) => setChecked({ ...checked, [area.value]: change.target.checked })}
          />{' '}
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

    {validationError && <p className="field-error" role="alert">{validationError}</p>}

    <button className="button primary" type="button" disabled={submitting || !canSubmit} onClick={submit}>
      {submitting ? 'Requesting changes…' : 'Request changes'}
    </button>{' '}
    <button className="button small" type="button" disabled={submitting} onClick={onCancel}>Cancel</button>
  </div>
}

function RejectAction({ eventId, safetyOfficerId, onCancel, onError, onDecided }: ActionProps & { onCancel: () => void }) {
  const [reason, setReason] = useState('')
  const [confirming, setConfirming] = useState(false)
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

  return <div className="safety-decision-form">
    <div className="field">
      <label htmlFor="safety-reject-reason">Reason</label>
      <textarea
        id="safety-reject-reason"
        value={reason}
        maxLength={NOTES_LIMIT}
        onChange={(change) => setReason(change.target.value)}
        placeholder="Why this safety arrangement is being rejected."
        required
      />
      <span className="muted">{reason.length} / {NOTES_LIMIT}</span>
    </div>

    {confirming ? <div className="safety-decision-confirm">
      <p>Reject and cancel this event? This can't be undone. Its venue bookings will be released.</p>
      <button className="button reject" type="button" disabled={rejecting} onClick={reject}>
        {rejecting ? 'Rejecting…' : 'Yes, reject and cancel'}
      </button>{' '}
      <button className="button small" type="button" disabled={rejecting} onClick={() => setConfirming(false)}>
        Cancel
      </button>
    </div> : <>
      <button className="button reject" type="button" disabled={!reason.trim()} onClick={() => setConfirming(true)}>
        Reject
      </button>{' '}
      <button className="button small" type="button" onClick={onCancel}>Cancel</button>
    </>}
  </div>
}
