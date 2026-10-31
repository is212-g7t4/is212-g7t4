import type { APIRequestContext, Page } from '@playwright/test'
import { expect } from '@playwright/test'
import {
  approveAllEquipment,
  authHeaders,
  createUnderReviewEvent,
  randomWindow,
  requestEquipment,
  serviceUrl,
  users,
} from '../../../helpers/stack'

export const TABLE_ID = '2ebcd2d3-636b-48e7-8784-ddef1d2d550c'
export const TABLE_NAME = '6-foot folding table'
export const TABLE_STOCK = 50

async function expectOk(
  response: { ok(): boolean; status(): number; text(): Promise<string> },
  operation: string,
) {
  expect(response.ok(), `${operation}: ${response.status()} ${await response.text()}`).toBe(true)
}

export async function createJ3Venue(api: APIRequestContext, name: string) {
  const response = await api.post(serviceUrl('venue', '/venues'), {
    headers: await authHeaders(users.venueStaff),
    data: {
      name,
      location: 'J3 E2E fixture',
      capacity: '100',
      facilities: ['Projector'],
      accessibility: 'Step-free access',
      supportedLayouts: ['Theatre'],
      status: 'Available',
      setupTimeMinutes: '0',
      turnaroundTimeMinutes: '0',
    },
  })
  await expectOk(response, 'create J3 venue')
  const body: { venue?: { id?: unknown } } = await response.json()
  if (typeof body.venue?.id !== 'string') throw new Error('Venue Service did not return the created venue ID.')
  return body.venue.id
}

export async function createJ3Booking(
  api: APIRequestContext,
  eventId: string,
  venueId: string,
  window: { start: string; end: string },
  venueRequirements = 'J3 safety arrangement fixture',
) {
  const response = await api.post(serviceUrl('venueBooking', '/booking-requests'), {
    headers: await authHeaders(users.coordinator),
    data: {
      eventId,
      venueId,
      requestedStartTime: window.start,
      requestedEndTime: window.end,
      requiredCapacity: 50,
      venueRequirements,
    },
  })
  await expectOk(response, 'create J3 venue booking')
  const body: { id?: unknown } = await response.json()
  if (typeof body.id !== 'string') throw new Error('Venue Booking Service did not return the created booking ID.')
  return body.id
}

export async function approveJ3Booking(api: APIRequestContext, bookingId: string) {
  await expectOk(await api.patch(
    serviceUrl('venueBooking', `/booking-requests/${bookingId}/review`),
    { headers: await authHeaders(users.venueStaff), data: { status: 'Approved' } },
  ), 'approve J3 venue booking')
}

export async function approveJ3Event(api: APIRequestContext, eventId: string) {
  await expectOk(await api.patch(serviceUrl('event', `/events/${eventId}/progress`), {
    headers: await authHeaders(users.coordinator),
    data: { status: 'Approved', actionDetails: 'J3 arrangements are ready for safety review.' },
  }), 'approve J3 event')
}

export async function submitJ3SafetyCheck(api: APIRequestContext, eventId: string) {
  await expectOk(await api.post(serviceUrl('safety', '/safety-checks'), {
    headers: await authHeaders(users.coordinator),
    data: {
      eventId,
      equipmentPlacementNotes: 'J3 equipment is placed clear of the exits.',
      crowdMovementNotes: 'J3 attendees use the marked entry and exit routes.',
    },
  }), 'submit J3 safety check')
}

export async function createJ3ReadyEvent(
  api: APIRequestContext,
  eventName: string,
  venueId: string,
  window: { start: string; end: string },
) {
  const eventId = await createUnderReviewEvent(api, eventName, window)
  const bookingId = await createJ3Booking(api, eventId, venueId, window)
  await approveJ3Booking(api, bookingId)
  await requestEquipment(api, eventId, TABLE_ID, 2)
  await approveAllEquipment(api, eventId)
  await approveJ3Event(api, eventId)
  return { eventId, bookingId }
}

export async function approveVenueRequestAsStaff(staff: Page, eventName: string, venueName: string) {
  let latestResponse: import('@playwright/test').Response | undefined
  const recordResponse = (response: import('@playwright/test').Response) => {
    if (new URL(response.url()).pathname === '/booking-requests'
      && response.request().method() === 'GET') latestResponse = response
  }
  staff.on('response', recordResponse)
  try {
    for (let attempt = 0; attempt < 3; attempt++) {
      if (attempt === 0) await staff.goto('/venue-requests')
      else await staff.getByRole('button', { name: 'Refresh requests' }).click()
      await expect(staff.getByRole('button', { name: 'Refresh requests' })).toBeEnabled()
      const alert = staff.getByRole('alert')
      if (!await alert.isVisible()) break
      const status = latestResponse?.status()
      const failure = `Venue request queue load failed (HTTP ${status ?? 'unknown'}): ${await alert.innerText()}`
      if (status === undefined || ![502, 503, 504].includes(status) || attempt === 2) throw new Error(failure)
      console.warn(`${failure} Retrying through Refresh requests.`)
    }
  } finally {
    staff.off('response', recordResponse)
  }

  const row = staff.getByRole('region', { name: `${eventName} venue requests` })
    .getByRole('row').filter({ hasText: venueName })
  await expect(row.getByRole('button', { name: 'Review', exact: true })).toBeVisible()
  await row.getByRole('button', { name: 'Review' }).click()
  await staff.getByRole('dialog').getByRole('button', { name: 'Approve', exact: true }).click()
  await expect(staff.getByText('Venue request approved.')).toBeVisible()
  await expect(row).toContainText('Approved')
}

export async function openJ3SafetyEvent(officer: Page, eventName: string) {
  let latestResponse: import('@playwright/test').Response | undefined
  const recordResponse = (response: import('@playwright/test').Response) => {
    if (new URL(response.url()).pathname === '/safety-checks/queue'
      && response.request().method() === 'GET') latestResponse = response
  }
  officer.on('response', recordResponse)
  try {
    for (let attempt = 0; attempt < 3; attempt++) {
      const [response] = await Promise.all([
        officer.waitForResponse((candidate) =>
          new URL(candidate.url()).pathname === '/safety-checks/queue'
          && candidate.request().method() === 'GET'),
        attempt === 0
          ? officer.goto('/safety-checks')
          : officer.getByRole('button', { name: 'Refresh safety checks' }).click(),
      ])
      latestResponse = response
      if (response.ok()) break
      const failure = `Safety queue returned HTTP ${response.status()}: ${await response.text()}`
      if (![502, 503, 504].includes(response.status()) || attempt === 2) throw new Error(failure)
      console.warn(`${failure} Retrying through Refresh safety checks.`)
      await expect(officer.getByRole('button', { name: 'Refresh safety checks' })).toBeEnabled()
    }
  } finally {
    officer.off('response', recordResponse)
  }

  const eventCard = officer.getByRole('button').filter({ hasText: eventName })
  await expect(eventCard, `Safety queue response: ${latestResponse?.status() ?? 'unknown'}`).toHaveCount(1)
  await eventCard.click()
}

export function bookingServiceUrl(path: string) {
  return `http://localhost:5007${path}`
}

export function equipmentRequestServiceUrl(path: string) {
  return `http://localhost:5011${path}`
}
