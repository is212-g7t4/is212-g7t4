import { beforeEach, expect, test, vi } from 'vitest'
import { fetchActiveVenueHolds, placeVenueHold, showVenueHoldStatus } from './venueHolds'
import type { Venue } from './venues'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

test('loads active venue holds', async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => ({ holds: [{ id: 'h1' }] }) } as Response)

  await expect(fetchActiveVenueHolds()).resolves.toEqual([{ id: 'h1' }])
  expect(fetch).toHaveBeenCalledWith('http://localhost:5008/venue-holds')
})

test('places a hold with the selected Venue Staff identity', async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => ({ hold: { id: 'h1' } }) } as Response)

  await placeVenueHold('venue-1', '2026-10-09T12:00', { id: 'staff-1', role: 'Venue Staff' })

  expect(fetch).toHaveBeenCalledWith('http://localhost:5008/venue-holds', expect.objectContaining({
    method: 'POST',
    headers: expect.objectContaining({ 'X-Dev-User-Id': 'staff-1', 'X-Dev-Role': 'Venue Staff' }),
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