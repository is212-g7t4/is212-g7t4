/**
 * # SCRUM-173 — Receive Venue Disruption Notifications
 *
 * As an Event Coordinator, I want to receive an in-app notification when a venue booking for an event assigned to me is affected, so that I know that alternative arrangements are required.
 * AC1: Given a rejection is ready for notification, then the notification is addressed to the coordinator assigned to that event when the notification is created.
 * AC2: The notification contains the event name, affected venue, closure start/end, rejection reason, and a link to the venue rejection.
 * AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.
 *
 * ## Supporting test infrastructure
 * Pin mocked API origins and disable server reuse; no direct acceptance assertions.
 * Existing unrelated story browser settings are preserved.
 */
import { defineConfig, devices } from '@playwright/test'

// Backend ports the frontend falls back to. Pinned below so a developer's local
// .env cannot change where the app sends requests, which e2e/fixtures.ts mocks.
export const SERVICE_PORTS = {
  user: 5001,
  equipment: 5002,
  event: 5003,
  assignment: 5004,
  registration: 5005,
  venue: 5006,
  venueBooking: 5007,
  availability: 5008,
  attendeeRegistration: 5009,
  equipmentReservation: 5010,
  safetyCheck: 5012,
  eventWorkflow: 5014,
  notification: 5015,
} as const

const url = (port: number) => `http://localhost:${port}`

export default defineConfig({
  testDir: '.',
  outputDir: '../test-results',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never', outputFolder: '../playwright-report' }]] : 'list',
  use: {
    baseURL: 'http://localhost:5174',
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'npm run dev',
    cwd: '..',
    url: 'http://localhost:5174',
    reuseExistingServer: false,
    env: {
      VITE_NOTIFICATION_SERVICE_URL: url(SERVICE_PORTS.notification),
      VITE_USER_SERVICE_URL: url(SERVICE_PORTS.user),
      VITE_EQUIPMENT_SERVICE_URL: url(SERVICE_PORTS.equipment),
      VITE_EVENT_SERVICE_URL: url(SERVICE_PORTS.event),
      VITE_COORDINATOR_ASSIGNMENT_SERVICE_URL: url(SERVICE_PORTS.assignment),
      VITE_REGISTRATION_SERVICE_URL: url(SERVICE_PORTS.registration),
      VITE_VENUE_SERVICE_URL: url(SERVICE_PORTS.venue),
      VITE_VENUE_BOOKING_SERVICE_URL: url(SERVICE_PORTS.venueBooking),
      VITE_VENUE_AVAILABILITY_SERVICE_URL: url(SERVICE_PORTS.availability),
      VITE_ATTENDEE_REGISTRATION_SERVICE_URL: url(SERVICE_PORTS.attendeeRegistration),
      VITE_EQUIPMENT_RESERVATION_SERVICE_URL: url(SERVICE_PORTS.equipmentReservation),
      VITE_SAFETY_CHECK_SERVICE_URL: url(SERVICE_PORTS.safetyCheck),
      VITE_EVENT_WORKFLOW_SERVICE_URL: url(SERVICE_PORTS.eventWorkflow),
    },
  },
})
