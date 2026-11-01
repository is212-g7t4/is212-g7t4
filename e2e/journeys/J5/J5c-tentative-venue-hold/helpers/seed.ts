import type { APIRequestContext } from '@playwright/test'
import { expect } from '@playwright/test'
import { authHeaders, createUnderReviewEvent, serviceUrl, users } from '../../../../helpers/stack'

export const VENUE_CAPACITY = 100

const venueServiceUrl = serviceUrl('venue', '')
const venueBookingServiceUrl = serviceUrl('venueBooking', '')
const availabilityServiceUrl = serviceUrl('venueAvailability', '')

/** Singapore wall-clock time as `YYYY-MM-DDTHH:mm`, `offsetMinutes` from now (the services read naive times as SGT). */
export function sgt(offsetMinutes = 0) {
  const shifted = new Date(Date.now() + offsetMinutes * 60_000)
  return shifted.toLocaleString('sv-SE', { timeZone: 'Asia/Singapore' }).replace(' ', 'T').slice(0, 16)
}

async function createVenue(api: APIRequestContext, name: string) {
  const created = await api.post(`${venueServiceUrl}/venues`, {
    headers: await authHeaders(users.venueStaff),
    data: {
      name, location: 'J5c fixture', capacity: String(VENUE_CAPACITY), facilities: ['Projector'],
      accessibility: 'Step-free access', supportedLayouts: ['Theatre'], status: 'Available',
      setupTimeMinutes: '0', turnaroundTimeMinutes: '0',
    },
  })
  expect(created.ok(), `create venue: ${created.status()} ${await created.text()}`).toBe(true)
  return (await created.json()).venue.id as string
}

export async function requestVenue(
  api: APIRequestContext, eventId: string, venueId: string, start: string, end: string,
) {
  return api.post(`${venueBookingServiceUrl}/booking-requests`, {
    headers: await authHeaders(users.coordinator),
    data: {
      eventId, venueId, coordinatorId: users.coordinator.id, requestedStartTime: start,
      requestedEndTime: end, requiredCapacity: 50, venueRequirements: '',
    },
  })
}

export async function placeHold(api: APIRequestContext, venueId: string, expiresAt: string, coordinatorId?: string) {
  return api.post(`${availabilityServiceUrl}/venue-holds`, {
    headers: await authHeaders(users.venueStaff),
    data: { venueId, expiresAt, setupTimeMinutes: 0, turnaroundTimeMinutes: 0, ...(coordinatorId ? { coordinatorId } : {}) },
  })
}

/**
 * One Under Review event spanning today to the day after tomorrow, and three unbuffered venues:
 * `held` (the journey places the hold), `booked` (already has a pending request, so a hold overlapping it is refused)
 * and `reminded` (holds expiring in just under 3 days, placed for the coordinator).
 */
export async function seedJ5c(api: APIRequestContext, runId: string) {
  const today = sgt(0).slice(0, 10)
  const lastDay = sgt(2 * 24 * 60).slice(0, 10)
  const eventId = await createUnderReviewEvent(api, `J5c Event ${runId}`, { start: `${today}T00:00`, end: `${lastDay}T23:00` })
  const heldVenueId = await createVenue(api, `J5c Venue held ${runId}`)
  const bookedVenueId = await createVenue(api, `J5c Venue booked ${runId}`)
  const remindedVenueId = await createVenue(api, `J5c Venue reminded ${runId}`)

  const bookedStart = sgt(30)
  const bookedEnd = sgt(90)
  const booking = await requestVenue(api, eventId, bookedVenueId, bookedStart, bookedEnd)
  expect(booking.ok(), `existing booking: ${booking.status()} ${await booking.text()}`).toBe(true)

  const reminderHold = await placeHold(api, remindedVenueId, sgt(2 * 24 * 60 + 23 * 60), users.coordinator.id)
  expect(reminderHold.ok(), `reminder hold: ${reminderHold.status()} ${await reminderHold.text()}`).toBe(true)

  return {
    eventId, heldVenueId, bookedVenueId, remindedVenueId, bookedEnd,
    reminderExpiry: (await reminderHold.json()).hold.expiresAt as string,
  }
}
