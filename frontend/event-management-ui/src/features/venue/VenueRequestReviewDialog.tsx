import './venueBookings.css'
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { User } from '../../types'
import { StatusBadge } from '../../components/FormControls'
import { InlineLoading } from '../../components/Loading'
import { RejectionDialog } from '../../components/RejectionDialog'
import { formatSchedule } from '../event/dateFormat'
import { VenueBookingError, fetchVenueRequestDetail, reviewVenueRequest } from './venueBookings'
import type { VenueBooking, VenueRequestDetail } from './venueBookings'
import { describeVenueConflicts } from './permissions'

const instant = (value: string) => {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('en-SG', {
    timeZone: 'Asia/Singapore', day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true,
  })
}

const schedule = (start: string | null, end: string | null, fallback: string) =>
  start && end ? formatSchedule(start, end) : fallback

function Detail({ label, children, full }: { label: string; children: ReactNode; full?: boolean }) {
  return <div className={`event-detail${full ? ' full' : ''}`}><dt>{label}</dt><dd>{children}</dd></div>
}

/** The modal shell: native <dialog>, same pattern as RejectionDialog and ConfirmDialog. */
function ReviewShell({ title, busy, onClose, children, actions }: {
  title: string; busy: boolean; onClose: () => void; children: ReactNode; actions: ReactNode
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const element = dialog.current!
    element.showModal()
    return () => element.close()
  }, [])
  return <dialog ref={dialog} className="rejection-dialog venue-review-dialog" aria-labelledby="venue-review-title"
    onCancel={(event) => { event.preventDefault(); if (!busy) onClose() }}>
    <div className="rejection-dialog-header"><h2 id="venue-review-title">{title}</h2></div>
    {children}
    <div className="rejection-dialog-actions">{actions}</div>
  </dialog>
}

/**
 * SCRUM-29: Venue Staff open one venue request (AC1) and approve or reject it
 * (AC2, AC3), giving a reason when rejecting (AC4). A request that can't be
 * decided opens read-only with the reason why.
 */
export function VenueRequestReviewDialog({ bookingId, user, onClose, onDecided, onStale }: {
  bookingId: string
  user: Pick<User, 'id' | 'role'>
  onClose: () => void
  /** The decision was recorded; the page updates its row in place. */
  onDecided: (booking: VenueBooking, message: string) => void
  /** Someone else got there first, or the event moved on; the page should reload. */
  onStale: (message: string) => void
}) {
  const [detail, setDetail] = useState<VenueRequestDetail | null>(null)
  const [loadError, setLoadError] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')

  useEffect(() => {
    let active = true
    fetchVenueRequestDetail(bookingId, user).then((loaded) => { if (active) setDetail(loaded) })
      .catch((cause: unknown) => { if (active) setLoadError(cause instanceof Error ? cause.message : 'Unable to load this venue request.') })
    return () => { active = false }
  }, [bookingId, user])

  const decide = async (status: 'Approved' | 'Rejected') => {
    if (submitting) return
    setSubmitting(true)
    setError('')
    try {
      const updated = await reviewVenueRequest(bookingId, status, user, status === 'Rejected' ? reason.trim() : undefined)
      onDecided(updated, status === 'Approved' ? 'Venue request approved.' : 'Venue request rejected.')
    } catch (cause) {
      if (cause instanceof VenueBookingError && cause.status === 409
        && (cause.code === 'BOOKING_ALREADY_DECIDED' || cause.code === 'EVENT_NOT_REVIEWABLE')) {
        onStale(cause.message)
        return
      }
      if (cause instanceof VenueBookingError && cause.status === 409 && cause.code === 'VENUE_UNAVAILABLE') {
        setError(`Not approved. ${describeVenueConflicts(cause.conflictTypes) || 'The venue is unavailable for this time.'}`)
      } else {
        setError(cause instanceof Error ? cause.message : 'Unable to record this decision.')
      }
      // A rejection error is shown back on the review, where the reason is kept.
      setRejecting(false)
    } finally {
      setSubmitting(false)
    }
  }

  if (rejecting && detail) {
    return <RejectionDialog
      title="Reject venue request?"
      eventName={`${detail.booking.venueName} for ${detail.event.eventName ?? 'this event'}`}
      reason={reason}
      submitting={submitting}
      onReasonChange={setReason}
      onCancel={() => setRejecting(false)}
      onConfirm={() => { void decide('Rejected') }}
    />
  }

  const close = <button className="button secondary" type="button" disabled={submitting} onClick={onClose}>Close</button>
  if (!detail) {
    return <ReviewShell title="Venue request" busy={false} onClose={onClose} actions={close}>
      {loadError ? <p className="field-error" role="alert">{loadError}</p> : <InlineLoading label="Loading venue request..." />}
    </ReviewShell>
  }

  const { booking, event, venue } = detail
  const decided = booking.reviewedAt ? ` on ${instant(booking.reviewedAt)}` : ''
  return <ReviewShell title={`${booking.venueName} for ${event.eventName ?? 'this event'}`} busy={submitting} onClose={onClose} actions={<>
    {close}
    {detail.canDecide ? <>
      <button className="button reject" type="button" disabled={submitting} onClick={() => { setError(''); setRejecting(true) }}>Reject</button>
      <button className="button primary approve" type="button" disabled={submitting} onClick={() => { void decide('Approved') }}>
        {submitting ? 'Approving...' : 'Approve'}
      </button>
    </> : null}
  </>}>
    <h3 className="venue-review-heading">Event <StatusBadge status={event.status ?? 'Unknown'} /></h3>
    <dl className="event-details">
      <Detail label="Event dates" full>{schedule(event.preferredStartDate, event.preferredEndDate, 'Event dates not set')}</Detail>
      <Detail label="Expected attendance">{event.expectedAttendance ?? 'Not specified'}</Detail>
      <Detail label="Event venue requirements">{event.venueRequirements ?? 'None specified'}</Detail>
      <Detail label="Accessibility needs" full>{event.accessibilityNeeds ?? 'None specified'}</Detail>
    </dl>
    <h3 className="venue-review-heading">Booking <StatusBadge status={booking.status} label={booking.awaitingReview ? 'Awaiting review' : undefined} /></h3>
    <dl className="event-details">
      <Detail label="Schedule" full>{formatSchedule(booking.requestedStartTime, booking.requestedEndTime)}</Detail>
      <Detail label="Venue occupied" full>
        {schedule(booking.occupiedFrom, booking.occupiedTo, 'Unknown')}
        <span className="muted"> (includes {venue.setupTimeMinutes} min setup, {venue.turnaroundTimeMinutes} min turnaround)</span>
      </Detail>
      <Detail label="Required capacity">{booking.requiredCapacity} of {venue.capacity ?? 'unknown'}</Detail>
      <Detail label="Booking requirements">{booking.venueRequirements || 'None specified'}</Detail>
      {booking.requestedAt && <Detail label="Submitted" full>{instant(booking.requestedAt)}</Detail>}
    </dl>
    {booking.status === 'Rejected' && booking.rejectionReason && <div className="closure-rejection">
      <strong>Rejected{decided}</strong>
      <p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{booking.rejectionReason}</p>
    </div>}
    {booking.status === 'Approved' && decided && <p className="muted">Approved{decided}</p>}
    {!detail.canDecide && detail.decisionBlockedReason && <p className="muted">{detail.decisionBlockedReason}</p>}
    {error && <p className="field-error" role="alert">{error}</p>}
  </ReviewShell>
}
