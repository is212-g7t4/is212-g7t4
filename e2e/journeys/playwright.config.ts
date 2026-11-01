import { defineConfig, devices } from '@playwright/test'

// Real-stack journeys; the isolated runner starts its own stack, and CI runs a subset on it.
export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.ts',
  outputDir: process.env.E2E_OUTPUT_DIR ?? './test-results',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  // The equipment-requests page fans out to several services and takes ~20s on a populated database.
  timeout: 180_000,
  expect: { timeout: 60_000 },
  reporter: [['list'], ['html', { open: 'never', outputFolder: process.env.E2E_REPORT_DIR ?? './report' }]],
  use: {
    baseURL: process.env.FRONTEND_URL ?? 'http://localhost:5174',
    trace: 'on',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
