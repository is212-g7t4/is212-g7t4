import { expect, test } from 'vitest'
import { formatSchedule, getDateTile, parseSingaporeDate } from './dateFormat'

// The services send naive Singapore local times; these must not depend on the
// machine's time zone (CI runs in UTC).
test('a naive date-time is read as Singapore time', () => {
  expect(parseSingaporeDate('2026-11-01T09:00:00').toISOString()).toBe('2026-11-01T01:00:00.000Z')
  expect(parseSingaporeDate('2026-11-01T09:00').toISOString()).toBe('2026-11-01T01:00:00.000Z')
  expect(parseSingaporeDate('2026-11-01T09:00:00.5').toISOString()).toBe('2026-11-01T01:00:00.500Z')
})

test('a date-time with an offset keeps it', () => {
  expect(parseSingaporeDate('2026-11-01T09:00:00Z').toISOString()).toBe('2026-11-01T09:00:00.000Z')
  expect(parseSingaporeDate('2026-11-01T09:00:00+00:00').toISOString()).toBe('2026-11-01T09:00:00.000Z')
})

test('a naive event window shows its Singapore wall-clock times', () => {
  expect(formatSchedule('2026-11-01T09:00:00', '2026-11-01T17:00:00')).toBe('Sun, 1 Nov · 9:00 am – 5:00 pm')
  expect(getDateTile('2026-11-01T00:30:00')).toEqual({ month: 'NOV', day: '01' })
})
