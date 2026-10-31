import { expect } from '@playwright/test'
import type { APIRequestContext, APIResponse, Page } from '@playwright/test'
import { authHeaders, createUnderReviewEvent, randomWindow, serviceUrl, users } from '../../../helpers/stack'

type Booking = Record<string, unknown> & {
  id: string
  eventId: string
  venueId: string
  status: string
  closureRejection?: { closureId: string; reason: string }
}

export function j4Names(path: 'a' | 'b', runId: string) {
  return {
    eventName: `J4${path} Event main ${runId}`,
    otherEventName: `J4${path} Event unrelated ${runId}`,
    closedVenueName: `J4${path} Venue closed ${runId}`,
    keptVenueName: `J4${path} Venue unaffected ${runId}`,
    alternativeVenueName: `J4${path} Venue alternative ${runId}`,
  }
}

export function j4Scope(names: ReturnType<typeof j4Names>) {
  return {
    eventNames: [names.eventName, names.otherEventName],
    venueNames: [names.closedVenueName, names.keptVenueName, names.alternativeVenueName],
  }
}

async function expectStatus(response: APIResponse, status: number, operation: string) {
  expect(response.status(), `${operation}: ${await response.text()}`).toBe(status)
}

async function createVenue(api: APIRequestContext, name: string) {
  const response = await api.post(serviceUrl('venue', '/venues'), {
    headers: await authHeaders(users.venueStaff),
    data: {
      name, location: 'J4 E2E fixture', capacity: '100', facilities: ['Projector'],
      accessibility: 'Step-free access', supportedLayouts: ['Theatre'], status: 'Available',
      setupTimeMinutes: '0', turnaroundTimeMinutes: '0',
    },
  })
  await expectStatus(response, 201, 'create J4 venue')
  const id = (await response.json()).venue?.id
  if (typeof id !== 'string') throw new Error('Venue Service did not return the created venue ID.')
  return id
}

async function createApprovedBooking(
  api: APIRequestContext, eventId: string, venueId: string, start: string, end: string,
) {
  const response = await api.post(serviceUrl('venueBooking', '/booking-requests'), {
    headers: await authHeaders(users.coordinator),
    data: {
      eventId, venueId, requestedStartTime: start, requestedEndTime: end,
      requiredCapacity: 50, venueRequirements: 'J4 independent venue arrangement',
    },
  })
  await expectStatus(response, 201, 'create J4 booking')
  const id = (await response.json()).id
  if (typeof id !== 'string') throw new Error('Venue Booking Service did not return the created booking ID.')
  await expectStatus(await api.patch(serviceUrl('venueBooking', `/booking-requests/${id}/review`), {
    headers: await authHeaders(users.venueStaff), data: { status: 'Approved' },
  }), 200, 'approve J4 fixture booking')
  return id
}

export async function readEvent(api: APIRequestContext, eventId: string): Promise<Record<string, unknown>> {
  const response = await api.get(serviceUrl('event', `/events/${eventId}`), {
    headers: await authHeaders(users.coordinator),
  })
  await expectStatus(response, 200, 'read J4 event')
  return response.json()
}

export async function readBookings(api: APIRequestContext, eventId: string): Promise<Booking[]> {
  const response = await api.get(serviceUrl('venueBooking', `/events/${eventId}/booking-requests`), {
    headers: await authHeaders(users.coordinator),
  })
  await expectStatus(response, 200, 'read J4 bookings')
  const body = await response.json()
  if (!Array.isArray(body.bookings) || !body.bookings.every((booking: Booking) => typeof booking.id === 'string'))
    throw new Error('Venue Booking Service did not return a booking list.')
  return body.bookings
}

export async function seedJ4(api: APIRequestContext, names: ReturnType<typeof j4Names>) {
  const window = randomWindow()
  const day = window.start.slice(0, 10)
  const start = `${day}T10:00`, end = `${day}T12:00`
  const closureStart = `${day}T10:30`, closureEnd = `${day}T11:30`
  const closedVenueId = await createVenue(api, names.closedVenueName)
  const keptVenueId = await createVenue(api, names.keptVenueName)
  const alternativeVenueId = await createVenue(api, names.alternativeVenueName)
  const eventId = await createUnderReviewEvent(api, names.eventName, window)
  const otherEventId = await createUnderReviewEvent(api, names.otherEventName, window)
  const affectedBookingId = await createApprovedBooking(api, eventId, closedVenueId, start, end)
  const keptBookingId = await createApprovedBooking(api, eventId, keptVenueId, start, end)
  const otherBookingId = await createApprovedBooking(
    api, otherEventId, closedVenueId, `${day}T14:00`, `${day}T16:00`,
  )
  const [eventBefore, otherEventBefore, bookingsBefore, otherBookingsBefore] = await Promise.all([
    readEvent(api, eventId), readEvent(api, otherEventId),
    readBookings(api, eventId), readBookings(api, otherEventId),
  ])
  const keptBookingBefore = bookingsBefore.find(booking => booking.id === keptBookingId)
  expect(bookingsBefore).toHaveLength(2)
  expect(otherBookingsBefore).toHaveLength(1)
  expect(keptBookingBefore).toBeDefined()
  return {
    ...names, day, start, end, closureStart, closureEnd, closedVenueId, keptVenueId, alternativeVenueId,
    eventId, otherEventId, affectedBookingId, keptBookingId, otherBookingId,
    eventBefore, otherEventBefore, keptBookingBefore, otherBookingsBefore,
    reason: 'J4 emergency maintenance: the west entrance is unsafe.',
  }
}

export type J4Fixture = Awaited<ReturnType<typeof seedJ4>>

export async function expectPreserved(api: APIRequestContext, fixture: J4Fixture) {
  const [event, otherEvent, bookings, otherBookings] = await Promise.all([
    readEvent(api, fixture.eventId), readEvent(api, fixture.otherEventId),
    readBookings(api, fixture.eventId), readBookings(api, fixture.otherEventId),
  ])
  expect(event).toEqual(fixture.eventBefore)
  expect(otherEvent).toEqual(fixture.otherEventBefore)
  expect(bookings.find(booking => booking.id === fixture.keptBookingId)).toEqual(fixture.keptBookingBefore)
  expect(otherBookings).toEqual(fixture.otherBookingsBefore)
  return bookings
}

export async function closeJ4Venue(api: APIRequestContext, fixture: J4Fixture) {
  const data = {
    venueId: fixture.closedVenueId, startDateTime: `${fixture.closureStart}:00+08:00`,
    endDateTime: `${fixture.closureEnd}:00+08:00`, reason: fixture.reason,
  }
  const preview = await api.post(serviceUrl('venueBooking', '/venue-closures/preview'), {
    headers: await authHeaders(users.venueStaff), data,
  })
  await expectStatus(preview, 200, 'preview J4 fixture closure')
  const impact = await preview.json()
  expect(impact.affectedCount).toBe(1)
  expect(impact.affectedRequests).toMatchObject([{ id: fixture.affectedBookingId }])
  const response = await api.post(serviceUrl('venueBooking', '/venue-closures'), {
    headers: await authHeaders(users.venueStaff),
    data: { ...data, confirmed: true, confirmationToken: impact.confirmationToken },
  })
  await expectStatus(response, 201, 'record J4 fixture closure')
  expect((await response.json()).rejectedCount).toBe(1)
}

export async function approveJ4Replacement(staff: Page, fixture: J4Fixture) {
  for (let attempt = 0; attempt < 3; attempt++) {
    const [response] = await Promise.all([
      staff.waitForResponse(candidate => new URL(candidate.url()).pathname === '/booking-requests'
        && candidate.request().method() === 'GET'),
      attempt === 0 ? staff.goto('/venue-requests')
        : staff.getByRole('button', { name: 'Refresh requests' }).click(),
    ])
    await expect(staff.getByRole('button', { name: 'Refresh requests' })).toBeEnabled()
    if (response.ok()) break
    const failure = `Venue queue returned HTTP ${response.status()}: ${await response.text()}`
    if (![502, 503, 504].includes(response.status()) || attempt === 2) throw new Error(failure)
    console.warn(`${failure} Retrying through Refresh requests.`)
  }
  const row = staff.getByRole('region', { name: `${fixture.eventName} venue requests` })
    .getByRole('row').filter({ hasText: fixture.alternativeVenueName })
  await expect(row).toContainText('Awaiting review')
  await row.getByRole('button', { name: 'Review', exact: true }).click()
  const dialog = staff.getByRole('dialog')
  await expect(dialog).toContainText(fixture.alternativeVenueName)
  await dialog.getByRole('button', { name: 'Approve', exact: true }).click()
  await expect(staff.getByText('Venue request approved.')).toBeVisible()
  await expect(row).toContainText('Approved')
}
