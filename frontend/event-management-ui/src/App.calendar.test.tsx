/**
 * # SCRUM-173 — Receive Venue Disruption Notifications
 *
 * As an Event Coordinator, I want to receive an in-app notification when a venue booking for an event assigned to me is affected, so that I know that alternative arrangements are required.
 * AC1: Given a rejection is ready for notification, then the notification is addressed to the coordinator assigned to that event when the notification is created.
 * AC2: The notification contains the event name, affected venue, closure start/end, rejection reason, and a link to the venue rejection.
 * AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.
 *
 * ## AC groups and layer
 * Cross-ticket regressions / fixture infrastructure: preserve original story ownership.
 * Only notification-specific additions support SCRUM-173 AC2; existing cases are not reattributed.
 * AC1 recipient selection is backend evidence, not inferred from these mocks.
 * AC2 content/navigation; AC3 supporting UI isolation/recovery.
 * FIRST: synthetic independent fixtures, controlled I/O/clocks, automatic assertions.
 * Historical tests are retrospective; no blanket historical TDD claim.
 */
/**
 * # Existing calendar application seam (calendar story regression).
 * Scenarios: internal and restricted profiles see their existing route/navigation.
 * SCRUM-173 infrastructure adaptation only: mock the newly global own-inbox API
 * so these calendar unit cases perform no notification network I/O.
 * No direct notification AC or persistence claim is assigned to these cases.
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import App from './App'
import { fetchUsers } from './features/user/users'
import type { Role } from './types'
import { signInAs } from './test/session'
// SCRUM-173 supporting shell fixture: no real inbox I/O in calendar unit tests.
vi.mock('./features/notifications/notifications', async (original) => ({
  ...await original<typeof import('./features/notifications/notifications')>(),
  notificationApi: vi.fn(async (path: string) => path.includes('unread-count') ? { unreadCount: 0 } : { notifications: [], nextCursor: null }),
}))
vi.mock('./features/user/users', () => ({ fetchUsers: vi.fn() }))
vi.mock('./features/venue/venues', () => ({
  fetchVenues: vi.fn().mockResolvedValue([]),
}))
beforeEach(() => {
  // No real network: a live stack would answer 401 to the fake token and end the session.
  vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))
  window.history.replaceState({}, '', '/venue-availability')
})
test.each([
  'Event Coordinator',
  'Venue Staff',
  'Technical Support',
  'Event Organiser',
  'Attendee',
] as Role[])('calendar direct route and nav reflect %s', async (role) => {
  const user = { id: 'id', username: 'test', email: '', organization: '', role }
  vi.mocked(fetchUsers).mockResolvedValue([user])
  signInAs(user)
  render(<App />)
  expect(screen.getByRole('heading', { name: 'Venue availability calendar' })).toBeInTheDocument()
  await screen.findByText(`Signed in as test — ${role}`)
  expect(document.title).toBe('Venue availability calendar · ConnectSphere')
  if (['Event Organiser', 'Attendee'].includes(role)) {
    expect(screen.getByRole('alert')).toHaveTextContent('Permission denied')
    expect(
      screen.queryByRole('button', { name: /Venue availability calendar/ }),
    ).not.toBeInTheDocument()
  } else {
    expect(
      screen.getByRole('region', { name: 'Venue availability calendar' }),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Venue availability calendar/ }))
    expect(window.location.pathname).toBe('/venue-availability')
  }
})
