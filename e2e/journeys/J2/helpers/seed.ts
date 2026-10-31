import type { APIRequestContext } from '@playwright/test'
import { expect } from '@playwright/test'
import { authHeaders, serviceUrl, users } from '../../../helpers/stack'

export async function createJ2Event(
  api: APIRequestContext,
  name: string,
  window: { start: string; end: string },
) {
  const response = await api.post(serviceUrl('event', '/events'), {
    headers: await authHeaders(users.organiser),
    data: {
      eventName: name,
      description: 'J2 real-stack journey fixture.',
      purpose: 'Verify event access and coordinator responsibility.',
      preferredStartDate: window.start,
      preferredEndDate: window.end,
      expectedAttendance: '50',
    },
  })
  expect(response.ok(), `create event: ${response.status()} ${await response.text()}`).toBe(true)
  const body: { id?: unknown } = await response.json()
  if (typeof body.id !== 'string') throw new Error('Event Service did not return the created event ID.')
  return body.id
}

export async function assignJ2Coordinator(
  api: APIRequestContext,
  eventId: string,
  coordinatorId: string,
) {
  const response = await api.post(
    serviceUrl('assignment', `/events/${eventId}/assign-coordinator/${coordinatorId}`),
    { headers: await authHeaders(users.lead) },
  )
  expect(response.ok(), `assign coordinator: ${response.status()} ${await response.text()}`).toBe(true)
}
