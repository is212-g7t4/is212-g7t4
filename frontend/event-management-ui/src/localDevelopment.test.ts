/** Local startup configuration only: Vite's actual loader, synthetic files, no APIs. */
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve } from 'node:path'
import { loadEnv } from 'vite'
import { afterEach, expect, it, vi } from 'vitest'

const publicConfig = resolve('.env.development')
const directories: string[] = []
afterEach(() => {
  vi.unstubAllEnvs()
  for (const directory of directories.splice(0)) rmSync(directory, { recursive: true, force: true })
})

function fixture() {
  expect(existsSync(publicConfig), 'public mode-specific endpoints must be repository-owned').toBe(true)
  const directory = mkdtempSync(resolve(tmpdir(), 'frontend-public-config-'))
  directories.push(directory)
  writeFileSync(resolve(directory, '.env.development'), readFileSync(publicConfig))
  return directory
}

it('loads the fifteen local Compose endpoints without an external launcher', () => {
  const env = loadEnv('development', fixture())
  const services = ['USER', 'EQUIPMENT', 'EVENT', 'COORDINATOR_ASSIGNMENT', 'REGISTRATION',
    'VENUE', 'VENUE_BOOKING', 'VENUE_AVAILABILITY', 'ATTENDEE_REGISTRATION',
    'EQUIPMENT_RESERVATION', 'EQUIPMENT_REQUEST', 'SAFETY_CHECK', 'SAFETY_CHECK_RECORD',
    'EVENT_WORKFLOW', 'NOTIFICATION']
  services.forEach((service, index) => {
    expect(env[`VITE_${service}_SERVICE_URL`]).toBe(`http://localhost:${5001 + index}`)
  })
})

it('uses mode defaults over generic files, with local-mode and process overrides still explicit', () => {
  const directory = fixture()
  writeFileSync(resolve(directory, '.env'), 'VITE_NOTIFICATION_SERVICE_URL=http://generic.invalid\n')
  writeFileSync(resolve(directory, '.env.local'), 'VITE_NOTIFICATION_SERVICE_URL=http://generic-local.invalid\n')
  expect(loadEnv('development', directory).VITE_NOTIFICATION_SERVICE_URL).toBe('http://localhost:5015')
  writeFileSync(resolve(directory, '.env.development.local'), 'VITE_NOTIFICATION_SERVICE_URL=http://mode-local.invalid\n')
  expect(loadEnv('development', directory).VITE_NOTIFICATION_SERVICE_URL).toBe('http://mode-local.invalid')
  vi.stubEnv('VITE_NOTIFICATION_SERVICE_URL', 'http://explicit-process.invalid')
  expect(loadEnv('development', directory).VITE_NOTIFICATION_SERVICE_URL).toBe('http://explicit-process.invalid')
})
