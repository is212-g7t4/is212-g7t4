import { afterEach, expect, test, vi } from 'vitest'
import { canManageEquipment } from './permissions'
import { createEquipment, fetchEquipment } from './equipment'

afterEach(() => vi.unstubAllGlobals())

const stubFetch = (ok: boolean, body: unknown) => {
  const fn = vi.fn().mockResolvedValue({ ok, json: () => Promise.resolve(body) })
  vi.stubGlobal('fetch', fn)
  return fn
}

test('only Technical Support can manage equipment', () => {
  expect(canManageEquipment('Technical Support')).toBe(true)
  expect(canManageEquipment('Venue Staff')).toBe(false)
})

test('fetchEquipment sends the status filter', async () => {
  const fn = stubFetch(true, { equipment: [] })
  await expect(fetchEquipment('Available')).resolves.toEqual([])
  expect(fn.mock.calls[0][0]).toBe('http://localhost:5002/equipment?status=Available')
  await fetchEquipment()
  expect(fn.mock.calls[1][0]).toBe('http://localhost:5002/equipment')
})

test('fetchEquipment surfaces the service message or a default', async () => {
  stubFetch(false, { message: 'down' })
  await expect(fetchEquipment()).rejects.toThrow('down')
  stubFetch(false, {})
  await expect(fetchEquipment()).rejects.toThrow('Unable to load')
})

test('createEquipment posts JSON', async () => {
  const fn = stubFetch(true, { equipment: { id: 'x' } })
  const payload = { equipmentType: 'Laptop', description: 'd', totalQuantity: 1, location: 'l', status: 'Available' } as const
  await expect(createEquipment(payload)).resolves.toEqual({ id: 'x' })
  const init = fn.mock.calls[0][1]
  expect(init.method).toBe('POST')
  expect(JSON.parse(init.body)).toEqual(payload)
})

test('createEquipment surfaces errors', async () => {
  stubFetch(false, { message: 'nope' })
  await expect(createEquipment({ equipmentType: 'Laptop', description: 'd', totalQuantity: 1, location: 'l', status: 'Available' })).rejects.toThrow('nope')
  stubFetch(false, {})
  await expect(createEquipment({ equipmentType: 'Laptop', description: 'd', totalQuantity: 1, location: 'l', status: 'Available' })).rejects.toThrow('Unable to add')
})
