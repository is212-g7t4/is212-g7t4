import { expect, test } from 'vitest'
import { singaporeDate, visibleWindow, timestampMicros, overlaps, supportedAnchor, navigateDate } from './dates'
test('SGT date and Monday week never depend on browser timezone', () => {
  expect(singaporeDate(new Date('2026-09-30T17:00:00Z'))).toBe('2026-10-01')
  expect(visibleWindow('2026-10-01', 'week')).toEqual({
    start: '2026-09-28',
    end: '2026-10-05',
  })
})

test('day and six-week month windows remain within backend bound', () => {
  expect(visibleWindow('2026-10-01', 'day')).toEqual({
    start: '2026-10-01',
    end: '2026-10-02',
  })
  expect(visibleWindow('2026-10-31', 'month')).toEqual({
    start: '2026-09-28',
    end: '2026-11-09',
  })
})

test('navigation clamps month-end and crosses years; half-open overlap permits adjacency', async () => {
  const { navigateDate, overlaps, singaporeInput } = await import('./dates')
  expect(navigateDate('2026-01-31', 'month', 1)).toBe('2026-02-28')
  expect(navigateDate('2026-01-01', 'week', -1)).toBe('2025-12-25')
  expect(navigateDate('2026-01-01', 'day', 1)).toBe('2026-01-02')
  expect(
    overlaps(
      '2026-10-01T09:00+08:00',
      '2026-10-01T10:00+08:00',
      '2026-10-01T10:00+08:00',
      '2026-10-01T11:00+08:00',
    ),
  ).toBe(false)
  expect(
    overlaps(
      '2026-10-01T09:00+08:00',
      '2026-10-01T12:00+08:00',
      '2026-10-01T10:00+08:00',
      '2026-10-01T11:00+08:00',
    ),
  ).toBe(true)
  expect(singaporeInput('2026-10-01T09:01')).toBe('2026-10-01T09:01:00+08:00')
  expect(singaporeInput('2026-02-30T09:01')).toBeNull()
  expect(singaporeInput('')).toBeNull()
})

test('exact microseconds respect adjacency, offsets and negative epochs', () => {
  expect(timestampMicros('2026-10-01T10:00:00.000001+08:00')).toBe(timestampMicros('2026-10-01T02:00:00.000001Z'))
  expect(timestampMicros('2026-10-01T10:00:00.1-02:30')).toBe(timestampMicros('2026-10-01T12:30:00.100000Z'))
  expect(timestampMicros('1969-12-31T23:59:59.999999Z')).toBe(-1n)
  expect(overlaps('2026-10-01T10:00:00.000001+08:00', '2026-10-01T10:00:00.000999+08:00',
    '2026-10-01T09:00:00+08:00', '2026-10-01T10:00:00.000001+08:00')).toBe(false)
  expect(overlaps('invalid', 'invalid', 'invalid', 'invalid')).toBe(false)
})
test.each([null, '0000-01-01T00:00:00Z', '2026-02-30T10:00:00Z', '2026-10-01T24:00:00Z',
  '2026-10-01T10:00:00+24:00', '2026-10-01T10:00:00+08:60', '2026-10-01T10:00:00.0000001Z',
  '2026-10-01T10:00:00', '10000-01-01T10:00:00Z'])('invalid ISO instant rejected: %s', (value) => {
  expect(timestampMicros(value)).toBeNull()
})
test.each(['0002-01-01', '9998-12-31'])('supported extreme %s has four-digit API windows in every view', (anchor) => {
  expect(supportedAnchor(anchor)).toBe(true)
  for (const view of ['day', 'week', 'month'] as const) {
    const window = visibleWindow(anchor, view)
    expect(window.start).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(window.end).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(window.start >= '0001-01-01').toBe(true)
    expect(window.end <= '9999-12-31').toBe(true)
  }
})
test.each(['0001-12-31', '9999-01-01', '10000-01-01', '2026-02-30', '2026-13-01', ''])('unsupported date %s', (value) => {
  expect(supportedAnchor(value)).toBe(false)
})
test('early four-digit leap year navigation keeps leap day', () => {
  expect(navigateDate('0004-01-31', 'month', 1)).toBe('0004-02-29')
})
test('inspection accepts seconds without imposing minimum duration', async () => {
  const { singaporeInput } = await import('./dates')
  expect(singaporeInput('2026-10-01T09:00:01')).toBe(
    '2026-10-01T09:00:01+08:00',
  )
})
