import '../features/calendar/calendar.css'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { User } from '../types'
import { fetchVenues } from '../features/venue/venues'
import type { Venue } from '../features/venue/venues'
import { fetchCalendar } from '../features/calendar/api'
import type { CalendarBooking } from '../features/calendar/api'
import { canViewCalendar } from '../features/calendar/permissions'
import { InspectionCalendar } from '../features/calendar/InspectionCalendar'
import type { CalendarView } from '../features/calendar/dates'
import {
  addDays,
  MIN_ANCHOR,
  MAX_ANCHOR,
  supportedAnchor,
  navigateDate,
  overlaps,
  singaporeInput,
  singaporeDate,
  visibleWindow,
} from '../features/calendar/dates'

function bookingLabel(b: CalendarBooking): string {
  const multiDay = b.requestedStartTime.slice(0, 10) !== b.requestedEndTime.slice(0, 10)
  const time = (value: string) => multiDay ? value.slice(0, 16).replace('T', ' ') : value.slice(11, 16)
  return `${b.blocksSelection ? 'Unavailable' : 'Pending confirmation'} · ${time(b.requestedStartTime)}–${time(b.requestedEndTime)} SGT`
}

/** Switcher identity → read-only calendar, never a booking submission or real auth. */
export function VenueCalendarPage({
  user,
  initialDate,
}: {
  user?: Pick<User, 'id' | 'role'>
  initialDate?: string
}) {
  if (!user || !canViewCalendar(user.role))
    return (
      <p role="alert">
        Permission denied. Venue availability is for internal staff only.
      </p>
    )
  return (
    <Calendar key={user.id + user.role} user={user} initialDate={initialDate} />
  )
}
function Calendar({
  user,
  initialDate,
}: {
  user: Pick<User, 'id' | 'role'>
  initialDate?: string
}) {
  const [venues, setVenues] = useState<Venue[]>([])
  const [catalogueRevision, setCatalogueRevision] = useState(0)
  const [catalogueLoaded, setCatalogueLoaded] = useState(false)
  const [venueIds, setVenueIds] = useState<string[]>([])
  const selectedVenues = venues.filter(v => venueIds.includes(v.id))
  const venueNames = Object.fromEntries(venues.map(v => [v.id, v.name]))
  const [bookings, setBookings] = useState<CalendarBooking[] | null>(null)
  const [error, setError] = useState('')
  const anchorMessage = `Supported anchor dates: ${MIN_ANCHOR} to ${MAX_ANCHOR}.`
  const [anchorError, setAnchorError] = useState(initialDate !== undefined && !supportedAnchor(initialDate) ? anchorMessage : '')
  const [anchor, setAnchor] = useState(initialDate && supportedAnchor(initialDate) ? initialDate : singaporeDate(new Date()))
  const [view, setView] = useState<CalendarView>('month')
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [revision, setRevision] = useState(0)
  const window = useMemo(() => visibleWindow(anchor, view), [anchor, view])
  // The grid snapshot belongs to this exact window/venue/revision; inspection fetches independently.
  const requestKey = [venueIds.join(','), window.start, window.end, revision].join('|')
  const [loadedKey, setLoadedKey] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [selection, setSelection] = useState('')
  const [inspected, setInspected] = useState<{start: string; end: string} | null>(null)
  const ready = venueIds.length > 0 && loadedKey === requestKey && bookings !== null && !error
  const inspectionVersion = useRef(0)
  const inspectionAbort = useRef<AbortController | null>(null)
  const [inspectionLoading, setInspectionLoading] = useState(false)
  const [inspectionError, setInspectionError] = useState('')
  const [inspectionRows, setInspectionRows] = useState<CalendarBooking[]>([])
  function invalidateInspection() {
    inspectionAbort.current?.abort()
    inspectionVersion.current += 1
    setSelection('')
    setInspected(null)
    setInspectionError('')
    setInspectionLoading(false)
    setInspectionRows([])
  }
  useEffect(() => () => { inspectionAbort.current?.abort(); inspectionVersion.current += 1 }, [])
  async function inspect() {
    invalidateInspection()
    const startTime = singaporeInput(start), endTime = singaporeInput(end)
    const validation = !start ? 'Start date/time is required' : !end ? 'End date/time is required' :
      !startTime || !endTime || !supportedAnchor(start.slice(0, 10)) || !supportedAnchor(end.slice(0, 10)) ? 'Enter valid dates and times within the supported date range.' :
      startTime >= endTime ? 'End date/time must be after start date/time' : ''
    if (validation) {
      setInspectionError(validation)
      return
    }
    const controller = new AbortController()
    inspectionAbort.current = controller
    const version = inspectionVersion.current
    setInspectionLoading(true)
    try {
      // Date-only API envelopes cover the precise half-open input range. One request at a time.
      const until = endTime!.slice(11, 19) === '00:00:00' ? end.slice(0, 10) : addDays(end.slice(0, 10), 1)
      const unique = new Map<string, CalendarBooking>()
      for (const venueId of venueIds) {
        for (let from = start.slice(0, 10); from < until;) {
          const next = addDays(from, Math.min(42, (Date.parse(until) - Date.parse(from)) / 86400000))
          const rows = await fetchCalendar(venueId, {start: from, end: next}, user, controller.signal)
          if (version !== inspectionVersion.current) return
          for (const row of rows) {
            const prior = unique.get(`${row.venueId}:${row.id}`)
            if (prior && (Object.keys(prior) as (keyof CalendarBooking)[]).some(key => prior[key] !== row[key]))
              throw new Error('Booking changed between chunks; retry the complete inspection.')
            unique.set(`${row.venueId}:${row.id}`, row)
          }
          from = next
        }
      }
      const matching = [...unique.values()].filter(b => overlaps(startTime!, endTime!, b.requestedStartTime, b.requestedEndTime))
      setInspectionRows(matching)
      setInspectorOpen(false)
      setInspected({start: startTime!, end: endTime!})
      setSelection(`Venues: ${selectedVenues.map(v => v.name).join(', ')}. Selected range: ${start.replace('T', ' ')} – ${end.replace('T', ' ')} SGT. ${matching.filter(b => b.blocksSelection).length} unavailable; ${matching.filter(b => !b.blocksSelection).length} pending confirmation. This is not a reservation.`)
    } catch {
      if (version === inspectionVersion.current) setInspectionError('Inspection unavailable. Retry; no availability can be inferred.')
    } finally {
      if (version === inspectionVersion.current) setInspectionLoading(false)
    }
  }
  /** Navigation/change event → clear inspection before requesting another snapshot. */
  function clearSelection() {
    setStart('')
    setEnd('')
    invalidateInspection()
  }
  function changeVenues(ids: string[]) {
    clearSelection()
    setError('')
    setVenueIds(ids)
  }
  function changeAnchor(date: string) {
    if (!supportedAnchor(date)) {
      setAnchorError(anchorMessage)
      return
    }
    setAnchorError('')
    clearSelection()
    setAnchor(date)
  }
  function changeView(next: CalendarView) {
    clearSelection()
    setView(next)
  }
  useEffect(() => {
    let active = true
    // Loading/error is synchronised with this network request, not derived booking data.
    // oxlint-disable-next-line react/set-state-in-effect
    setError('')
    setCatalogueLoaded(false)
    fetchVenues()
      .then((rows) => {
        if (active) {
          // Validate only fields this inspection dropdown consumes; do not apply request suitability rules.
          if (
            !Array.isArray(rows) ||
            !rows.every(
              (v) =>
                v &&
                typeof v.id === 'string' &&
                /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
                  v.id,
                ) &&
                typeof v.name === 'string',
            )
          )
            throw new Error('Invalid catalogue')
          setVenues(rows)
          setVenueIds(rows.length ? [rows[0].id] : [])
          setCatalogueLoaded(true)
        }
      })
      .catch(() => {
        if (active) setError('Unable to load venues.')
      })
    return () => {
      active = false
    }
  }, [catalogueRevision])
  useEffect(() => {
    if (!venueIds.length) return
    const controller = new AbortController()
    let active = true
    // Clear the prior network result while the replacement request is in flight.
    // oxlint-disable-next-line react/set-state-in-effect
    setError('')
    setBookings(null)
    Promise.all(venueIds.map(id => fetchCalendar(id, window, user, controller.signal))).then(groups => groups.flat())
      .then((rows) => {
        if (active) {
          setBookings(rows)
          setLoadedKey(requestKey)
        }
      })
      .catch(() => {
        if (active)
          setError(
            'Availability unavailable. Refresh to retry; no availability can be inferred.',
          )
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [venueIds, window, user, requestKey])
  return (
    <section
      className="venue-calendar"
      aria-label="Venue availability calendar"
    >
      <div className="calendar-toolbar">
        <div className="calendar-navigation">
          <button onClick={() => changeAnchor(singaporeDate(new Date()))}>Today</button>
          <button className="calendar-arrow" aria-label="Previous" disabled={!supportedAnchor(navigateDate(anchor, view, -1))} onClick={() => changeAnchor(navigateDate(anchor, view, -1))}>‹</button>
          <button className="calendar-arrow" aria-label="Next" disabled={!supportedAnchor(navigateDate(anchor, view, 1))} onClick={() => changeAnchor(navigateDate(anchor, view, 1))}>›</button>
          <h2>{inspected ? 'Inspected range' : new Intl.DateTimeFormat('en', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(anchor + 'T12:00:00Z'))}</h2>
        </div>
        <div className="calendar-controls">
          <details className="calendar-venue-picker">
            <summary>Venues · {selectedVenues.length} selected<span>{selectedVenues.map(v => v.name).join(', ') || 'Choose venues'}</span></summary>
            <fieldset><legend>Select venues</legend>
              <button type="button" disabled={venueIds.length === venues.length} onClick={() => changeVenues(venues.map(v => v.id))}>Select all</button>
              <button type="button" disabled={!venueIds.length} onClick={() => changeVenues([])}>Deselect all</button>
              {venues.map(v => <label key={v.id}><input type="checkbox" checked={venueIds.includes(v.id)} onChange={() => changeVenues(venueIds.includes(v.id) ? venueIds.filter(id => id !== v.id) : [...venueIds, v.id])} />{v.name}</label>)}
            </fieldset>
          </details>
          <div className="calendar-views" aria-label="Calendar view">
        {(['day', 'week', 'month'] as const).map((v) => (
          <button
            key={v}
            aria-pressed={!inspected && view === v}
            onClick={() => changeView(v)}
          >
            {v[0].toUpperCase() + v.slice(1)}
          </button>
        ))}
          </div>
        </div>
      </div>
      <div className="calendar-subbar">
        <span>SGT · Read-only <span className="calendar-legend-approved">Unavailable</span><span className="calendar-legend-pending">Pending confirmation</span></span>
        <div>
          <button onClick={() => { clearSelection(); setRevision(r => r + 1) }}>Refresh</button>
          <button disabled={!venueIds.length} aria-expanded={inspectorOpen} aria-controls="calendar-inspector" onClick={() => setInspectorOpen(!inspectorOpen)}>Inspect time range</button>
          <details className="calendar-jump"><summary>Jump to date</summary>        <label>
          <span>Anchor date</span>
          <small id="calendar-jump-hint">Choose a day to show in the calendar</small>
          <input
            aria-label="Anchor date"
            aria-describedby="calendar-jump-hint"
            type="date"
            min={MIN_ANCHOR}
            max={MAX_ANCHOR}
            value={anchor}
            onChange={(e) => {
              if (e.target.value) changeAnchor(e.target.value)
            }}
          />
        </label>
</details>
        </div>
      </div>
      {!catalogueLoaded && <button onClick={() => setCatalogueRevision(r => r + 1)}>Retry venues</button>}
      {catalogueLoaded && venues.length > 0 && venueIds.length === 0 && <p>Choose at least one venue.</p>}
      {catalogueLoaded && venues.length === 0 && <p>No venues available in the catalogue.</p>}
      {inspected && <InspectionCalendar key={inspected.start + inspected.end} start={inspected.start} end={inspected.end} rows={inspectionRows} venueNames={venueNames} summary={selection} onBack={() => { clearSelection(); setView('month') }} />}
      {!inspected && view === 'month' && (
        <div className="calendar-grid-scroll">
          <div className="calendar-weekdays" aria-hidden="true">
            {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map(day => <span key={day}>{day}</span>)}
          </div>
          <div className="calendar-month">
            {Array.from({ length: 42 }, (_, i) => addDays(window.start, i)).map(date => {
              const entries = ready ? bookings.filter(b => overlaps(
                date + 'T00:00:00+08:00', addDays(date, 1) + 'T00:00:00+08:00',
                b.requestedStartTime, b.requestedEndTime,
              )) : []
              return <button key={date} aria-label={`Open ${date}`}
                className={date.slice(0, 7) !== anchor.slice(0, 7) ? 'calendar-outside' : ''}
                aria-current={date === singaporeDate(new Date()) ? 'date' : undefined}
                disabled={!supportedAnchor(date)} onClick={() => { changeAnchor(date); changeView('day') }}>
                <span className="calendar-date">{Number(date.slice(8))}</span>
                {entries.slice(0, 1).map(b => <span key={`${b.venueId}:${b.id}`}
                  className={b.blocksSelection ? 'calendar-approved' : 'calendar-pending'}
                  title={`${venueNames[b.venueId]} · ${bookingLabel(b)}`}>
                  <span className="calendar-venue-name">{venueNames[b.venueId]}</span>{bookingLabel(b)}
                </span>)}
                {entries.length > 1 && <span className="calendar-more">+{entries.length - 1} more</span>}
              </button>
            })}
          </div>
        </div>
      )}
      {anchorError && <p role="alert">{anchorError}</p>}
      {error && <p role="alert">{error}</p>}
      {!inspected && venueIds.length > 0 && !ready && !error && !(catalogueLoaded && venues.length === 0) && (
        <p>Loading availability…</p>
      )}
      {!inspected && ready && bookings.length === 0 && <p className="calendar-empty">No bookings in this window.</p>}
      {!inspected && ready && view !== 'month' && (
        <div className="calendar-days">
          {Array.from({ length: view === 'day' ? 1 : 7 }, (_, i) =>
            addDays(window.start, i),
          ).map((date) => (
            <article key={date} className="calendar-day">
              <div className="calendar-weekdays" aria-hidden="true"><span>{new Intl.DateTimeFormat('en', {weekday: 'short', timeZone: 'UTC'}).format(new Date(date + 'T12:00:00Z'))}</span></div>
              <h3>{date}</h3>
              {bookings
                .filter((b) =>
                  overlaps(
                    date + 'T00:00:00+08:00',
                    addDays(date, 1) + 'T00:00:00+08:00',
                    b.requestedStartTime,
                    b.requestedEndTime,
                  ),
                )
                .map((b) => (
                  <div
                    key={`${b.venueId}:${b.id}`}
                    className={
                      b.blocksSelection
                        ? 'calendar-approved'
                        : 'calendar-pending'
                    }
                  >
                    <strong>
                      <span className="calendar-venue-name">{venueNames[b.venueId]}</span>{bookingLabel(b)}
                    </strong>
                    <p>
                      {b.requestedStartTime.slice(0, 19).replace('T', ' ')} –{' '}
                      {b.requestedEndTime.slice(0, 19).replace('T', ' ')} SGT
                    </p>
                  </div>
                ))}
            </article>
          ))}
        </div>
      )}

      {inspectorOpen && (
        <aside id="calendar-inspector" className="calendar-inspector" aria-label="Time range inspector">
        <button onClick={() => setInspectorOpen(false)}>Close inspector</button>
        <p>Asia/Singapore (SGT). DEV identity simulation — not authentication.</p>
        <p>Unavailable periods are visual indicators only: every range can be inspected. Pending confirmation does not reserve time.</p>
        <h3>Explore a time range</h3>
        <p className="calendar-window">Choose any dates — you do not need to navigate the calendar first. All times are Singapore time.</p>
        <fieldset disabled={!venueIds.length}>
          <legend>Dates &amp; times</legend>
          <label>
            Start (SGT)
            <input
              type="datetime-local"
              step="1"
              value={start}
              onChange={(e) => {
                setStart(e.target.value)
                invalidateInspection()
              }}
            />
          </label>
          <label>
            End (SGT)
            <input
              type="datetime-local"
              step="1"
              value={end}
              onChange={(e) => {
                setEnd(e.target.value)
                invalidateInspection()
              }}
            />
          </label>

          <button
            disabled={!venueIds.length || inspectionLoading}
            onClick={inspect}
          >
            Inspect range
          </button>
        </fieldset>
        {inspectionLoading && <p>Loading inspection…</p>}
        {inspectionError && <p role="alert">{inspectionError}</p>}

        </aside>
      )}
    </section>
  )
}
