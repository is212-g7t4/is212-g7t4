import { afterEach, expect, test, vi } from 'vitest'
import { fetchCalendar } from './api'
const venue = '00000000-0000-0000-0000-000000000001'
const user = { id: venue, role: 'Technical Support' }
export const booking = {
  id: venue,
  eventId: venue,
  venueId: venue,
  requestedBy: null,
  reviewedBy: null,
  status: 'Approved',
  blocksSelection: true,
  requestedStartTime: '2026-10-01T09:00:00+08:00',
  requestedEndTime: '2026-10-01T10:00:00+08:00',
}
afterEach(() => vi.unstubAllGlobals())
test('caller abort signal reaches fetch without loosening single-venue validation', async () => {
  const controller = new AbortController()
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({bookings: [booking]})))
  vi.stubGlobal('fetch', fetcher)
  await fetchCalendar(venue, {start: '2026-10-01', end: '2026-10-02'}, user, controller.signal)
  expect(fetcher.mock.calls[0][1].signal).toBe(controller.signal)
})
test('valid UUID belonging to another selected venue still fails this single-venue response', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({bookings: [{...booking, venueId: '00000000-0000-0000-0000-000000000002'}]}))))
  await expect(fetchCalendar(venue,{start:'2026-10-01',end:'2026-10-02'},user)).rejects.toThrow('Invalid availability response')
})
test('valid sub-millisecond API interval preserves microseconds', async () => {
  const row = { ...booking, requestedStartTime: '2026-10-01T10:00:00.000001+08:00',
    requestedEndTime: '2026-10-01T10:00:00.000999+08:00' }
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ bookings: [row] }))))
  await expect(fetchCalendar(venue, { start: '2026-10-01', end: '2026-10-02' }, user)).resolves.toEqual([row])
})
test.each(['2026-10-01T10:00:00.000001+08:00', '2026-10-01T10:00:00.000000+08:00'])('equal/reversed microsecond interval fails closed: %s', async (end) => {
  const row = { ...booking, requestedStartTime: '2026-10-01T10:00:00.000001+08:00', requestedEndTime: end }
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ bookings: [row] }))))
  await expect(fetchCalendar(venue, { start: '2026-10-01', end: '2026-10-02' }, user)).rejects.toThrow('Invalid availability response')
})
test('GET uses selected DEV identity and encoded explicit SGT bounds', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify({ bookings: [booking] })))
  vi.stubGlobal('fetch', fetcher)
  expect(
    await fetchCalendar(
      venue,
      { start: '2026-10-01', end: '2026-10-02' },
      user,
    ),
  ).toEqual([booking])
  const [url, options] = fetcher.mock.calls[0]
  expect(new URL(url).searchParams.get('dateFrom')).toBe(
    '2026-10-01T00:00:00+08:00',
  )
  expect(options.headers).toEqual({
    'X-Dev-User-Id': venue,
    'X-Dev-Role': 'Technical Support',
  })
})

test.each([401, 403, 503])('HTTP %s fails closed', async (status) => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(new Response('{}', { status })),
  )
  await expect(
    fetchCalendar(venue, { start: '2026-10-01', end: '2026-10-02' }, user),
  ).rejects.toThrow('Availability unavailable')
})
test.each([
  {},
  null,
  { bookings: [{ ...booking, status: 'Unknown' }] },
  { bookings: [{ ...booking, blocksSelection: false }] },
  {
    bookings: [{ ...booking, requestedStartTime: '2026-02-30T09:00:00+08:00' }],
  },
  { bookings: [{ ...booking, venueId: 'wrong' }] },
  { bookings: [{ ...booking, requestedEndTime: booking.requestedStartTime }] },
])('invalid payload fails closed %#', async (body) => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(new Response(JSON.stringify(body))),
  )
  await expect(
    fetchCalendar(venue, { start: '2026-10-01', end: '2026-10-02' }, user),
  ).rejects.toThrow('Invalid availability response')
})

test.each([
  null,
  {},
  { ...booking, requestedStartTime: 33 },
  { ...booking, eventId: 'bad' },
  { ...booking, requestedStartTime: '2026-13-01T09:00:00+08:00' },
])('unsafe row rejected %#', async (row) => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ bookings: [row] }))),
  )
  await expect(
    fetchCalendar(venue, { start: '2026-10-01', end: '2026-10-02' }, user),
  ).rejects.toThrow('Invalid availability response')
})
test('non-JSON and network failure reject; empty and both pending statuses succeed', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('not JSON')))
  await expect(
    fetchCalendar(venue, { start: '2026-10-01', end: '2026-10-02' }, user),
  ).rejects.toThrow('Invalid availability response')
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
  await expect(
    fetchCalendar(venue, { start: '2026-10-01', end: '2026-10-02' }, user),
  ).rejects.toThrow('offline')
  for (const bookings of [
    [],
    [{ ...booking, status: 'Pending', blocksSelection: false }],
    [{ ...booking, status: 'Pending Review', blocksSelection: false }],
  ]) {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ bookings }))),
    )
    expect(
      await fetchCalendar(
        venue,
        { start: '2026-10-01', end: '2026-10-02' },
        user,
      ),
    ).toEqual(bookings)
  }
})

test.each([
  { bookings: [booking, booking] },
  { bookings: [{ ...booking, requestedBy: 5 }] },
  { bookings: [{ ...booking, reviewedBy: undefined }] },
])('duplicate identity or malformed metadata is rejected %#', async (body) => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(new Response(JSON.stringify(body))),
  )
  await expect(
    fetchCalendar(venue, { start: '2026-10-01', end: '2026-10-02' }, user),
  ).rejects.toThrow('Invalid availability response')
})
