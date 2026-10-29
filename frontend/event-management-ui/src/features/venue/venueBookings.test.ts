import { afterEach, expect, test, vi } from 'vitest'
import { createVenueBooking, fetchVenueBookings, updateVenueBooking, cancelVenueBooking, fetchVenueRequestDetail, fetchVenueRequests, reviewVenueRequest } from './venueBookings'

const details = { eventId: 'event', venueId: 'venue', coordinatorId: 'coordinator', requestedStartTime: '2026-12-01T09:00', requestedEndTime: '2026-12-01T10:00', requiredCapacity: 10, venueRequirements: '' }

test('venue staff queue and review use the owning composite', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ events: [] })))
  vi.stubGlobal('fetch', fetcher)
  expect(await fetchVenueRequests('Pending')).toEqual([])
  expect(fetcher).toHaveBeenLastCalledWith(expect.stringContaining('/booking-requests?status=Pending'), undefined)
  fetcher.mockResolvedValue(new Response(JSON.stringify({ id: 'booking', status: 'Approved' })))
  await reviewVenueRequest('booking/id', 'Approved')
  expect(fetcher).toHaveBeenLastCalledWith(expect.stringContaining('/booking-requests/booking%2Fid/review'),
    expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ status: 'Approved' }) }))
})
afterEach(() => vi.unstubAllGlobals())
test('existing edit and cancel routes preserve encoded IDs and request bodies', async () => {
  const fetcher = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ id: 'booking', status: 'Pending Review' })))
  vi.stubGlobal('fetch', fetcher)
  await updateVenueBooking('booking/id', details)
  expect(fetcher).toHaveBeenLastCalledWith(expect.stringContaining('/booking-requests/booking%2Fid'), expect.objectContaining({ method: 'PATCH', body: JSON.stringify(details) }))
  await cancelVenueBooking('booking/id', 'event', 'coordinator')
  expect(fetcher).toHaveBeenLastCalledWith(expect.stringContaining('/booking-requests/booking%2Fid/cancel'), expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ eventId: 'event', coordinatorId: 'coordinator' }) }))
})

test.each([null, [], 'bad', { message: {} }, { message: '', code: 9, conflictTypes: 'bad' }])('malformed error payload is safe: %j', async (body) => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 500 })))
  await expect(createVenueBooking(details)).rejects.toMatchObject({ message: 'Unable to complete the venue booking request.', status: 500, conflictTypes: [] })
})
test('legacy message-only errors remain readable', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ message: 'Capacity exceeded' }), { status: 422 })))
  await expect(createVenueBooking(details)).rejects.toThrow('Capacity exceeded')
})
test('invalid JSON errors retain a generic failure', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>down</html>', { status: 502 })))
  await expect(createVenueBooking(details)).rejects.toMatchObject({ message: 'Unable to complete the venue booking request.', status: 502 })
})
test('metadata is de-duplicated and non-string values cannot enter conflict descriptions', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: 'VENUE_UNAVAILABLE', conflictTypes: ['VENUE_CLOSURE', null, {}, 3, 'VENUE_CLOSURE'] }), { status: 409 })))
  await expect(createVenueBooking(details)).rejects.toMatchObject({ conflictTypes: ['VENUE_CLOSURE'] })
})
test('read failures do not imply a write was attempted', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Offline')))
  await expect(fetchVenueBookings('event', 'coordinator')).rejects.toThrow('Unable to load venue bookings.')
})
test('SCRUM-30 lost success response body must not be treated as a saved request', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('truncated', { status: 201 })))
  await expect(createVenueBooking(details)).rejects.toThrow('Unable to confirm whether the booking request was saved.')
})
test('SCRUM-30 retains structured conflict metadata on the request error', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ message: 'Unavailable', code: 'VENUE_UNAVAILABLE', conflictTypes: ['APPROVED_BOOKING'] }), { status: 409 })))
  await expect(createVenueBooking(details)).rejects.toMatchObject({ message: 'Unavailable', status: 409, code: 'VENUE_UNAVAILABLE', conflictTypes: ['APPROVED_BOOKING'] })
})

test('SCRUM-28 AC2: the event-status refusal keeps its code and message', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
    code: 'EVENT_NOT_ACCEPTING_VENUE_REQUESTS', message: 'Not accepting requests.', eventStatus: 'Confirmed',
  }), { status: 409 })))
  await expect(createVenueBooking(details)).rejects.toMatchObject({
    status: 409, code: 'EVENT_NOT_ACCEPTING_VENUE_REQUESTS', message: 'Not accepting requests.', conflictTypes: [],
  })
})

test('SCRUM-29 AC4: reviewVenueRequest sends a reason only with a rejection', async () => {
  const fetcher = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ id: 'booking', status: 'Rejected' })))
  vi.stubGlobal('fetch', fetcher)
  await reviewVenueRequest('booking', 'Rejected', 'Too small')
  expect(fetcher).toHaveBeenLastCalledWith(expect.stringContaining('/booking-requests/booking/review'),
    expect.objectContaining({ body: JSON.stringify({ status: 'Rejected', rejectionReason: 'Too small' }) }))
  await reviewVenueRequest('booking', 'Approved', 'ignored')
  expect(fetcher).toHaveBeenLastCalledWith(expect.anything(),
    expect.objectContaining({ body: JSON.stringify({ status: 'Approved' }) }))
})

test('SCRUM-29 AC1: fetchVenueRequestDetail asks the composite', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ booking: { id: 'b' }, canDecide: true })))
  vi.stubGlobal('fetch', fetcher)
  expect(await fetchVenueRequestDetail('b/1')).toMatchObject({ canDecide: true })
  expect(fetcher).toHaveBeenLastCalledWith(expect.stringMatching(/\/booking-requests\/b%2F1$/), undefined)
})

test('SCRUM-29 AC5: the already-decided refusal keeps its code', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: 'BOOKING_ALREADY_DECIDED', message: 'Decided.' }), { status: 409 })))
  await expect(reviewVenueRequest('b', 'Approved')).rejects.toMatchObject({ status: 409, code: 'BOOKING_ALREADY_DECIDED' })
})
