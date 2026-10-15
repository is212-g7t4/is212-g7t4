import type { CalendarEntry } from './api'

/** Presentation labels never imply a closure is an ordinary event booking. */
export function entryLabel(entry: CalendarEntry): string {
  return entry.status === 'Closed' ? 'Closed' : entry.status === 'On Hold' ? 'On hold' : entry.blocksSelection ? 'Unavailable' : 'Pending confirmation'
}
export function entryClass(entry: CalendarEntry): string {
  return entry.status === 'Closed' ? 'calendar-closed' : entry.status === 'On Hold' ? 'calendar-hold' : entry.blocksSelection ? 'calendar-approved' : 'calendar-pending'
}
export const fullSGT = (value: string) => value.replace('T', ' ').replace('+08:00', '') + ' SGT'
/** Native disclosure works with keyboard/mouse and keeps full original (not clipped) bounds. */
export function ClosureDetails({entry}: {entry: CalendarEntry}) {
  if (entry.status !== 'Closed') return null
  return <details className="calendar-closure-details">
    <summary>Closure details</summary>
    <dl>
      <dt>Closure starts</dt><dd>{fullSGT(entry.requestedStartTime)}</dd>
      <dt>Closure ends</dt><dd>{fullSGT(entry.requestedEndTime)}</dd>
      <dt>Operational reason</dt><dd className="calendar-closure-reason">{entry.reason}</dd>
    </dl>
    <p>Other bookings, holds and operating conditions still apply after this closure ends.</p>
  </details>
}
