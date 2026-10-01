import { useState } from 'react'
import type { CalendarBooking } from './api'
import { addDays, overlaps, timestampMicros } from './dates'

export function InspectionCalendar({ start, end, rows, summary, venueNames = {}, onBack }: {
  start: string; end: string; rows: CalendarBooking[]; summary: string; venueNames?: Record<string, string>; onBack: () => void
}) {
  const format = Date.parse(end) - Date.parse(start) <= 7 * 86400000 ? 'Week' : 'Month'
  const until = end.slice(11, 19) === '00:00:00' ? end.slice(0, 10) : addDays(end.slice(0, 10), 1)
  const [page, setPage] = useState(0)
  const monthIndex = (date: string) => Number(date.slice(0, 4)) * 12 + Number(date.slice(5, 7)) - 1
  const firstMonth = monthIndex(start)
  const months = monthIndex(addDays(until, -1)) - firstMonth + 1
  const monthDate = (index: number) => `${String(Math.floor(index / 12)).padStart(4, '0')}-${String(index % 12 + 1).padStart(2, '0')}-01`
  // Bound DOM/date allocation independently of the complete fetched result. No dates are discarded.
  const pageStart = page === 0 ? start.slice(0, 10) : monthDate(firstMonth + page * 12)
  const pageEnd = format === 'Week' || (page + 1) * 12 >= months ? until : monthDate(firstMonth + (page + 1) * 12)
  const groups = new Map<string, string[]>()
  for (let date = pageStart; date < pageEnd; date = addDays(date, 1)) {
    const key = format === 'Week' ? `week-${Math.floor((Date.parse(date) - Date.parse(pageStart)) / 86400000 / 7)}` : date.slice(0, 7)
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(date)
  }
  return <section aria-label={`Inspected range · ${format}`} className="calendar-inspection-result">
    <h2>Inspected range · {format}</h2>
    <p role="status">{summary}</p>
    <button onClick={onBack}>Back to calendar</button>
    {months > 12 && <nav aria-label="Selected month pages" className="calendar-result-pagination">
      <button disabled={page === 0} onClick={() => setPage(page - 1)}>Earlier selected months</button>
      <span>Months {page * 12 + 1}–{Math.min((page + 1) * 12, months)} of {months}</span>
      <button disabled={(page + 1) * 12 >= months} onClick={() => setPage(page + 1)}>Later selected months</button>
    </nav>}
    {[...groups].map(([key, dates]) => <div key={key} className="calendar-result-section">
      {format === 'Month' && <h3>{new Intl.DateTimeFormat('en', {month: 'long', year: 'numeric', timeZone: 'UTC'}).format(new Date(dates[0] + 'T12:00:00Z'))}</h3>}
      <div className="calendar-grid-scroll">
        <div className="calendar-weekdays" style={format === 'Week' ? {gridTemplateColumns: `repeat(${dates.length}, minmax(140px, 1fr))`, minWidth: 0} : undefined} aria-hidden="true">{(format === 'Month' ? ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] : dates.map(date => new Intl.DateTimeFormat('en', {weekday: 'short', timeZone: 'UTC'}).format(new Date(date + 'T12:00:00Z')))).map((day, i) => <span key={i}>{day}</span>)}</div>
        <div className={`calendar-result-grid calendar-result-${format.toLowerCase()}`} style={format === 'Week' ? {gridTemplateColumns: `repeat(${Math.min(7, dates.length)}, minmax(140px, 1fr))`} : undefined}>
          {format === 'Month' && Array.from({length: (new Date(dates[0] + 'T12:00:00Z').getUTCDay() + 6) % 7}, (_, i) => <div key={i} className="calendar-alignment-spacer" aria-hidden="true" />)}
          {dates.map(date => <article key={date} data-inspected-date={date} className="calendar-result-day">
            <h4>{date}</h4>
            {rows.filter(b => overlaps(date + 'T00:00:00+08:00', addDays(date, 1) + 'T00:00:00+08:00', b.requestedStartTime, b.requestedEndTime)).map(b => {
              const later = (a: string, b: string) => timestampMicros(a)! > timestampMicros(b)! ? a : b
              const earlier = (a: string, b: string) => timestampMicros(a)! < timestampMicros(b)! ? a : b
              const from = later(later(b.requestedStartTime, start), date + 'T00:00:00+08:00')
              const to = earlier(earlier(b.requestedEndTime, end), addDays(date, 1) + 'T00:00:00+08:00')
              const clipped = timestampMicros(from) !== timestampMicros(b.requestedStartTime) || timestampMicros(to) !== timestampMicros(b.requestedEndTime)
              return <p key={`${b.venueId}:${b.id}`} className={b.blocksSelection ? 'calendar-approved' : 'calendar-pending'}>
                <span className="calendar-venue-name">{venueNames[b.venueId]}</span>
                {b.blocksSelection ? 'Unavailable' : 'Pending confirmation'} · {from.replace('T', ' ').replace('+08:00', '')} – {to.replace('T', ' ').replace('+08:00', '')} SGT
                {clipped && <small>Clipped to selected range/day</small>}
              </p>
            })}
          </article>)}
        </div>
      </div>
    </div>)}
  </section>
}
