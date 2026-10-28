/**
 * SCRUM-49 — Event Change and Modification Notifications
 * As an Event Organiser and Event Coordinator, I want to receive notifications about
 * event changes that affect me, so that I can respond to changes promptly.
 * AC1: Given an Event Organiser submits a change request, the system sends an in-app
 * notification to the Event Coordinator with the event name, proposed changes, and
 * a link to review the request.
 * AC2: Given an approval or rejection of a change request is successfully recorded,
 * the Event Organiser receives an in-app notification with the event name, decision,
 * and reason if rejected.
 * AC3: Given an event is cancelled or rejected, the system sends an in-app notification to both
 * the Event Coordinator and Event Organiser confirming cancellation or rejection respectively with event name.
 *
 * AC1 case 2 only: real App, inbox, destination allowlist, request page and HTTP
 * adapters in jsdom; fetch, user discovery and unrelated venue reminders doubled.
 * Synthetic HTTP fixtures mirror the Workflow change-request list contract and
 * agreed SCRUM-49 notification envelope. Fixed dates are display data, not expiry.
 * Proves exact-request navigation/highlighting and existing controls, not backend
 * recipient/content generation, authorization enforcement, persistence or delivery.
 * AC2/AC3 producer/consumer checks belong to backend story tests. Stale-link/access
 * edge cases, exhaustive testing and real-browser journeys are deferred.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { fetchUsers } from './features/user/users'
import type { EventChangeRequest } from './features/event/changeRequests'
import type { InboxItem } from './features/notifications/notifications'
import type { User } from './types'

vi.mock('./features/user/users', () => ({ fetchUsers: vi.fn() }))
vi.mock('./features/venue/venueHolds', () => ({ fetchHoldReminders: vi.fn(async () => []) }))

const eventId = '30000000-0000-0000-0000-000000000001'
const otherEventId = '30000000-0000-0000-0000-000000000002'
const firstId = '40000000-0000-0000-0000-000000000001'
const secondId = '40000000-0000-0000-0000-000000000002'
const coordinator: User = { id: '10000000-0000-0000-0000-000000000001', username: 'Assigned coordinator', role: 'Event Coordinator', email: '', organization: '' }
// Event Workflow GET /change-requests returns pending rows with their current event.
const request = (id: string, attendance: string): EventChangeRequest => ({
  id, eventId, proposedChanges: { expectedAttendance: attendance }, status: 'Pending Review',
  requestedAt: '2026-10-28T01:00:00Z', requestedBy: '10000000-0000-0000-0000-000000000002',
  reason: `Capacity adjustment to ${attendance}`, reviewedBy: null, reviewedAt: null, rejectionReason: null,
  event: { id: eventId, eventName: 'Community Fair', description: '', purpose: '',
    preferredStartDate: '2026-11-01T09:00:00+08:00', preferredEndDate: '2026-11-01T12:00:00+08:00',
    expectedAttendance: '30', venueRequirements: '', accessibilityNeeds: '', equipmentRequirements: '', registrationNeeds: '',
    status: 'Approved', submittedAt: null, coordinatorId: coordinator.id, decision: null, decisionHistory: [], actionDetails: '', actionHistory: [],
  },
})
const message = 'Change requested for Community Fair. Proposed changes: Expected Attendance: 60.'
const notification: InboxItem = {
  id: '50000000-0000-0000-0000-000000000001', eventId, type: 'event.change-request-submitted',
  createdAt: '2026-10-28T01:00:00Z', readAt: null,
  payload: { message, details: { eventName: 'Community Fair', eventId, changeRequestId: secondId, proposedChanges: { expectedAttendance: '60' } },
    destination: { kind: 'change-request-review', eventId, changeRequestId: secondId } },
}
const response = (body: unknown) => ({ ok: true, json: async () => body }) as Response
let unexpected: string[]
let http: ReturnType<typeof vi.fn>

beforeEach(() => {
  unexpected = []
  vi.mocked(fetchUsers).mockResolvedValue([coordinator])
  vi.stubGlobal('localStorage', { getItem: () => coordinator.id, setItem: vi.fn() })
  window.history.replaceState({}, '', '/notifications')
  http = vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = new URL(input)
    if (url.pathname === '/notifications/unread-count') return response({ unreadCount: 1 })
    if (url.pathname === '/notifications') return response({ notifications: [notification], nextCursor: null })
    if (url.pathname === `/notifications/${notification.id}` && init.method === 'PATCH') {
      return response({ notification: { ...notification, readAt: '2026-10-28T01:01:00Z' } })
    }
    if (url.pathname === '/change-requests' && url.searchParams.get('coordinatorId') === coordinator.id) {
      const first = request(firstId, '45')
      return response({ changeRequests: [{ ...first, eventId: otherEventId, event: { ...first.event, id: otherEventId, eventName: 'Unrelated Fair' } }, request(secondId, '60')] })
    }
    unexpected.push(`${init.method ?? 'GET'} ${input}`)
    throw new Error(`Unmocked HTTP request: ${input}`)
  })
  vi.stubGlobal('fetch', http)
})
afterEach(() => {
  expect(unexpected, 'All HTTP must be explicitly doubled; no shared services').toEqual([])
  vi.unstubAllGlobals()
  window.history.replaceState({}, '', '/')
})

describe('SCRUM-49 AC1 — direct request review', () => {
  it('Given two pending requests, When the second request notification is clicked, Then only that request is highlighted with review controls', async () => {
    // Given: pending requests for two events; the alert identifies the second.
    // Event's submission contract permits only one pending request per event.
    render(<App />)
    expect(await screen.findByText(message)).toBeInTheDocument()
    // When: follow the actual inbox link through mark-read and App routing.
    const link = screen.getByRole('link', { name: 'Open notification' })
    expect(link).toHaveAttribute('href', `/change-requests?event=${eventId}&request=${secondId}`)
    await userEvent.click(link)
    // Then: do not silently choose the first request or merely open the whole queue.
    const selected = (await screen.findByText('Selected request')).closest('article')!
    expect(window.location.pathname + window.location.search).toBe(`/change-requests?event=${eventId}&request=${secondId}`)
    expect(screen.getAllByText('Selected request')).toHaveLength(1)
    expect(within(selected).getByRole('heading', { name: 'Community Fair' })).toBeInTheDocument()
    expect(selected).toHaveAttribute('aria-current', 'true')
    expect(within(selected).getByText('60')).toBeInTheDocument()
    expect(within(selected).queryByText('45')).not.toBeInTheDocument()
    expect(within(selected).getByRole('button', { name: 'Approve changes' })).toBeEnabled()
    expect(within(selected).getByRole('button', { name: 'Reject changes' })).toBeEnabled()
    expect(screen.getByText('45')).toBeInTheDocument()
    expect(http).toHaveBeenCalledWith(`http://localhost:5014/change-requests?coordinatorId=${coordinator.id}`, undefined)
  })
})
