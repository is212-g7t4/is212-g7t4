import type { APIRequestContext } from '@playwright/test'
import { expect } from '@playwright/test'
import {
  authHeaders, createUnderReviewEvent, randomWindow, serviceUrl, users,
} from '../../../../helpers/stack'

/** Establish a Confirmed event through venue approval and the safety workflow. */
export async function createConfirmedEvent(api: APIRequestContext, name: string, runId: string) {
  const window = randomWindow()
  const eventId = await createUnderReviewEvent(api, name, window)
  const venueId = '8381b11e-aaae-4d58-bdba-2607e9e2bde2' // seeded Available Grand Ballroom, capacity 500
  const bookingResponse = await api.post(serviceUrl('venueBooking', '/booking-requests'), {
    headers: await authHeaders(users.coordinator),
    data: {
      eventId, venueId, requestedStartTime: window.start, requestedEndTime: window.end,
      requiredCapacity: 50, venueRequirements: 'E2E journey fixture',
    },
  })
  expect(bookingResponse.ok(), `create venue booking: ${bookingResponse.status()} ${await bookingResponse.text()}`).toBe(true)
  const booking = await bookingResponse.json() as { id: string }
  const approvedBooking = await api.patch(serviceUrl('venueBooking', `/booking-requests/${booking.id}/review`), {
    headers: await authHeaders(users.venueStaff), data: { status: 'Approved' },
  })
  expect(approvedBooking.ok(), `approve venue booking: ${approvedBooking.status()} ${await approvedBooking.text()}`).toBe(true)

  const approvedEvent = await api.patch(serviceUrl('event', `/events/${eventId}/progress`), {
    headers: await authHeaders(users.coordinator), data: { status: 'Approved', actionDetails: 'E2E safety fixture' },
  })
  expect(approvedEvent.ok(), `approve event: ${approvedEvent.status()} ${await approvedEvent.text()}`).toBe(true)
  const pendingCheck = await api.post(serviceUrl('safety', '/safety-checks'), {
    headers: await authHeaders(users.coordinator), data: { eventId, equipmentPlacementNotes: `J6 fixture ${runId}` },
  })
  expect(pendingCheck.ok(), `submit safety check: ${pendingCheck.status()} ${await pendingCheck.text()}`).toBe(true)
  const safetyDecision = await api.post(serviceUrl('safety', '/safety-checks/approve'), {
    headers: await authHeaders(users.safetyOfficer), data: { eventId, remarks: 'E2E fixture approval.' },
  })
  expect(safetyDecision.ok(), `approve safety check: ${safetyDecision.status()} ${await safetyDecision.text()}`).toBe(true)
  return { eventId, window }
}
