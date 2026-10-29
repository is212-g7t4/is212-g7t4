import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { StatusBadge } from '../../components/FormControls'
import { InlineLoading } from '../../components/Loading'
import {
  NOTES_LIMIT,
  SafetySubmitError,
  fetchSafetyReadiness,
  submitSafetyCheck,
} from './safetyCheck'
import type { OutstandingArrangement } from './safetyCheck'

type Props = {
  eventId: string
  coordinatorId: string
  /** Bumped by the page when a venue booking changes, so readiness is re-read. */
  refreshKey?: number
  /** Called after a successful submission so the page reloads the event. */
  onSubmitted: () => void
}

/**
 * SCRUM-149: submit an `Approved` event for its Operational Safety Check.
 *
 * Rendered only for the event's own assigned coordinator (AC5) — the caller
 * decides that; see `canUpdate` in EventDetailPage. The panel reads readiness
 * on mount so a coordinator sees what is still outstanding before clicking
 * rather than after (AC2).
 */
export function SafetySubmitPanel({ eventId, coordinatorId, refreshKey = 0, onSubmitted }: Props) {
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [outstanding, setOutstanding] = useState<OutstandingArrangement[]>([])
  const [ready, setReady] = useState(false)
  const [placementNotes, setPlacementNotes] = useState('')
  const [crowdNotes, setCrowdNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')
  const [submitMessage, setSubmitMessage] = useState('')

  useEffect(() => {
    let active = true
    // Deliberately no `setLoading(true)` here: on a re-read (a venue booking
    // changed) the current list stays put until the new one arrives, rather
    // than flashing a spinner over it.
    fetchSafetyReadiness(eventId, coordinatorId).then((readiness) => {
      if (!active) return
      setReady(readiness.ready)
      setOutstanding(readiness.outstanding)
      setLoadError('')
    }).catch((cause: Error) => {
      // Fail closed in the UI too: no readiness means no submit button.
      if (active) setLoadError(cause.message)
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [eventId, coordinatorId, refreshKey])

  const submit = async (formEvent: FormEvent) => {
    formEvent.preventDefault()
    if (submitting || !ready) return
    setSubmitting(true)
    setSubmitError('')
    setSubmitMessage('')
    try {
      await submitSafetyCheck({
        eventId,
        coordinatorId,
        equipmentPlacementNotes: placementNotes.trim() || undefined,
        crowdMovementNotes: crowdNotes.trim() || undefined,
      })
      setSubmitMessage('Submitted for safety check.')
      onSubmitted()
    } catch (cause) {
      if (cause instanceof SafetySubmitError && cause.code === 'ARRANGEMENTS_OUTSTANDING') {
        // AC2: an arrangement changed since the readiness read. Show the
        // server's list, which is now the authoritative one.
        setOutstanding(cause.outstanding || [])
        setReady(false)
        setSubmitError(cause.message)
      } else if (cause instanceof SafetySubmitError && cause.code === 'SAFETY_CHECK_ALREADY_PENDING') {
        // AC4: someone already submitted it. Reload so the page shows that.
        setSubmitError(cause.message)
        onSubmitted()
      } else {
        setSubmitError(cause instanceof Error ? cause.message : 'Unable to submit for a safety check.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) return <div className="safety-submit"><InlineLoading label="Checking arrangements…" /></div>

  return <div className="safety-submit">
    <h4>Submit for safety check</h4>
    {loadError
      ? <p className="field-error" role="alert">{loadError}</p>
      : !ready && outstanding.length > 0 && <div className="safety-outstanding">
          <h5>Before you can submit for a safety check</h5>
          <ul className="safety-outstanding-list">
            {outstanding.map((item, index) => <li key={`${item.type}-${item.id ?? index}`}>
              <span className="safety-outstanding-label">{item.label}</span>
              {item.status && <StatusBadge status={item.status} />}
              <span className="muted">{item.reason}</span>
            </li>)}
          </ul>
        </div>}
    {!loadError && <p className="muted">Rejected venue bookings and equipment requests don't block a safety check. The Safety Officer still sees them in the review.</p>}
    {!loadError && <form onSubmit={submit}>
      {/* Labels are associated explicitly rather than by wrapping, so the
          character count can sit in the same field without becoming part of
          the field's accessible name. */}
      <div className="field-row">
        <div className="field">
          <label htmlFor="safety-placement-notes">Equipment placement notes</label>
          <textarea
            id="safety-placement-notes"
            value={placementNotes}
            maxLength={NOTES_LIMIT}
            onChange={(change) => setPlacementNotes(change.target.value)}
            placeholder="Where the equipment will be set up, and anything the Safety Officer should know about it."
          />
          <span className="muted">{placementNotes.length} / {NOTES_LIMIT}</span>
        </div>
        <div className="field">
          <label htmlFor="safety-crowd-notes">Expected crowd movement notes</label>
          <textarea
            id="safety-crowd-notes"
            value={crowdNotes}
            maxLength={NOTES_LIMIT}
            onChange={(change) => setCrowdNotes(change.target.value)}
            placeholder="How attendees will enter, move through and leave the venue."
          />
          <span className="muted">{crowdNotes.length} / {NOTES_LIMIT}</span>
        </div>
      </div>
      <p className="muted">Both notes are optional.</p>
      {submitError && <p className="field-error" role="alert">{submitError}</p>}
      {submitMessage && <p role="status">{submitMessage}</p>}
      <button className="button primary" type="submit" disabled={!ready || submitting}>
        {submitting ? 'Submitting…' : 'Submit for safety check'}
      </button>
    </form>}
  </div>
}
