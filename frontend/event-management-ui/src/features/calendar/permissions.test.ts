import { expect, test } from 'vitest'
import { canViewCalendar } from './permissions'
test.each([
  'Event Coordinator',
  'Venue Staff',
  'Technical Support',
  'Technical Support Staff',
])('internal %s can inspect', (role) =>
  expect(canViewCalendar(role)).toBe(true),
)
test.each(['Event Organiser', 'Attendee', 'unknown', ''])(
  'external/unknown %s denied',
  (role) => expect(canViewCalendar(role)).toBe(false),
)
