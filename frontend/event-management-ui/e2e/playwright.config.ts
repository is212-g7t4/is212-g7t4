import { defineConfig, devices } from '@playwright/test'

// Backend ports the frontend falls back to. Pinned below so a developer's local
// .env cannot change where the app sends requests, which e2e/fixtures.ts mocks.
export const SERVICE_PORTS = {
  user: 5001,
  event: 5003,
  assignment: 5004,
  registration: 5005,
  venue: 5006,
  availability: 5008,
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
    reuseExistingServer: !process.env.CI,
    env: {
      VITE_USER_SERVICE_URL: url(SERVICE_PORTS.user),
      VITE_EVENT_SERVICE_URL: url(SERVICE_PORTS.event),
      VITE_COORDINATOR_ASSIGNMENT_SERVICE_URL: url(SERVICE_PORTS.assignment),
      VITE_REGISTRATION_SERVICE_URL: url(SERVICE_PORTS.registration),
      VITE_VENUE_SERVICE_URL: url(SERVICE_PORTS.venue),
      VITE_VENUE_AVAILABILITY_SERVICE_URL: url(SERVICE_PORTS.availability),
    },
  },
})
