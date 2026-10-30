import { useEffect, useRef, useState } from 'react'
import './venueBookings.css'
import type { FormEvent } from 'react'
import { Field, StatusBadge } from '../../components/FormControls'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { InlineLoading } from '../../components/Loading'
import { singaporeInput } from '../calendar/dates'
import { fetchVenues } from './venues'
import type { Venue } from './venues'
import { fetchActiveVenueHolds } from './venueHolds'
import type { VenueHold } from './venueHolds'
import { VenueBookingError, cancelVenueBooking, createVenueBooking, fetchVenueBookings, updateVenueBooking } from './venueBookings'
import type { VenueBooking } from './venueBookings'
import {
  SAFETY_WITHDRAWAL_WARNING,
  VENUE_REQUEST_CLOSED_NOTICE,
  bookingWindowError,
  canChangeVenueBooking,
  canSubmitVenueRequest,
  describeVenueConflicts,
  venueChangeClosedNotice,
} from './permissions'

type Props = {
  targetBookingId?: string
  eventId: string
  /** SCRUM-28 AC2: new requests are only accepted in some event statuses. */
  eventStatus: string
  coordinatorId: string
  eventStart: string
  eventEnd: string
  eventExpectedAttendance: string
  eventVenueRequirements: string
  /**
   * SCRUM-149: a booking change can make the event ready for its safety check
   * (or stop it being ready), so the page is told to re-read that.
   */
  onBookingsChanged?: () => void
  /** The event's status changed underneath the form, so the page should re-read it. */
  onEventChanged?: () => void
}

const singaporeInstant = (value: string) => /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{1,6}$/.test(value)
  ? value + '+08:00'
  : singaporeInput(value) ?? value
const closureDate = (value: string) => new Intl.DateTimeFormat('en-SG', { timeZone: 'Asia/Singapore', day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(singaporeInstant(value))) + ' SGT'

const localDateTime = (value: string) => {
  if (!value) return ''
  const parsed = new Date(singaporeInstant(value))
  if (!Number.isFinite(parsed.getTime())) return ''
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Singapore', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(parsed)
  const part = (type: string) => parts.find(p => p.type === type)?.value
  return `${part('year')}-${part('month')}-${part('day')}T${part('hour')}:${part('minute')}`
}

export function VenueBookingsPanel({
  targetBookingId,
  eventId,
  eventStatus,
  coordinatorId,
  eventStart,
  eventEnd,
  eventExpectedAttendance,
  eventVenueRequirements,
  onBookingsChanged,
  onEventChanged,
}: Props) {
  const [bookings, setBookings] = useState<VenueBooking[]>([])
  const [venues, setVenues] = useState<Venue[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [venueError, setVenueError] = useState('')
  const [holdsError, setHoldsError] = useState('')
  const [activeHolds, setActiveHolds] = useState<VenueHold[]>([])
  const [submitError, setSubmitError] = useState('')
  const draftRevision = useRef(0)
  const [submitMessage, setSubmitMessage] = useState('')
  const [saving, setSaving] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [cancellingId, setCancellingId] = useState<string | null>(null)
  const [venueId, setVenueId] = useState('')
  const [start, setStart] = useState(localDateTime(eventStart))
  const [end, setEnd] = useState(localDateTime(eventEnd))
  const [requiredCapacity, setRequiredCapacity] = useState(eventExpectedAttendance)
  const [requirements, setRequirements] = useState(eventVenueRequirements)
  // SCRUM-28 Part B: on a Confirmed event a change waits for this confirmation.
  const [pendingChange, setPendingChange] = useState<{ kind: 'edit' } | { kind: 'cancel'; booking: VenueBooking } | null>(null)

  useEffect(() => {
    let active = true
    Promise.allSettled([
      fetchVenueBookings(eventId, coordinatorId),
      fetchVenues(),
      fetchActiveVenueHolds(),
    ]).then(([bookingResult, venueResult, holdsResult]) => {
      if (!active) return
      if (bookingResult.status === 'fulfilled') setBookings(bookingResult.value)
      else setLoadError(bookingResult.reason instanceof Error ? bookingResult.reason.message : 'Unable to load venue bookings.')
      if (venueResult.status === 'fulfilled') setVenues(venueResult.value)
      else setVenueError(venueResult.reason instanceof Error ? venueResult.reason.message : 'Unable to load venues.')
      if (holdsResult.status === 'fulfilled') setActiveHolds(holdsResult.value)
      else setHoldsError(holdsResult.reason instanceof Error ? holdsResult.reason.message : 'Unable to load active venue holds.')
      setLoading(false)
    })
    return () => { active = false }
  }, [eventId, coordinatorId])

  const target = useRef<HTMLElement | null>(null)
  useEffect(() => {
    if (!loading && targetBookingId && target.current) {
      target.current.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
      target.current.focus({ preventScroll: true })
    }
  }, [loading, targetBookingId])
  const acceptsNewRequests = canSubmitVenueRequest(eventStatus)
  const acceptsChanges = canChangeVenueBooking(eventStatus)
  const withdrawsApproval = eventStatus === 'Confirmed'
  const withdrawalNote = withdrawsApproval ? " The event's safety approval was withdrawn and it is back to Approved." : ''
  const availableVenues = venues.filter((venue) => venue.status === 'Available')
  const overlapsActiveHold = (venueId: string) => {
    const bookingStart = Date.parse(singaporeInstant(start))
    const bookingEnd = Date.parse(singaporeInstant(end))
    return activeHolds.some((hold) => hold.venueId === venueId
      && bookingStart < Date.parse(hold.expiresAt)
      && bookingEnd > Date.parse(hold.createdAt))
  }

  const resetForm = () => {
    setSubmitError('')
    setEditingId(null)
    setVenueId('')
    setStart(localDateTime(eventStart))
    setEnd(localDateTime(eventEnd))
    setRequiredCapacity(eventExpectedAttendance)
    setRequirements(eventVenueRequirements)
  }

  const edit = (booking: VenueBooking) => {
    setEditingId(booking.id)
    setVenueId(booking.venueId)
    setStart(localDateTime(booking.requestedStartTime))
    setEnd(localDateTime(booking.requestedEndTime))
    setRequiredCapacity(String(booking.requiredCapacity))
    setRequirements(booking.venueRequirements)
    setSubmitError('')
    setSubmitMessage('')
  }

  const handleImmutable = async (cause: unknown, bookingId: string | null) => {
    if (!(cause instanceof VenueBookingError) || cause.code !== 'BOOKING_IMMUTABLE') return false
    if (editingId === bookingId) {
      setEditingId(null)
      setSubmitError('This request is now read-only. Your draft is retained; use Add venue booking for a separate replacement.')
    } else {
      setSubmitError('This request is now read-only. Your other booking draft is unchanged.')
    }
    try { setBookings(await fetchVenueBookings(eventId, coordinatorId)); onBookingsChanged?.() }
    catch { setLoadError('Unable to refresh bookings. Reload the page to view the latest request status.') }
    return true
  }

  /** The event's status moved on while the form was open (SCRUM-28 AC2 / Part B). */
  const handleEventStatusChanged = async (cause: unknown) => {
    if (!(cause instanceof VenueBookingError) || cause.status !== 409
      || !['EVENT_NOT_ACCEPTING_VENUE_REQUESTS', 'EVENT_NOT_ACCEPTING_VENUE_CHANGES'].includes(cause.code ?? '')) return false
    setSubmitError(cause.message)
    try { setBookings(await fetchVenueBookings(eventId, coordinatorId)) }
    catch { setLoadError('Unable to refresh bookings. Reload the page to view the latest request status.') }
    onEventChanged?.()
    return true
  }

  const validDraft = () => {
    const capacity = Number(requiredCapacity)
    if (!venueId || !start || !end || !Number.isInteger(capacity) || capacity < 1) {
      setSubmitError('Select a venue and provide valid dates and a positive required capacity.')
      return false
    }
    if (end <= start) {
      setSubmitError('Booking end date and time must be after the start.')
      return false
    }
    const windowError = bookingWindowError(start, end, localDateTime(eventStart), localDateTime(eventEnd))
    if (windowError) {
      setSubmitError(windowError)
      return false
    }
    return true
  }

  const submit = (formEvent: FormEvent) => {
    formEvent.preventDefault()
    if (saving) return
    setSubmitError('')
    setSubmitMessage('')
    if (!validDraft()) return
    if (editingId && withdrawsApproval) {
      setPendingChange({ kind: 'edit' })
      return
    }
    void save()
  }

  const save = async () => {
    const capacity = Number(requiredCapacity)
    setSaving(true)
    const submittedRevision = draftRevision.current
    try {
      const details = {
        eventId,
        venueId,
        coordinatorId,
        requestedStartTime: start,
        requestedEndTime: end,
        requiredCapacity: capacity,
        venueRequirements: requirements,
      }
      const saved = editingId
        ? await updateVenueBooking(editingId, details)
        : await createVenueBooking(details)
      const selectedVenue = venues.find((venue) => venue.id === venueId)
      const displayed = { ...saved, venueName: saved.venueName || selectedVenue?.name || 'Unknown venue' }
      setBookings((current) => (
        editingId
          ? current.map((booking) => booking.id === editingId ? displayed : booking)
          : [...current, displayed]
      ).sort((left, right) => left.requestedStartTime.localeCompare(right.requestedStartTime)))
      setSubmitMessage(editingId
        ? `${selectedVenue?.name || 'Venue'} booking updated and returned to pending review.${withdrawalNote}`
        : `${selectedVenue?.name || 'Venue'} booking request submitted. Status: Pending Review.`)
      resetForm()
      onBookingsChanged?.()
      if (editingId && withdrawsApproval) onEventChanged?.()
    } catch (cause) {
      if (await handleImmutable(cause, editingId)) return
      // The event moved on while the form was open; this isn't a venue conflict.
      if (await handleEventStatusChanged(cause)) return
      if (cause instanceof VenueBookingError && cause.status === 409 && cause.code === 'VENUE_UNAVAILABLE') {
        // A late rejection belongs to the submitted draft, not a newly edited time/venue.
        if (submittedRevision !== draftRevision.current) return
        const reasons = describeVenueConflicts(cause.conflictTypes)
        setSubmitError(`Request not submitted. ${reasons || 'The venue is unavailable for this time.'} Choose another venue or time.`)
      } else {
        setSubmitError(cause instanceof Error ? cause.message : 'Unable to save this venue booking.')
      }
    } finally {
      setSaving(false)
      setPendingChange(null)
    }
  }

  const cancel = (booking: VenueBooking) => {
    if (cancellingId || saving) return
    if (withdrawsApproval) {
      setPendingChange({ kind: 'cancel', booking })
      return
    }
    if (!window.confirm(`Cancel the ${booking.venueName} booking? The record will remain visible as Cancelled.`)) return
    void performCancel(booking)
  }

  const performCancel = async (booking: VenueBooking) => {
    setSubmitError('')
    setSubmitMessage('')
    setCancellingId(booking.id)
    try {
      const cancelled = await cancelVenueBooking(booking.id, eventId, coordinatorId)
      setBookings((current) => current.map((item) => item.id === booking.id
        ? { ...cancelled, venueName: item.venueName }
        : item))
      if (editingId === booking.id) resetForm()
      setSubmitMessage(`${booking.venueName} booking cancelled. Other venue bookings were not changed.${withdrawalNote}`)
      onBookingsChanged?.()
      if (withdrawsApproval) onEventChanged?.()
    } catch (cause) {
      if (await handleImmutable(cause, booking.id)) return
      if (await handleEventStatusChanged(cause)) return
      setSubmitError(cause instanceof Error ? cause.message : 'Unable to cancel this venue booking.')
    } finally {
      setCancellingId(null)
      setPendingChange(null)
    }
  }

  return <section className="event-card-section venue-bookings-section">
    <h3>Venue bookings</h3>
    <p className="muted">Create separate venue requests for this event. Capacity, timing, requirements, and status are evaluated per booking.</p>

    {loading ? <InlineLoading label="Loading venue bookings…" /> : <>
      {loadError && <p className="field-error" role="alert">{loadError}</p>}
      {targetBookingId && !bookings.some(booking => booking.id === targetBookingId) && <p role="status">The linked venue request is unavailable or you no longer have access. Your historical notification is retained.</p>}
      {bookings.length === 0 ? <p className="muted">No venue booking requests yet.</p> :
        <div className="venue-booking-list">
          {bookings.map((booking) => <article id={`venue-booking-${booking.id}`} tabIndex={booking.id === targetBookingId ? -1 : undefined} ref={booking.id === targetBookingId ? target : undefined} className={`venue-booking-item${booking.id === targetBookingId ? ' notification-target' : ''}`} key={booking.id}>
            <header><strong>{booking.venueName}</strong><StatusBadge status={booking.status} /></header>
            <dl className="event-details">
              <div className="event-detail full"><dt>Date and time</dt><dd>{closureDate(booking.requestedStartTime)} – {closureDate(booking.requestedEndTime)}</dd></div>
              <div className="event-detail"><dt>Required capacity</dt><dd>{booking.requiredCapacity}</dd></div>
              <div className="event-detail"><dt>Venue requirements</dt><dd>{booking.venueRequirements || 'None specified'}</dd></div>
            </dl>
            {booking.closureRejection && <div className="closure-rejection">
              <strong>Rejected due to temporary venue closure</strong>
              <p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{booking.closureRejection.reason}</p>
              <p>{closureDate(booking.closureRejection.startDateTime)} – {closureDate(booking.closureRejection.endDateTime)}</p>
            </div>}
            {/* SCRUM-29 AC2/AC3/AC6: the Venue Staff decision, and why a request was rejected. */}
            {booking.status === 'Approved' && booking.reviewedAt && <p className="muted">Approved by Venue Staff on {closureDate(booking.reviewedAt)}</p>}
            {booking.status === 'Rejected' && !booking.closureRejection && (booking.rejectionReason
              ? <div className="closure-rejection">
                <strong>Rejected by Venue Staff</strong>
                <p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{booking.rejectionReason}</p>
                {booking.reviewedAt && <p>{closureDate(booking.reviewedAt)}</p>}
              </div>
              : <p className="muted">Rejected by Venue Staff</p>)}
            {booking.status === 'Rejected' && <p className="muted">Rejected requests are read-only. Use Add venue booking below to request a replacement.</p>}
            {booking.status !== 'Cancelled' && booking.status !== 'Rejected' && <div className="venue-booking-actions">
              <button className="button small" type="button" disabled={!acceptsChanges || saving || cancellingId !== null} onClick={() => edit(booking)}>Edit booking</button>
              <button className="button small reject" type="button" disabled={!acceptsChanges || saving || cancellingId !== null} onClick={() => cancel(booking)}>
                {cancellingId === booking.id ? 'Cancelling…' : 'Cancel booking'}
              </button>
            </div>}
          </article>)}
        </div>}
      {bookings.length > 0 && !acceptsChanges && <p className="muted">{venueChangeClosedNotice(eventStatus)}</p>}

      {!editingId && !acceptsNewRequests ? <div className="venue-booking-form">
        <h4>Add venue booking</h4>
        <p className="muted">{VENUE_REQUEST_CLOSED_NOTICE}</p>
        {submitError && <p className="field-error" role="alert">{submitError}</p>}
        {submitMessage && <p role="status">{submitMessage}</p>}
      </div> : <form className="venue-booking-form" onSubmit={submit} onChangeCapture={() => { draftRevision.current += 1 }}>
        <h4>{editingId ? 'Edit venue booking' : 'Add venue booking'}</h4>
        <label className="field"><span>Venue <span className="required">*</span></span>
          <select value={venueId} onChange={(change) => { setVenueId(change.target.value); setSubmitError('') }} disabled={Boolean(venueError || holdsError)} required>
            <option value="">Select a venue</option>
            {availableVenues.map((venue) => {
              const isOnHold = overlapsActiveHold(venue.id)
              return <option key={venue.id} value={venue.id} disabled={isOnHold}>
                {venue.name} · capacity {venue.capacity ?? 'unknown'}{isOnHold ? ' (On Hold)' : ''}
              </option>
            })}
          </select>
          {venueError && <span className="field-error" role="alert">{venueError}</span>}
          {holdsError && <span className="field-error" role="alert">{holdsError}</span>}
        </label>
        <div className="field-row">
          <Field label="Booking start" type="datetime-local" value={start} onChange={(value) => { setStart(value); setSubmitError('') }} required />
          <Field label="Booking end" type="datetime-local" value={end} onChange={(value) => { setEnd(value); setSubmitError('') }} required />
        </div>
        <Field label="Expected attendance / required capacity" type="number" min="1" value={requiredCapacity} onChange={(value) => { setRequiredCapacity(value); setSubmitError('') }} required />
        <Field label="Venue requirements" value={requirements} onChange={(value) => { setRequirements(value); setSubmitError('') }} textarea placeholder="e.g. Theatre seating, stage and projector." />
        {submitError && <p className="field-error" role="alert">{submitError}</p>}
        {submitMessage && <p role="status">{submitMessage}</p>}
        <button className="button primary" type="submit" disabled={saving || cancellingId !== null || Boolean(venueError || holdsError)}>
          {saving ? 'Saving…' : editingId ? 'Save venue booking' : 'Submit venue booking'}
        </button>
        {editingId && withdrawsApproval && <p className="muted">{SAFETY_WITHDRAWAL_WARNING}</p>}
        {editingId && <button className="button" type="button" disabled={saving} onClick={resetForm}>Discard changes</button>}
      </form>}
    </>}
    {pendingChange && <ConfirmDialog
      title={pendingChange.kind === 'edit' ? 'Save this venue booking change?' : `Cancel the ${pendingChange.booking.venueName} booking?`}
      confirmLabel={pendingChange.kind === 'edit' ? 'Save and withdraw approval' : 'Cancel booking and withdraw approval'}
      pendingLabel={pendingChange.kind === 'edit' ? 'Saving…' : 'Cancelling…'}
      submitting={saving || cancellingId !== null}
      onCancel={() => setPendingChange(null)}
      onConfirm={() => {
        if (pendingChange.kind === 'edit') { if (validDraft()) void save(); else setPendingChange(null) }
        else void performCancel(pendingChange.booking)
      }}
    >{SAFETY_WITHDRAWAL_WARNING}</ConfirmDialog>}
  </section>
}
