import { useEffect, useState } from 'react'
import { DetailPanelSkeleton } from '../../components/Loading'
import { fetchSafetyReview } from './safetyCheck'
import type { SafetyReview as SafetyReviewData } from './safetyCheck'

type Props = { eventId: string; safetyOfficerId: string }

function recorded(value: string | number | null | undefined): string {
  if (value === null || value === undefined || String(value).trim() === '') return 'Not provided'
  return String(value)
}

export function SafetyReview({ eventId, safetyOfficerId }: Props) {
  const [review, setReview] = useState<SafetyReviewData | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    fetchSafetyReview(eventId, safetyOfficerId).then((data) => {
      if (active) setReview(data)
    }).catch((cause: Error) => {
      if (active) setError(cause.message)
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [eventId, safetyOfficerId])

  return <section className="event-card-section safety-review" aria-labelledby="safety-review-heading">
    <h3 id="safety-review-heading">Safety review information</h3>
    {loading ? <DetailPanelSkeleton /> : error ? <p className="field-error" role="alert">{error}</p> : review && <>
      <h4>Venue arrangements</h4>
      {review.venues.length === 0 ? <p>Not provided</p> : review.venues.map((venue) => <div className="safety-review-item" key={venue.bookingId}>
        <h5>{recorded(venue.name)}</h5>
        {venue.overCapacity && <p className="safety-review-warning" role="alert">Over capacity: expected attendance exceeds this venue's capacity.</p>}
        <dl className="event-details">
          <div className="event-detail"><dt>Expected attendance</dt><dd>{recorded(venue.expectedAttendance)}</dd></div>
          <div className="event-detail"><dt>Venue capacity</dt><dd>{recorded(venue.capacity)}</dd></div>
          <div className="event-detail"><dt>Layout</dt><dd>{recorded(venue.layout)}</dd></div>
          <div className="event-detail"><dt>Emergency access</dt><dd>{recorded(venue.emergencyAccess)}</dd></div>
          <div className="event-detail"><dt>Accessibility</dt><dd>{recorded(review.event.accessibilityNeeds)}</dd></div>
          <div className="event-detail"><dt>Venue accessibility details</dt><dd>{recorded(venue.accessibility)}</dd></div>
          <div className="event-detail"><dt>Known venue restrictions</dt><dd>{recorded(venue.restrictions)}</dd></div>
          <div className="event-detail full"><dt>Venue requirements</dt><dd>{recorded(venue.venueRequirements)}</dd></div>
        </dl>
      </div>)}

      <h4>Equipment and placement</h4>
      {review.equipment.length === 0 ? <p>Not provided</p> : <dl className="event-details">
        {review.equipment.map((item) => <div className="event-detail full" key={item.requestId}>
          <dt>{recorded(item.name)} · quantity {recorded(item.quantity)}</dt>
          <dd>{recorded(item.description)}<br />Technical requirements: {recorded(item.technicalRequirements)}</dd>
        </div>)}
      </dl>}
      <dl className="event-details">
        <div className="event-detail full"><dt>Equipment placement notes</dt><dd>{recorded(review.safetyCheck.equipmentPlacementNotes)}</dd></div>
        <div className="event-detail full"><dt>Crowd movement notes</dt><dd>{recorded(review.safetyCheck.crowdMovementNotes)}</dd></div>
      </dl>

      <h4>Previous safety decisions</h4>
      {review.history.length === 0 ? <p>Not provided</p> : review.history.map((decision) => <div className="safety-review-item" key={decision.id}>
        <h5>Round {decision.roundNumber} · {decision.status}</h5>
        <dl className="event-details">
          <div className="event-detail"><dt>Decision date</dt><dd>{recorded(decision.decidedAt)}</dd></div>
          <div className="event-detail full"><dt>Reason</dt><dd>{recorded(decision.withdrawalReason || decision.remarks)}</dd></div>
          <div className="event-detail full"><dt>Requested changes</dt><dd>{decision.flags.length
            ? decision.flags.map((flag) => flag.changeRequired).filter(Boolean).join('; ')
            : 'Not provided'}</dd></div>
        </dl>
      </div>)}
    </>}
  </section>
}