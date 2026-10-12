import { test as base, expect } from '@playwright/test'
import type { Page, Route } from '@playwright/test'
import { SERVICE_PORTS } from './playwright.config'

// Payload shapes mirror the backend serializers (snake_case users, camelCase events).
export const users = {
  organiser: { user_id: 'u-organiser', username: 'Olivia Lim', email: 'olivia@example.com', role: 'Event Organiser', organization: 'Org A' },
  manager: { user_id: 'u-manager', username: 'Alice Tan', email: 'alice@example.com', role: 'Event Coordinator Lead', organization: 'Org A' },
  coordinator: { user_id: 'u-coord', username: 'Carl Ng', email: 'carl@example.com', role: 'Event Coordinator', organization: 'Org A' },
  venueStaff: { user_id: '00000000-0000-0000-0000-0000000000aa', username: 'Vera Koh', email: 'vera@example.com', role: 'Venue Staff', organization: 'Org A' },
  techSupport: { user_id: '00000000-0000-0000-0000-0000000000bb', username: 'Wei Chen', email: 'wei@example.com', role: 'Technical Support', organization: 'Org A' },
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

export const asUser = (page: Page, userId: string) =>
  page.addInitScript((id) => localStorage.setItem('activeUserId', id), userId)
