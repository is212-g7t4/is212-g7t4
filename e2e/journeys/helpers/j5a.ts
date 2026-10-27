import type { APIRequestContext } from '@playwright/test'
import { expect } from '@playwright/test'
import { createUnderReviewEvent, randomWindow } from './stack'

export const SETUP_MINUTES = 60
export const TURNAROUND_MINUTES = 60
export const VENUE_CAPACITY = 100

const venueServiceUrl = 'http://localhost:5006'
const venueBookingServiceUrl = 'http://localhost:5007'

/** A fixture venue with 60-minute setup and turnaround buffers, configured through the same composite call the venue form uses. */
export async function createBufferedVenue(api: APIRequestContext, name: string) {
  const profile = {
    name, location: 'J5a fixture', capacity: String(VENUE_CAPACITY), facilities: ['Projector'],
    accessibility: 'Step-free access', supportedLayouts: ['Theatre'], status: 'Available',
  }
  const created = await api.post(`${venueServiceUrl}/venues`, {
    data: { ...profile, setupTimeMinutes: '0', turnaroundTimeMinutes: '0' },
  })
  expect(created.ok(), `create venue: ${created.status()} ${await created.text()}`).toBe(true)
  const venueId = (await created.json()).venue.id as string

  const configured = await api.put(`${venueBookingServiceUrl}/venues/${venueId}`, {
    data: { ...profile, setupTimeMinutes: String(SETUP_MINUTES), turnaroundTimeMinutes: String(TURNAROUND_MINUTES) },
  })
  expect(configured.ok(), `configure buffers: ${configured.status()} ${await configured.text()}`).toBe(true)
  return venueId
}

/** Two Under Review events (so coordinators can request venues) plus a buffered venue, all on one far-future day. */
export async function seedJ5a(api: APIRequestContext, runId: string) {
  const window = randomWindow()
  const day = window.start.slice(0, 10)
  const venueName = `J5a Venue ${runId}`
  const venueId = await createBufferedVenue(api, venueName)
  const eventAId = await createUnderReviewEvent(api, `J5a Event A ${runId}`, window)
  const eventBId = await createUnderReviewEvent(api, `J5a Event B ${runId}`, window)
  return { day, venueName, venueId, eventAId, eventBId }
}
