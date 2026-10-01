// Leave a year at each end for Monday padding, the 42-day grid and exclusive API bounds.
export const MIN_ANCHOR = '0002-01-01'
export const MAX_ANCHOR = '9998-12-31'
export function supportedAnchor(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value < MIN_ANCHOR || value > MAX_ANCHOR) return false
  const date = new Date(value + 'T00:00:00Z')
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value
}
export type CalendarView = 'day' | 'week' | 'month'
/** Input instant → YYYY-MM-DD in Asia/Singapore, independent of host timezone. */
export function singaporeDate(now: Date): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Singapore',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(now)
}
/** Calendar-only UTC arithmetic: input date → date displaced by whole days. */
export function addDays(date: string, days: number): string {
  const d = new Date(date + 'T00:00:00Z')
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}
/** Anchor and view → half-open date bounds (Monday-start week). */
export function visibleWindow(
  anchor: string,
  _view: CalendarView,
): { start: string; end: string } {
  if (_view === 'day') return { start: anchor, end: addDays(anchor, 1) }
  const base = _view === 'month' ? anchor.slice(0, 7) + '-01' : anchor
  const weekday = new Date(base + 'T00:00:00Z').getUTCDay()
  const start = addDays(base, -((weekday + 6) % 7))
  return { start, end: addDays(start, _view === 'month' ? 42 : 7) }
}

/** Anchor/view/direction → next anchor, clamping a month-end rather than skipping February. */
export function navigateDate(
  anchor: string,
  view: CalendarView,
  direction: number,
): string {
  if (view !== 'month')
    return addDays(anchor, direction * (view === 'week' ? 7 : 1))
  const d = new Date(anchor + 'T00:00:00Z')
  const day = d.getUTCDate()
  d.setUTCDate(1)
  d.setUTCMonth(d.getUTCMonth() + direction)
  const last = new Date(
    Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0),
  ).getUTCDate()
  d.setUTCDate(Math.min(day, last))
  return d.toISOString().slice(0, 10)
}
/** Valid ISO instant → exact epoch microseconds; reject rollover and excess precision. */
export function timestampMicros(value: unknown): bigint | null {
  if (typeof value !== 'string') return null
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?(Z|[+-]\d{2}:\d{2})$/.exec(value)
  if (!match || value.startsWith('0000')) return null
  const local = match[1] + ':' + (match[2] ?? '00')
  const date = new Date(local + 'Z')
  if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 19) !== local) return null
  const offset = match[4]
  const hours = offset === 'Z' ? 0 : Number(offset.slice(1, 3))
  const minutes = offset === 'Z' ? 0 : Number(offset.slice(4, 6))
  if (hours > 23 || minutes > 59) return null
  const offsetMinutes = (hours * 60 + minutes) * (offset[0] === '-' ? -1 : 1)
  return BigInt(date.getTime() - offsetMinutes * 60000) * 1000n + BigInt((match[3] ?? '').padEnd(6, '0'))
}
/** Two explicit-offset intervals → half-open overlap; touching endpoints are free. */
export function overlaps(
  start: string,
  end: string,
  otherStart: string,
  otherEnd: string,
): boolean {
  const a = timestampMicros(start), b = timestampMicros(end)
  const c = timestampMicros(otherStart), d = timestampMicros(otherEnd)
  return a !== null && b !== null && c !== null && d !== null && a < d && b > c
}
/** datetime-local text → explicit SGT timestamp, or null for missing/invalid calendar dates. */
export function singaporeInput(value: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(value)) return null
  const local = value.length === 16 ? value + ':00' : value
  const date = new Date(local + 'Z')
  if (
    !Number.isFinite(date.getTime()) ||
    date.toISOString().slice(0, 19) !== local
  )
    return null
  return local + '+08:00'
}
