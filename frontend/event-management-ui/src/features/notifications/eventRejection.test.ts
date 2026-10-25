/** SCRUM-45 AC3: organiser rejection links use event-only destinations, never producer URLs. */
import { test, expect } from 'vitest'
import { notificationPath } from './notifications'
const eventId = '30000000-0000-0000-0000-000000000001'
test('event details notification opens existing organiser event route without a booking', () => {
  expect(notificationPath({ kind: 'event-details', eventId })).toBe(`/events/${eventId}`)
  expect(notificationPath({ kind: 'event-details', eventId: '../../outside' })).toBeNull()
})
