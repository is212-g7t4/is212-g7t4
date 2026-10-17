import { test as base, expect } from '@playwright/test'
import type { Page, Route } from '@playwright/test'
import { SERVICE_PORTS } from './playwright.config'

// Payload shapes mirror the backend serializers (snake_case users, camelCase events).
export const users = {
  organiser: { user_id: 'u-organiser', username: 'Olivia Lim', email: 'olivia@example.com', role: 'Event Organiser', organization: 'Org A' },
  lead: { user_id: 'u-lead', username: 'Alice Tan', email: 'alice@example.com', role: 'Event Coordinator Lead', organization: 'Org A' },
  coordinator: { user_id: 'u-coord', username: 'Carl Ng', email: 'carl@example.com', role: 'Event Coordinator', organization: 'Org A' },
  venueStaff: { user_id: '00000000-0000-0000-0000-0000000000aa', username: 'Vera Koh', email: 'vera@example.com', role: 'Venue Staff', organization: 'Org A' },
  techSupport: { user_id: '00000000-0000-0000-0000-0000000000bb', username: 'Wei Chen', email: 'wei@example.com', role: 'Technical Support', organization: 'Org A' },
  safetyOfficer: { user_id: '00000000-0000-0000-0000-0000000000cc', username: 'Nurul Huda', email: 'nurul@example.com', role: 'Safety Officer', organization: 'Org A' },
  attendee: { user_id: 'u-attendee', username: 'Adam Yeo', email: 'adam@example.com', role: 'Attendee', organization: 'Org B' },
}
export const allUsers = Object.values(users)

export const venues = [
  { id: '00000000-0000-0000-0000-000000000001', name: 'Grand Hall', location: 'Level 1', capacity: 200, facilities: ['Projector', 'Stage'], accessibility: 'Step-free access', supportedLayouts: ['Theatre'], status: 'Available' },
  { id: '00000000-0000-0000-0000-000000000002', name: 'Meeting Room', location: 'Level 2', capacity: 12, facilities: ['Whiteboard'], accessibility: 'Lift access', supportedLayouts: ['Boardroom'], status: 'Available' },
]

export function makeEvent(overrides: Record<string, unknown> = {}) {
  return {
    id: 'evt-001', eventName: 'Tech Conference', description: 'A conference', purpose: 'Networking',
    preferredStartDate: '2026-12-01T09:00', preferredEndDate: '2026-12-01T17:00', expectedAttendance: '100',
    venueRequirements: 'Stage', accessibilityNeeds: 'Ramp', equipmentRequirements: 'Mics',
    registrationNeeds: 'Open', status: 'Submitted', submittedAt: '2026-11-01T02:00:00+00:00',
    coordinatorId: users.coordinator.user_id, decision: null, decisionHistory: [],
    actionDetails: '', actionHistory: [], ...overrides,
  }
}

const port = (p: number) => `http://localhost:${p}`
const CORS = { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': '*' }
export const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: 'application/json', headers: CORS, body: JSON.stringify(body) })

// Every backend call is intercepted. Anything a test did not mock is recorded and
// fails the test, so a new unmocked request cannot slip through silently.
export const test = base.extend<{ mockApi: (page: Page) => Promise<void>; unmocked: string[] }>({
  unmocked: async ({}, use) => {
    const calls: string[] = []
    await use(calls)
    expect(calls, 'requests to services with no mock').toEqual([])
  },
  mockApi: async ({ unmocked }, use) => {
    await use(async (page) => {
      for (const p of Object.values(SERVICE_PORTS)) {
        await page.route(`${port(p)}/**`, (route) => {
          if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers: CORS })
          unmocked.push(`${route.request().method()} ${route.request().url()}`)
          return route.abort()
        })
      }
      // App-shell poll that runs on every page for coordinators; tests override it to show an alert.
      await mock(page, 'availability', '/venue-holds/reminders', (route) => json(route, { reminders: [] }))
      // Booking forms need active holds to determine whether a venue is selectable.
      await mock(page, 'availability', '/venue-holds', (route) => json(route, { holds: [] }))
      // Safety Officer event details read their consolidated review context
      // before rendering the decision controls.
      await page.route(
        (url) => url.origin === port(SERVICE_PORTS.safetyCheck)
          && /^\/safety-checks\/[^/]+\/review$/.test(url.pathname),
        (route) => json(route, {
          event: makeEvent({ status: 'Pending Safety Check' }),
          safetyCheck: {
            id: 'review-round', eventId: '', roundNumber: 1, submittedBy: '',
            submittedAt: '', equipmentPlacementNotes: null, crowdMovementNotes: null,
            status: 'Pending', decidedBy: null, decidedAt: null, remarks: null,
            withdrawnAt: null, withdrawnBy: null, withdrawalReason: null, flags: [],
          },
          venues: [], equipment: [], history: [],
        }),
      )
      // Venue Staff detail pages always check whether existing bookings conflict
      // under the venue's buffer rules. Individual tests can register a later
      // route when they need to display a conflict.
      await page.route(
        (url) => url.origin === port(SERVICE_PORTS.venueBooking)
          && /^\/venues\/[^/]+\/legacy-conflicts$/.test(url.pathname),
        (route) => {
          const venueId = route.request().url().split('/').at(-2)
          return json(route, { venueId, conflictCount: 0, conflicts: [] })
        },
      )
    })
  },
})
export { expect }

// Registered after mockApi, so Playwright tries these first (last route wins).
// Matches on service origin + exact path; the handler can inspect query/body.
export function mock(page: Page, service: keyof typeof SERVICE_PORTS, path: string, handler: (route: Route) => unknown) {
  return page.route((url) => url.origin === port(SERVICE_PORTS[service]) && url.pathname === path, (route) => {
    if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers: CORS })
    return handler(route)
  })
}

// An event's venue is its approved VenueBooking, read from Venue Availability.
export function mockApprovedVenue(page: Page, eventId: string, venueId = venues[0].id) {
  return mock(page, 'availability', `/events/${eventId}/venue-bookings`, (route) => json(route, {
    bookings: [{ id: `booking-${eventId}`, eventId, venueId, status: 'Approved', requestedStartTime: '2099-11-10T09:00:00' }],
  }))
}

// SCRUM-149: an Approved event an Event Coordinator owns now renders the
// submit-for-safety-check panel, which reads its readiness on mount. Any test
// that opens such an event needs this, even if safety isn't what it's testing.
export function mockSafetyReadiness(
  page: Page,
  readiness: Record<string, unknown> = {},
) {
  return mock(page, 'safetyCheck', '/safety-checks/readiness', (route) => json(route, {
    ready: true, eventStatus: 'Approved', outstanding: [], openSafetyCheck: null, ...readiness,
  }))
}

// SCRUM-162: the Safety Officer's queue, built by Safety Check Service. Pass
// events in the order the service would return them (nearest first); any
// overrides (venues, roundNumber, resubmission) go on the event itself.
export function mockSafetyQueue(page: Page, events: () => Record<string, unknown>[]) {
  return mock(page, 'safetyCheck', '/safety-checks/queue', (route) => json(route, {
    events: events().map((event) => ({
      eventId: event.id,
      eventName: event.eventName,
      preferredStartDate: event.preferredStartDate,
      preferredEndDate: event.preferredEndDate,
      expectedAttendance: event.expectedAttendance,
      venues: event.venues ?? [{ id: venues[0].id, name: venues[0].name }],
      safetyCheckId: `record-${event.id}`,
      submittedAt: event.safetySubmittedAt ?? '2026-11-01T02:30:00+00:00',
      roundNumber: event.roundNumber ?? 1,
      resubmission: Number(event.roundNumber ?? 1) > 1,
    })),
  }))
}

export const asUser = (page: Page, userId: string) =>
  page.addInitScript((id) => localStorage.setItem('activeUserId', id), userId)
