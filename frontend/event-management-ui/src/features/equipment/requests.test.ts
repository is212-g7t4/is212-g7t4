import { afterEach, expect, test, vi } from 'vitest'
import { createEquipmentRequests, fetchEventReservations, fetchRequestableEvents, reviewAllEventEquipmentRequests, reviewEquipmentRequest } from './requests'

afterEach(() => vi.unstubAllGlobals())

const user = { id: 'u1', role: 'Technical Support' } as const
const stubFetch = (ok: boolean, body: unknown) => {
  const fn = vi.fn().mockResolvedValue({ ok, json: () => Promise.resolve(body) })
  vi.stubGlobal('fetch', fn)
  return fn
}

// Review AC1/AC3 (transport): fetch the event request view using caller identity and status filters.
test('fetchEventReservations calls the reservation composite with the status filter and DEV headers', async () => {
  const fn = stubFetch(true, { events: [{ eventId: 'ev1' }] })
  await expect(fetchEventReservations(user, 'Pending')).resolves.toEqual([{ eventId: 'ev1' }])
  expect(fn.mock.calls[0][0]).toBe('http://localhost:5010/equipment-reservations?status=Pending')
  expect(fn.mock.calls[0][1].headers).toEqual({ 'X-Dev-User-Id': 'u1', 'X-Dev-Role': 'Technical Support' })
  await fetchEventReservations(user)
  expect(fn.mock.calls[1][0]).toBe('http://localhost:5010/equipment-reservations')
})

// Review AC2 (transport): send an individual request's decision to the owning composite.
test('reviewEquipmentRequest patches one request through the composite', async () => {
  const fn = stubFetch(true, { request: { id: 'r1', status: 'Rejected' } })
  await expect(reviewEquipmentRequest('r1', 'Rejected', user)).resolves.toEqual({ id: 'r1', status: 'Rejected' })
  const [url, init] = fn.mock.calls[0]
  expect(url).toBe('http://localhost:5010/equipment-reservations/requests/r1')
  expect(init.method).toBe('PATCH')
  expect(JSON.parse(init.body)).toEqual({ status: 'Rejected' })
})

// Review AC2 / Reservation AC2 (transport): scope a bulk decision to its event ID.
test('reviewAllEventEquipmentRequests patches the whole event through the composite', async () => {
  const fn = stubFetch(true, { requests: [{ id: 'r1' }] })
  await expect(reviewAllEventEquipmentRequests('ev1', 'Approved', user)).resolves.toEqual([{ id: 'r1' }])
  expect(fn.mock.calls[0][0]).toBe('http://localhost:5010/equipment-reservations/events/ev1')
  expect(JSON.parse(fn.mock.calls[0][1].body)).toEqual({ status: 'Approved' })
})

// Review AC1/AC2 (failure): surface read and decision errors instead of reporting false success.
test('each call surfaces the service message or a default', async () => {
  stubFetch(false, { message: 'Cannot approve, insufficient stock.' })
  await expect(fetchEventReservations(user)).rejects.toThrow('Cannot approve')
  await expect(reviewEquipmentRequest('r1', 'Approved', user)).rejects.toThrow('Cannot approve')
  await expect(reviewAllEventEquipmentRequests('ev1', 'Approved', user)).rejects.toThrow('Cannot approve')
  stubFetch(false, {})
  await expect(fetchEventReservations(user)).rejects.toThrow('Unable to load equipment requests')
  await expect(reviewEquipmentRequest('r1', 'Approved', user)).rejects.toThrow('Unable to update this equipment request')
  await expect(reviewAllEventEquipmentRequests('ev1', 'Approved', user)).rejects.toThrow("Unable to update this event's equipment requests")
})

const coordinator = { id: 'c1', role: 'Event Coordinator' } as const

// Create request AC1/AC2/AC3: send event-linked equipment needs and accept the server's Pending result.
test('createEquipmentRequests posts every item for the event through the composite', async () => {
  const fn = stubFetch(true, { requests: [{ id: 'r1', status: 'Pending' }] })
  const items = [{ equipmentId: 'eq1', quantityRequested: 3, technicalRequirements: '2 lapel' }]
  await expect(createEquipmentRequests('ev1', items, coordinator)).resolves.toEqual([{ id: 'r1', status: 'Pending' }])
  const [url, init] = fn.mock.calls[0]
  expect(url).toBe('http://localhost:5010/equipment-reservations/events/ev1/requests')
  expect(init.method).toBe('POST')
  expect(init.headers).toEqual({ 'Content-Type': 'application/json', 'X-Dev-User-Id': 'c1', 'X-Dev-Role': 'Event Coordinator' })
  expect(JSON.parse(init.body)).toEqual({ items })
})

// Create request AC1 (failure): unsuccessful recording surfaces an actionable service error.
test('createEquipmentRequests surfaces the service message or a default', async () => {
  stubFetch(false, { message: 'This equipment is Unavailable: Laptop.' })
  await expect(createEquipmentRequests('ev1', [], coordinator)).rejects.toThrow('Unavailable: Laptop')
  stubFetch(false, {})
  await expect(createEquipmentRequests('ev1', [], coordinator)).rejects.toThrow('Unable to submit this equipment request')
})

// Create request AC1/AC2 (eligibility): equipment needs are tied to eligible assigned events.
test('fetchRequestableEvents keeps only assigned Under Review events and excludes Submitted events', async () => {
  const fn = stubFetch(true, { events: [
    { id: 'a', status: 'Submitted' }, { id: 'b', status: 'Under Review' },
    { id: 'c', status: 'Approved' }, { id: 'd', status: 'Confirmed' }, { id: 'e', status: 'Rejected' },
    { id: 'f', status: 'Safety Changes Requested' },
  ] })
  await expect(fetchRequestableEvents('c1')).resolves.toEqual([
    { id: 'b', status: 'Under Review' }, { id: 'f', status: 'Safety Changes Requested' },
  ])
  expect(fn.mock.calls[0][0]).toBe('http://localhost:5003/events?coordinatorId=c1')
})
