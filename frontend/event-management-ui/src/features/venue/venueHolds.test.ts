import { beforeEach, expect, test, vi } from 'vitest'
import { fetchActiveVenueHolds, fetchHoldReminders, placeVenueHold, showVenueHoldStatus } from './venueHolds'
import type { Venue } from './venues'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

test('loads active venue holds', async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => ({ holds: [{ id: 'h1' }] }) } as Response)

  await expect(fetchActiveVenueHolds()).resolves.toEqual([{ id: 'h1' }])
  expect(fetch).toHaveBeenCalledWith('http://localhost:5008/venue-holds')
})

test('places a hold', async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => ({ hold: { id: 'h1' } }) } as Response)

  await placeVenueHold('venue-1', '2026-10-09T12:00')

  expect(fetch).toHaveBeenCalledWith('http://localhost:5008/venue-holds', expect.objectContaining({
    method: 'POST',
    body: JSON.stringify({ venueId: 'venue-1', expiresAt: '2026-10-09T12:00' }),
  }))
})

test('marks held venues On Hold without changing other venue statuses', () => {
  const venues: Venue[] = [
    { id: 'v1', status: 'Available' },
    { id: 'v2', status: 'Under Maintenance' },
  ].map((venue) => ({
    ...venue, name: '', location: '', capacity: null,
    facilities: [], accessibility: '', supportedLayouts: [],
  }))

  expect(showVenueHoldStatus(venues, [{ id: 'h1', venueId: 'v1', createdAt: '', expiresAt: '', heldBy: null }]))
    .toMatchObject([{ id: 'v1', status: 'On Hold' }, { id: 'v2', status: 'Under Maintenance' }])
})
test('sends the coordinator the hold is placed for', async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => ({ hold: { id: 'h1' } }) } as Response)

  await placeVenueHold('venue-1', '2026-10-09T12:00', 'coord-1')

  expect(vi.mocked(fetch).mock.calls[0][1]?.body).toBe(JSON.stringify({ venueId: 'venue-1', expiresAt: '2026-10-09T12:00', coordinatorId: 'coord-1' }))
})

test('sends venue buffers together with the coordinator reminder assignment', async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => ({ hold: { id: 'h1' } }) } as Response)

  await placeVenueHold(
    'venue-1',
    '2026-10-09T12:00',
    'coord-1',
    { setupTimeMinutes: 30, turnaroundTimeMinutes: 45 },
  )

  expect(vi.mocked(fetch).mock.calls[0][1]?.body).toBe(JSON.stringify({
    venueId: 'venue-1',
    expiresAt: '2026-10-09T12:00',
    coordinatorId: 'coord-1',
    setupTimeMinutes: 30,
    turnaroundTimeMinutes: 45,
  }))
})

test('loads hold reminders', async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => ({ reminders: [{ id: 'h1' }] }) } as Response)

  await expect(fetchHoldReminders()).resolves.toEqual([{ id: 'h1' }])
  expect(fetch).toHaveBeenCalledWith('http://localhost:5008/venue-holds/reminders')
})

test('hold reminder failures surface the service message', async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: false, json: async () => ({ message: 'nope' }) } as Response)

  await expect(fetchHoldReminders()).rejects.toThrow('nope')
})


