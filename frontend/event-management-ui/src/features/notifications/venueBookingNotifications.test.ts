/**
 * SCRUM-47: As an Event Coordinator and Venue Staff, I want to receive
 * notifications about venue booking requests and decisions, so that I can
 * coordinate venue arrangements efficiently.
 * AC1 Given an Event Coordinator submits a venue booking request, system sends
 * an in-app notification to Venue Staff with event name, requested venue,
 * date/time and link to review.
 * AC2 Given booking approved/rejected, sends an in-app notification to Event
 * Coordinator with event name, venue, decision.
 * Real: destination resolver. No network, router, database or broker is exercised.
 * This case covers AC1's ordinary review destination; dispatcher cases cover AC2.
 */
import { expect, it } from 'vitest'
import { notificationPath } from './notifications'

/** Normal: the staff booking alert opens the ordinary requests page without filters. */
it('AC1: venue booking submission opens the venue requests page', () => {
  expect(notificationPath({ kind: 'venue-requests' })).toBe('/venue-requests')
})
