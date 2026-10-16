import type { SubmittedEvent } from './submission'
import { formatDateTime, formatTimestamp } from './formatDates'

export function EventOverview({ event, coordinatorName, assignedByName }: { event: SubmittedEvent; coordinatorName?: string | null; assignedByName?: string | null }) {
  return (
    <>
      <div className="event-facts">
        <span><strong>{formatDateTime(event.preferredStartDate)}</strong>Starts</span>
        <span><strong>{formatDateTime(event.preferredEndDate)}</strong>Ends</span>
        <span><strong>{event.expectedAttendance || '—'}</strong>Expected attendance</span>
      </div>

      <dl className="event-details">
        <div className="event-detail full"><dt>Description</dt><dd>{event.description || 'Not specified'}</dd></div>
        <div className="event-detail full"><dt>Purpose</dt><dd>{event.purpose || 'Not specified'}</dd></div>
        <div className="event-detail"><dt>Venue requirements</dt><dd>{event.venueRequirements || 'Not specified'}</dd></div>
        <div className="event-detail"><dt>Accessibility needs</dt><dd>{event.accessibilityNeeds || 'Not specified'}</dd></div>
        <div className="event-detail"><dt>Equipment requirements</dt><dd>{event.equipmentRequirements || 'Not specified'}</dd></div>
        <div className="event-detail"><dt>Registration needs</dt><dd>{event.registrationNeeds || 'Not specified'}</dd></div>
      </dl>

      <p className="event-footnote muted">
        Assigned to <strong>{coordinatorName || 'Not assigned'}</strong>
        {event.coordinatorId && event.assignedBy && assignedByName && <> by <strong>{assignedByName}</strong></>}
        {event.coordinatorId && event.assignedAt && <> on {formatTimestamp(event.assignedAt)}</>}
        {event.submittedAt && <> · Submitted {formatTimestamp(event.submittedAt)}</>}
        {event.decision?.decidedAt && <> · {event.decision.status} on {formatTimestamp(event.decision.decidedAt)}</>}
      </p>
    </>
  )
}
