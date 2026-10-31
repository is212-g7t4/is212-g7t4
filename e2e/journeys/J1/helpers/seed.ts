import type { APIRequestContext } from '@playwright/test'
import { expect } from '@playwright/test'
import { authHeaders, serviceUrl, users } from '../../../helpers/stack'

const venueServiceUrl = serviceUrl('venue', '')

export async function createJ1Venue(api: APIRequestContext, runId: string) {
  const venueName = `J1 Venue ${runId}`
  const response = await api.post(`${venueServiceUrl}/venues`, {
    headers: await authHeaders(users.venueStaff),
    data: {
      name: venueName,
      location: 'J1 E2E fixture',
      capacity: '100',
      facilities: ['Projector'],
      accessibility: 'Step-free access',
      supportedLayouts: ['Theatre'],
      status: 'Available',
      setupTimeMinutes: '0',
      turnaroundTimeMinutes: '0',
    },
  })
  expect(response.ok(), `create venue: ${response.status()} ${await response.text()}`).toBe(true)
  return { venueName }
}
