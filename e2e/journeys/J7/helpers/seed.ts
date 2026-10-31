import type { APIRequestContext } from '@playwright/test'
import { expect } from '@playwright/test'
import {
  authHeaders, createUnderReviewEvent, randomWindow, serviceUrl, users,
} from '../../../helpers/stack'

const venueId = 'beffbfe3-9520-47e7-9290-da59a923b944' // seeded Available Rooftop Garden

function offsetWindow(base: { start: string }, days: number) {
  const date = new Date(`${base.start.slice(0, 10)}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  const day = date.toISOString().slice(0, 10)
  return { start: `${day}T09:00`, end: `${day}T17:00` }
}

async function createConfirmedEvent(
  api: APIRequestContext,
  eventName: string,
  runId: string,
  window: { start: string; end: string },
  expectedAttendance: number,
  withdrawalDeadline?: string,
) {
  const eventId = await createUnderReviewEvent(api, eventName, window, {
    expectedAttendance,
    withdrawalDeadline,
  })
  const bookingResponse = await api.post(serviceUrl('venueBooking', '/booking-requests'), {
    headers: await authHeaders(users.coordinator),
    data: {
      eventId, venueId, requestedStartTime: window.start, requestedEndTime: window.end,
      requiredCapacity: expectedAttendance, venueRequirements: 'J7 E2E fixture',
    },
  })
  expect(bookingResponse.ok(), `create venue booking: ${bookingResponse.status()} ${await bookingResponse.text()}`).toBe(true)
  const booking = await bookingResponse.json() as { id: string }
  const approvedBooking = await api.patch(serviceUrl('venueBooking', `/booking-requests/${booking.id}/review`), {
    headers: await authHeaders(users.venueStaff), data: { status: 'Approved' },
  })
  expect(approvedBooking.ok(), `approve venue booking: ${approvedBooking.status()} ${await approvedBooking.text()}`).toBe(true)

  const approvedEvent = await api.patch(serviceUrl('event', `/events/${eventId}/progress`), {
    headers: await authHeaders(users.coordinator), data: { status: 'Approved', actionDetails: 'J7 registration fixture' },
  })
  expect(approvedEvent.ok(), `approve event: ${approvedEvent.status()} ${await approvedEvent.text()}`).toBe(true)
  const pendingCheck = await api.post(serviceUrl('safety', '/safety-checks'), {
    headers: await authHeaders(users.coordinator), data: { eventId, equipmentPlacementNotes: `J7 fixture ${runId}` },
  })
  expect(pendingCheck.ok(), `submit safety check: ${pendingCheck.status()} ${await pendingCheck.text()}`).toBe(true)
  const safetyDecision = await api.post(serviceUrl('safety', '/safety-checks/approve'), {
    headers: await authHeaders(users.safetyOfficer), data: { eventId, remarks: 'J7 fixture approval.' },
  })
  expect(safetyDecision.ok(), `approve safety check: ${safetyDecision.status()} ${await safetyDecision.text()}`).toBe(true)
  return { eventId, eventName }
}

async function register(api: APIRequestContext, eventId: string, attendee: typeof users.attendee | typeof users.attendeeTwo) {
  const response = await api.post(serviceUrl('attendeeRegistration', '/registrations'), {
    headers: await authHeaders(attendee), data: { eventId },
  })
  expect(response.status(), `register ${attendee.email}: ${response.status()} ${await response.text()}`).toBe(201)
  return response.json() as Promise<{ registration: { registration_id: string } }>
}

export async function seedJ7(api: APIRequestContext, runId: string) {
  const base = randomWindow()
  const mainName = `J7 Event register and withdraw ${runId}`
  const duplicateName = `J7 Event duplicate ${runId}`
  const fullName = `J7 Event full ${runId}`
  const deadlineName = `J7 Event deadline ${runId}`
  const notConfirmedName = `J7 Event not confirmed ${runId}`

  const main = await createConfirmedEvent(api, mainName, runId, offsetWindow(base, 0), 1)
  const duplicate = await createConfirmedEvent(api, duplicateName, runId, offsetWindow(base, 2), 2)
  const full = await createConfirmedEvent(api, fullName, runId, offsetWindow(base, 4), 1)
  await register(api, full.eventId, users.attendeeTwo)

  const deadline = await createConfirmedEvent(
    api, deadlineName, runId, offsetWindow(base, 6), 2,
    new Date(Date.now() + 8 * 60 * 60 * 1000 - 60_000).toISOString().slice(0, 16),
  )
  await register(api, deadline.eventId, users.attendee)

  const notConfirmedWindow = offsetWindow(base, 8)
  const notConfirmedId = await createUnderReviewEvent(api, notConfirmedName, notConfirmedWindow)

  const confirmedResponse = await api.get(serviceUrl('event', '/events/registration'), {
    headers: await authHeaders(users.attendee),
  })
  expect(confirmedResponse.ok(), `load confirmed events: ${confirmedResponse.status()} ${await confirmedResponse.text()}`).toBe(true)
  const confirmedBody = await confirmedResponse.json() as {
    events: { id: string; eventName: string; preferredStartDate: string }[]
  }
  const closed = confirmedBody.events.find((event) => Date.parse(event.preferredStartDate) <= Date.now())
  if (!closed) throw new Error('The seeded event catalogue needs a past Confirmed event for the closed-registration case.')

  return {
    main,
    duplicate,
    full,
    deadline,
    notConfirmed: { eventId: notConfirmedId, eventName: notConfirmedName },
    closed: { eventId: closed.id, eventName: closed.eventName },
  }
}