import { afterEach, expect, test, vi } from 'vitest'
import { fetchApprovedVenueId } from './eventVenue'

afterEach(() => vi.unstubAllGlobals())

const booking = (status: string, venueId: string, requestedStartTime: string) => ({ status, venueId, requestedStartTime })

test('returns the venue of the earliest approved booking for the event', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ bookings: [
    booking('Pending Review', 'venue-pending', '2026-11-10T08:00:00'),
    booking('Approved', 'venue-later', '2026-11-11T09:00:00'),
    booking('Approved', 'venue-first', '2026-11-10T09:00:00'),
  ] })))
  vi.stubGlobal('fetch', fetchMock)

  expect(await fetchApprovedVenueId('event-1')).toBe('venue-first')
  expect(fetchMock).toHaveBeenCalledWith('http://localhost:5008/events/event-1/venue-bookings')
})

test('returns null when no booking is approved', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ bookings: [
    booking('Pending', 'venue-1', '2026-11-10T09:00:00'),
  ] }))))
  expect(await fetchApprovedVenueId('event-1')).toBeNull()
})

test('reports a service error', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ message: 'down' }), { status: 503 })))
  await expect(fetchApprovedVenueId('event-1')).rejects.toThrow('down')
})
