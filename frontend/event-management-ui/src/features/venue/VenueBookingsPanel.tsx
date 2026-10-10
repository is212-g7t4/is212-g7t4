import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Field, StatusBadge } from '../../components/FormControls'
import { InlineLoading } from '../../components/Loading'
import { formatSchedule } from '../event/dateFormat'
import { fetchVenues } from './venues'
import type { Venue } from './venues'
import { cancelVenueBooking, createVenueBooking, fetchVenueBookings, updateVenueBooking } from './venueBookings'
import type { VenueBooking } from './venueBookings'

type Props = {
  eventId: string
  coordinatorId: string
  eventStart: string
  eventEnd: string
  eventExpectedAttendance: string
  eventVenueRequirements: string
}

const localDateTime = (value: string) => value ? value.slice(0, 16) : ''

export function VenueBookingsPanel({
  eventId,
  coordinatorId,
  eventStart,
  eventEnd,
  eventExpectedAttendance,
  eventVenueRequirements,
}: Props) {
  const [bookings, setBookings] = useState<VenueBooking[]>([])
  const [venues, setVenues] = useState<Venue[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [venueError, setVenueError] = useState('')
  const [submitError, setSubmitError] = useState('')
  const [submitMessage, setSubmitMessage] = useState('')
  const [saving, setSaving] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [cancellingId, setCancellingId] = useState<string | null>(null)
  const [venueId, setVenueId] = useState('')
  const [start, setStart] = useState(localDateTime(eventStart))
  const [end, setEnd] = useState(localDateTime(eventEnd))
  const [requiredCapacity, setRequiredCapacity] = useState(eventExpectedAttendance)
  const [requirements, setRequirements] = useState(eventVenueRequirements)

  useEffect(() => {
    let active = true
    Promise.allSettled([
      fetchVenueBookings(eventId, coordinatorId),
      fetchVenues(),
    ]).then(([bookingResult, venueResult]) => {
      if (!active) return
      if (bookingResult.status === 'fulfilled') setBookings(bookingResult.value)
      else setLoadError(bookingResult.reason instanceof Error ? bookingResult.reason.message : 'Unable to load venue bookings.')
      if (venueResult.status === 'fulfilled') setVenues(venueResult.value)
      else setVenueError(venueResult.reason instanceof Error ? venueResult.reason.message : 'Unable to load venues.')
      setLoading(false)
    })
    return () => { active = false }
  }, [eventId, coordinatorId])

  const availableVenues = venues.filter((venue) => venue.status === 'Available')

  const resetForm = () => {
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

  const submit = async (formEvent: FormEvent) => {
    formEvent.preventDefault()
    if (saving) return
    setSubmitError('')
    setSubmitMessage('')
    const capacity = Number(requiredCapacity)
    if (!venueId || !start || !end || !Number.isInteger(capacity) || capacity < 1) {
      setSubmitError('Select a venue and provide valid dates and a positive required capacity.')
      return
    }
    if (end <= start) {
      setSubmitError('Booking end date and time must be after the start.')
      return
    }
    setSaving(true)
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
        ? `${selectedVenue?.name || 'Venue'} booking updated and returned to pending review.`
        : `${selectedVenue?.name || 'Venue'} booking request submitted independently.`)
      resetForm()
    } catch (cause) {
      setSubmitError(cause instanceof Error ? cause.message : 'Unable to save this venue booking.')
    } finally {
      setSaving(false)
    }
  }

  const cancel = async (booking: VenueBooking) => {
    if (cancellingId || saving) return
    if (!window.confirm(`Cancel the ${booking.venueName} booking? The record will remain visible as Cancelled.`)) return
    setSubmitError('')
    setSubmitMessage('')
    setCancellingId(booking.id)
    try {
      const cancelled = await cancelVenueBooking(booking.id, eventId, coordinatorId)
      setBookings((current) => current.map((item) => item.id === booking.id
        ? { ...cancelled, venueName: item.venueName }
        : item))
      if (editingId === booking.id) resetForm()
      setSubmitMessage(`${booking.venueName} booking cancelled. Other venue bookings were not changed.`)
    } catch (cause) {
      setSubmitError(cause instanceof Error ? cause.message : 'Unable to cancel this venue booking.')
    } finally {
      setCancellingId(null)
    }
  }

  return <section className="event-card-section venue-bookings-section">
    <h3>Venue bookings</h3>
    <p className="muted">Create separate venue requests for this event. Capacity, timing, requirements, and status are evaluated per booking.</p>

    {loading ? <InlineLoading label="Loading venue bookings…" /> : <>
      {loadError && <p className="field-error" role="alert">{loadError}</p>}
      {bookings.length === 0 ? <p className="muted">No venue booking requests yet.</p> :
        <div className="venue-booking-list">
          {bookings.map((booking) => <article className="venue-booking-item" key={booking.id}>
            <header><strong>{booking.venueName}</strong><StatusBadge status={booking.status} /></header>
            <dl className="event-details">
              <div className="event-detail full"><dt>Date and time</dt><dd>{formatSchedule(booking.requestedStartTime, booking.requestedEndTime)}</dd></div>
              <div className="event-detail"><dt>Required capacity</dt><dd>{booking.requiredCapacity}</dd></div>
              <div className="event-detail"><dt>Venue requirements</dt><dd>{booking.venueRequirements || 'None specified'}</dd></div>
            </dl>
            {booking.status !== 'Cancelled' && <div className="venue-booking-actions">
              <button className="button small" type="button" disabled={saving || cancellingId !== null} onClick={() => edit(booking)}>Edit booking</button>
              <button className="button small reject" type="button" disabled={saving || cancellingId !== null} onClick={() => void cancel(booking)}>
                {cancellingId === booking.id ? 'Cancelling…' : 'Cancel booking'}
              </button>
            </div>}
          </article>)}
        </div>}

      <form className="venue-booking-form" onSubmit={submit}>
        <h4>{editingId ? 'Edit venue booking' : 'Add venue booking'}</h4>
        <label className="field"><span>Venue <span className="required">*</span></span>
          <select value={venueId} onChange={(change) => { setVenueId(change.target.value); setSubmitError('') }} disabled={Boolean(venueError)} required>
            <option value="">Select a venue</option>
            {availableVenues.map((venue) => <option key={venue.id} value={venue.id}>{venue.name} · capacity {venue.capacity ?? 'unknown'}</option>)}
          </select>
          {venueError && <span className="field-error" role="alert">{venueError}</span>}
        </label>
        <div className="field-row">
          <Field label="Booking start" type="datetime-local" value={start} onChange={setStart} required />
          <Field label="Booking end" type="datetime-local" value={end} onChange={setEnd} required />
        </div>
        <Field label="Expected attendance / required capacity" type="number" min="1" value={requiredCapacity} onChange={setRequiredCapacity} required />
        <Field label="Venue requirements" value={requirements} onChange={setRequirements} textarea placeholder="e.g. Theatre seating, stage and projector." />
        {submitError && <p className="field-error" role="alert">{submitError}</p>}
        {submitMessage && <p role="status">{submitMessage}</p>}
        <button className="button primary" type="submit" disabled={saving || cancellingId !== null || Boolean(venueError)}>
          {saving ? 'Saving…' : editingId ? 'Save venue booking' : 'Submit venue booking'}
        </button>
        {editingId && <button className="button" type="button" disabled={saving} onClick={resetForm}>Discard changes</button>}
      </form>
    </>}
  </section>
}
