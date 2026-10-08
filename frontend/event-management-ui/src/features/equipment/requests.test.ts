import { afterEach, expect, test, vi } from 'vitest'
import { fetchEventReservations, reviewAllEventEquipmentRequests, reviewEquipmentRequest } from './requests'

afterEach(() => vi.unstubAllGlobals())

const user = { id: 'u1', role: 'Technical Support' } as const
const stubFetch = (ok: boolean, body: unknown) => {
  const fn = vi.fn().mockResolvedValue({ ok, json: () => Promise.resolve(body) })
  vi.stubGlobal('fetch', fn)
  return fn
}

test('fetchEventReservations calls the reservation composite with the status filter and DEV headers', async () => {
  const fn = stubFetch(true, { events: [{ eventId: 'ev1' }] })
  await expect(fetchEventReservations(user, 'Pending')).resolves.toEqual([{ eventId: 'ev1' }])
  expect(fn.mock.calls[0][0]).toBe('http://localhost:5010/equipment-reservations?status=Pending')
  expect(fn.mock.calls[0][1].headers).toEqual({ 'X-Dev-User-Id': 'u1', 'X-Dev-Role': 'Technical Support' })
  await fetchEventReservations(user)
  expect(fn.mock.calls[1][0]).toBe('http://localhost:5010/equipment-reservations')
})

test('reviewEquipmentRequest patches one request through the composite', async () => {
  const fn = stubFetch(true, { request: { id: 'r1', status: 'Rejected' } })
  await expect(reviewEquipmentRequest('r1', 'Rejected', user)).resolves.toEqual({ id: 'r1', status: 'Rejected' })
  const [url, init] = fn.mock.calls[0]
  expect(url).toBe('http://localhost:5010/equipment-reservations/requests/r1')
  expect(init.method).toBe('PATCH')
  expect(JSON.parse(init.body)).toEqual({ status: 'Rejected' })
})

test('reviewAllEventEquipmentRequests patches the whole event through the composite', async () => {
  const fn = stubFetch(true, { requests: [{ id: 'r1' }] })
  await expect(reviewAllEventEquipmentRequests('ev1', 'Approved', user)).resolves.toEqual([{ id: 'r1' }])
  expect(fn.mock.calls[0][0]).toBe('http://localhost:5010/equipment-reservations/events/ev1')
  expect(JSON.parse(fn.mock.calls[0][1].body)).toEqual({ status: 'Approved' })
})

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
