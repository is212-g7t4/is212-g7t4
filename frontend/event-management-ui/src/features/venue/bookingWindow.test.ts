import { expect, test } from 'vitest'
import { bookingWindowError } from './permissions'

// SCRUM-28: a venue request must be in the future and on the event's dates.
const NOW = new Date('2030-02-01T05:00:00Z') // 13:00 SGT
const EVENT = ['2030-03-01T09:00', '2030-03-02T17:00'] as const

test('a booking that starts now or earlier is refused', () => {
  expect(bookingWindowError('2030-02-01T13:00', '2030-02-01T15:00', ...EVENT, NOW)).toBe('Booking start must be in the future.')
  expect(bookingWindowError('2030-01-01T13:00', '2030-01-01T15:00', '', '', NOW)).toBe('Booking start must be in the future.')
})

test.each([
  ['2030-02-28T13:00', '2030-02-28T15:00'],
  ['2030-03-02T16:00', '2030-03-03T01:00'],
  ['2030-03-03T09:00', '2030-03-03T11:00'],
])('a booking off the event dates is refused (%s to %s)', (start, end) => {
  expect(bookingWindowError(start, end, ...EVENT, NOW)).toBe("Booking must fall within the event's dates (2030-03-01 to 2030-03-02).")
})

test('any time on the event days is accepted, including setup before the event starts', () => {
  expect(bookingWindowError('2030-03-01T07:00', '2030-03-01T08:00', ...EVENT, NOW)).toBe('')
  expect(bookingWindowError('2030-03-02T07:00', '2030-03-02T23:59', ...EVENT, NOW)).toBe('')
})

test('without event dates only the future check applies', () => {
  expect(bookingWindowError('2031-01-01T09:00', '2031-01-01T10:00', '', '', NOW)).toBe('')
})
