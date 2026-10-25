const TIME_ZONE = 'Asia/Singapore'

// The services send naive Singapore local times (e.g. `2026-11-01T09:00:00`).
// `new Date()` reads an offset-less date-time in the *browser's* time zone, so
// outside Singapore (or on a UTC CI runner) 09:00 would display as 17:00.
// Pin those to +08:00; values that already carry an offset are left alone.
const NAIVE_DATE_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/

export function parseSingaporeDate(value: string): Date {
  return new Date(NAIVE_DATE_TIME.test(value) ? `${value}+08:00` : value)
}

export function getDateTile(value: string): { month: string; day: string } {
  const parsed = parseSingaporeDate(value)
  if (Number.isNaN(parsed.getTime())) return { month: '—', day: '—' }
  return {
    month: parsed.toLocaleString('en-SG', { timeZone: TIME_ZONE, month: 'short' }).toUpperCase(),
    day: parsed.toLocaleString('en-SG', { timeZone: TIME_ZONE, day: '2-digit' }),
  }
}

function sameDay(a: Date, b: Date): boolean {
  const format = (date: Date) => date.toLocaleDateString('en-SG', { timeZone: TIME_ZONE })
  return format(a) === format(b)
}

function weekdayDate(value: Date): string {
  return value.toLocaleString('en-SG', { timeZone: TIME_ZONE, weekday: 'short', day: 'numeric', month: 'short' })
}

function time(value: Date): string {
  return value.toLocaleString('en-SG', { timeZone: TIME_ZONE, hour: 'numeric', minute: '2-digit', hour12: true })
}

export function formatSchedule(startValue: string, endValue: string): string {
  const start = parseSingaporeDate(startValue)
  const end = parseSingaporeDate(endValue)
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return `${startValue.replace('T', ' ')} – ${endValue.replace('T', ' ')}`
  }
  if (sameDay(start, end)) {
    return `${weekdayDate(start)} · ${time(start)} – ${time(end)}`
  }
  return `${weekdayDate(start)}, ${time(start)} – ${weekdayDate(end)}, ${time(end)}`
}
