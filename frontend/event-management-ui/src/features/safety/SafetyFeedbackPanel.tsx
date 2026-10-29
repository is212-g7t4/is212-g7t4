import { useEffect, useState } from 'react'
import { InlineLoading } from '../../components/Loading'
import { FLAG_AREAS, SafetySubmitError, fetchSafetyFeedback, fetchSafetyResubmissionReadiness, resubmitSafetyCheck } from './safetyCheck'
import type { SafetyCheckRecord, SafetyResubmissionReadiness } from './safetyCheck'

type Props = { eventId: string; coordinatorId: string; refreshKey?: number; onResubmitted: () => void }

export function SafetyFeedbackPanel({ eventId, coordinatorId, refreshKey = 0, onResubmitted }: Props) {
  const [rounds, setRounds] = useState<SafetyCheckRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [readiness, setReadiness] = useState<SafetyResubmissionReadiness | null>(null)
  const [equipmentError, setEquipmentError] = useState('')
  const [checkedKey, setCheckedKey] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')
  const readinessKey = `${eventId}:${coordinatorId}:${refreshKey}`

  useEffect(() => {
    let active = true
    fetchSafetyFeedback(eventId, coordinatorId).then((records) => {
      if (active) setRounds([...records].sort((first, second) => second.roundNumber - first.roundNumber))
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : 'Unable to load safety feedback.')
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [eventId, coordinatorId])

  useEffect(() => {
    let active = true
    fetchSafetyResubmissionReadiness(eventId, coordinatorId).then((result) => {
      if (active) { setReadiness(result); setEquipmentError('') }
    }).catch((cause: unknown) => {
      if (active) { setReadiness(null); setEquipmentError(cause instanceof Error ? cause.message : 'Unable to check arrangements.') }
    }).finally(() => { if (active) setCheckedKey(readinessKey) })
    return () => { active = false }
  }, [eventId, coordinatorId, readinessKey])

  const checking = checkedKey !== readinessKey
  const disabled = loading || checking || Boolean(error) || !readiness?.ready || submitting || rounds[0]?.status !== 'Changes Requested'
  const resubmit = async () => {
    if (disabled) return
    setSubmitting(true)
    setSubmitError('')
    try {
      await resubmitSafetyCheck({
        eventId, coordinatorId,
        equipmentPlacementNotes: rounds[0].equipmentPlacementNotes || undefined,
        crowdMovementNotes: rounds[0].crowdMovementNotes || undefined,
      })
      onResubmitted()
    } catch (cause) {
      if (cause instanceof SafetySubmitError && cause.code === 'ARRANGEMENTS_OUTSTANDING') {
        setReadiness({ ready: false, eventStatus: 'Safety Changes Requested', outstanding: cause.outstanding || [] })
      }
      if (cause instanceof SafetySubmitError && cause.code === 'SAFETY_CHECK_ALREADY_PENDING') onResubmitted()
      setSubmitError(cause instanceof Error ? cause.message : 'Unable to resubmit the safety check.')
    } finally {
      setSubmitting(false)
    }
  }

  return <section className="event-card-section" aria-label="Safety Officer feedback">
    <h3>Safety Officer feedback</h3>
    {loading ? <InlineLoading label="Loading safety feedback..." />
      : error ? <p className="field-error" role="alert">{error}</p>
        : rounds.length === 0 ? <p className="muted">No safety feedback is available for this event.</p>
          : <>
            <RoundFeedback round={rounds[0]} />
            {rounds.length > 1 && <details>
              <summary>Earlier safety review rounds ({rounds.length - 1})</summary>
              {rounds.slice(1).map((round) => <div key={round.id}>
                <h4>Round {round.roundNumber}</h4>
                <RoundFeedback round={round} />
              </div>)}
            </details>}
          </>}
    {checking && <p className="muted" role="status">Checking venue and equipment requests...</p>}
    {readiness && readiness.outstanding.length > 0 && <p className="muted" role="status">
      Outstanding equipment requests: {readiness.outstanding.filter((item) => item.type === 'equipment').length}<br />
      Outstanding venue requests: {readiness.outstanding.filter((item) => item.type === 'venue').length}
    </p>}
    {readiness && readiness.outstanding.length > 0 && <ul className="safety-outstanding-list">
      {readiness.outstanding.map((item, index) => <li key={`${item.type}-${item.id ?? index}`}>
        <strong>{item.type === 'venue' ? 'Venue' : 'Equipment'}: {item.label}</strong><span>{item.reason}</span>
      </li>)}
    </ul>}
    {readiness && <p className="muted">Rejected venue bookings and equipment requests don't block a safety check. The Safety Officer still sees them in the review.</p>}
    {equipmentError && <p className="field-error" role="alert">{equipmentError}</p>}
    {submitError && <p className="field-error" role="alert">{submitError}</p>}
    <button className="button primary" type="button" disabled={disabled} onClick={() => { void resubmit() }}>
      {submitting ? 'Resubmitting...' : 'Resubmit Safety Check'}
    </button>
  </section>
}

function RoundFeedback({ round }: { round: SafetyCheckRecord }) {
  return <>
    <dl className="event-details">
      <div className="event-detail"><dt>Review round</dt><dd>{round.roundNumber}</dd></div>
      <div className="event-detail"><dt>Decision</dt><dd>{round.status === 'Pending' ? 'Awaiting decision' : round.status}</dd></div>
      {round.decidedAt && <div className="event-detail"><dt>Decision date</dt><dd>{new Date(round.decidedAt).toLocaleString('en-SG', { timeZone: 'Asia/Singapore' })} SGT</dd></div>}
      <div className="event-detail full"><dt>Reason</dt><dd>{round.remarks || 'No reason recorded.'}</dd></div>
    </dl>
    {round.flags.length > 0 && <>
      <h4>Affected areas and requested changes</h4>
      <dl className="event-details">
        {round.flags.map((flag) => <div className="event-detail full" key={flag.id}>
          <dt>{FLAG_AREAS.find((area) => area.value === flag.area)?.label || flag.area}</dt>
          <dd>
            {flag.changeRequired}
            {flag.bookingId && <><br /><span className="muted">Venue booking: {flag.bookingId}</span></>}
            {flag.equipmentRequestId && <><br /><span className="muted">Equipment request: {flag.equipmentRequestId}</span></>}
          </dd>
        </div>)}
      </dl>
    </>}
    {round.withdrawnAt && <p className="muted">
      Approval withdrawn on {new Date(round.withdrawnAt).toLocaleString('en-SG', { timeZone: 'Asia/Singapore' })} SGT.
      {round.withdrawalReason && <> {round.withdrawalReason}</>}
    </p>}
  </>
}