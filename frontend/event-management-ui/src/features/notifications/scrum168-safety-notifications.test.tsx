/**
 * SCRUM-168 — Safety review notification presentation (component tests).
 * AC mapping:
 * AC1: submitted-review name, proposed Singapore date/time, round and event-details
 *      href render for an officer; submission/recheck triggers and all-officer
 *      recipient selection are covered by Event/Workflow story tests, not here.
 * AC2: coordinator decision cards show Approved (with/without optional remarks),
 *      Rejected with reason, and Changes Requested with reason/affected-area labels.
 *      Changes Requested also renders in the bell; recipient capture and producer
 *      deduplication of affected areas belong to Event/Workflow story tests.
 * AC3: no transaction, persistence, retry or rollback proof here; Event's unit/
 *      disposable-PostgreSQL story tests and Workflow's worker tests cover those seams.
 * AC4: existing provider, inbox and bell render the two delivered safety types and
 *      allowlisted event-details hrefs. Existing NotificationCenter regressions
 *      cover refresh/read/navigation; Notification's consumer story tests cover its
 *      boundary. These component tests do not prove broker or live inbox delivery.
 * Real: React provider/components, payload presentation, date formatter and href
 *       allowlist in jsdom. Mocked: fetch inbox/unread-count responses and navigation
 *       callbacks; users and producer-shaped envelopes are synthetic fixtures.
 * Links are asserted, not followed. No services, database or browser journey run.
 * Fixed 2026 timestamps are historical formatting examples, not future scheduling
 * inputs or expiry checks. Schedule values carry +08:00; expected display uses SGT
 * explicitly (Asia/Singapore), independent of the current date or host timezone.
 */
import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { NotificationBell, NotificationProvider, NotificationsPage } from './NotificationCenter'
import type { InboxItem } from './notifications'
import type { User } from '../../types'

const eventId = '30000000-0000-0000-0000-000000000001'
const coordinator = { id: '10000000-0000-0000-0000-000000000001', role: 'Event Coordinator' as const, username: 'Coordinator', email: '', organization: '' }
const officer = { ...coordinator, role: 'Safety Officer' as const }
type SafetyDetails = NonNullable<NonNullable<InboxItem['payload']>['details']> & { recipientId: string }

// Details mirror Event models.py::_record_safety_review/_record_safety_decision
// (with recipientId added by fanout); messages mirror Workflow dispatcher.py::
// safety_review_message/safety_decision_message. These are static producer-shaped
// fixtures, not an execution of the producer or proof of cross-service delivery.
function start(type: string, message: string, details: SafetyDetails, user: User = coordinator) {
  const item: InboxItem = {
    id: 'safety-notification', type, eventId, createdAt: '2026-10-28T01:00:00Z', readAt: null,
    payload: { message, destination: { kind: 'event-details', eventId }, details },
  }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
    ok: true,
    json: async () => url.includes('unread-count') ? { unreadCount: 1 } : { notifications: [item], nextCursor: null },
  })))
  render(<NotificationProvider user={user} onNavigate={vi.fn()}><NotificationBell onViewAll={vi.fn()} /><NotificationsPage /></NotificationProvider>)
}
afterEach(() => vi.unstubAllGlobals())

// Event deduplicates source areas; the renderer displays their user-facing labels.
test('requested changes show the reason and distinct affected-area labels in inbox and bell', async () => {
  const message = 'Community Fair safety review: Changes Requested (round 2). Keep exits clear and secure the cables. Affected areas: venue arrangement, technical arrangement, event details.'
  start('safety.review-decision', message, {
    eventId, eventName: 'Community Fair', recipientId: coordinator.id,
    decision: 'Changes Requested', round: 2,
    reason: 'Keep exits clear and secure the cables.',
    areas: ['venue arrangement', 'technical arrangement', 'event details'],
  })
  const inbox = screen.getByRole('region', { name: 'Notifications inbox' })
  await within(inbox).findByText('Community Fair')
  expect(within(inbox).getByText(message)).toBeInTheDocument()
  expect(within(inbox).getByText('Keep exits clear and secure the cables.')).toHaveClass('notification-reason')
  expect(within(inbox).getByText('Safety review round: 2')).toBeInTheDocument()
  expect(within(inbox).getByRole('link', { name: 'Open notification' })).toHaveAttribute('href', `/events/${eventId}`)
  expect(within(inbox).getByText('Affected areas: Venue arrangement, Technical / equipment arrangement, Event details')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Notifications, 1 unread' }))
  const bell = screen.getByRole('region', { name: 'Recent notifications' })
  expect(within(bell).getByText(message)).toBeInTheDocument()
  expect(within(bell).getByText('Keep exits clear and secure the cables.')).toBeInTheDocument()
  expect(within(bell).getByText('Affected areas: Venue arrangement, Technical / equipment arrangement, Event details')).toBeInTheDocument()
})

// Characterization, not new RED claims: the common renderer already supports
// these fields. Frozen producer wording is displayed verbatim, not regenerated.
test('submitted review shows the event name and date in its message with an event-details link', async () => {
  const message = 'Community Fair requires safety review (round 1). Proposed: 28 Oct 2026, 10:00 SGT – 28 Oct 2026, 12:00 SGT.'
  start('safety.review-submitted', message, {
    eventId, eventName: 'Community Fair', recipientId: officer.id, round: 1,
    startDateTime: '2026-10-28T10:00:00+08:00', endDateTime: '2026-10-28T12:00:00+08:00',
  }, officer)
  await screen.findByText(message)
  expect(screen.getByText('Community Fair')).toBeInTheDocument()
  expect(screen.getByText('28 Oct 2026, 10:00 SGT – 28 Oct 2026, 12:00 SGT')).toBeInTheDocument()
  expect(screen.getByText('Safety review round: 1')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Open notification' })).toHaveAttribute('href', `/events/${eventId}`)
})

test.each([
  { scenario: 'with optional remarks', reason: 'Keep the approved exit layout.' },
  { scenario: 'without optional remarks', reason: null },
])('approved review $scenario shows its decision and only supplied remarks', async ({ reason }) => {
  const message = reason
    ? 'Community Fair safety review: Approved (round 1). Keep the approved exit layout.'
    : 'Community Fair safety review: Approved (round 1).'
  start('safety.review-decision', message, {
    eventId, eventName: 'Community Fair', recipientId: coordinator.id,
    decision: 'Approved', round: 1, reason, areas: [],
  })
  await screen.findByText(message)
  expect(screen.getByText('Community Fair')).toBeInTheDocument()
  expect(screen.getByText('Safety review round: 1')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Open notification' })).toHaveAttribute('href', `/events/${eventId}`)
  if (reason) expect(screen.getByText(reason)).toHaveClass('notification-reason')
  else expect(document.querySelector('.notification-reason')).toBeNull()
})

test('rejected review shows the decision and recorded rejection reason', async () => {
  const message = 'Community Fair safety review: Rejected (round 1). Emergency access cannot be maintained.'
  start('safety.review-decision', message, {
    eventId, eventName: 'Community Fair', recipientId: coordinator.id,
    decision: 'Rejected', round: 1,
    reason: 'Emergency access cannot be maintained.', areas: [],
  })
  await screen.findByText(message)
  expect(screen.getByText('Community Fair')).toBeInTheDocument()
  expect(screen.getByText('Emergency access cannot be maintained.')).toHaveClass('notification-reason')
  expect(screen.getByRole('link', { name: 'Open notification' })).toHaveAttribute('href', `/events/${eventId}`)
})
