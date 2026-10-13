import { afterEach, expect, test, vi } from 'vitest'
import { createClosure, listClosures } from './venueClosures'
const user = { id: '00000000-0000-0000-0000-0000000000aa', role: 'Venue Staff' as const }
const closure = { closureId: 'c1', venueId: 'v1', startDateTime: '2020-01-01T09:00:00+08:00', endDateTime: '2099-01-01T10:00:00+08:00', reason: 'Repairs', createdBy: user.id, createdAt: '2026-01-01T10:00:00+08:00' }
afterEach(() => vi.unstubAllGlobals())
test.each([
 ['', '2099-01-01T10:00', 'Repairs'], ['2099-02-30T09:00', '2099-03-01T10:00', 'Repairs'],
 ['2099-01-01T10:00', '2099-01-01T10:00', 'Repairs'], ['2020-01-01T09:00', '2020-01-01T10:00', 'Repairs'],
 ['2099-01-01T09:00', '2099-01-01T10:00', '  '],
])('SCRUM-170 rejects invalid interval/reason before POST: %s %s', async (start, end, reason) => {
 const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher)
 await expect(createClosure('v1', start, end, reason, user)).rejects.toThrow()
 expect(fetcher).not.toHaveBeenCalled()
})
test.each([400, 401, 403, 404])('SCRUM-170 reports rejected save %s', async status => {
 vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ message: 'Rejected' }), { status })))
 await expect(createClosure('v1', '2020-01-01T09:00', '2099-01-01T10:00', 'Repairs', user)).rejects.toThrow('Rejected')
})
test.each(['network', 'malformed', 'server'])('SCRUM-170 warns ambiguous %s save without retry', async failure => {
 const fetcher = failure === 'network' ? vi.fn().mockRejectedValue(new TypeError('offline')) : vi.fn().mockResolvedValue(new Response('{}', { status: failure === 'server' ? 503 : 201 }))
 vi.stubGlobal('fetch', fetcher)
 await expect(createClosure('v1', '2020-01-01T09:00', '2099-01-01T10:00', 'Repairs', user)).rejects.toThrow(/may have been recorded/)
 expect(fetcher).toHaveBeenCalledTimes(1)
})
test('SCRUM-170 lists bounded pages with opaque cursor and cancellation', async () => {
 const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ closures: [closure], nextCursor: 'opaque+/' })))
 vi.stubGlobal('fetch', fetcher)
 const signal = new AbortController().signal
 expect(await listClosures('v1', user, 'opaque+/', signal)).toEqual({ closures: [closure], nextCursor: 'opaque+/' })
 const [url, init] = fetcher.mock.calls[0]
 expect(new URL(url).searchParams.get('cursor')).toBe('opaque+/')
 expect(new URL(url).searchParams.get('limit')).toBe('50')
 expect(init.signal).toBe(signal)
})
test.each([{ closures: [{ ...closure, venueId: 'foreign' }], nextCursor: null }, { closures: [], nextCursor: 1 }, { closures: [{ ...closure, endDateTime: 'bad' }], nextCursor: null }])('SCRUM-170 rejects malformed list', async body => {
 vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body))))
 await expect(listClosures('v1', user)).rejects.toThrow(/Unable to load/)
})
test('SCRUM-170 rejected non-JSON save gives controlled message', async () => {
 vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('invalid', { status: 400 })))
 await expect(createClosure('v1', '2020-01-01T09:00', '2099-01-01T10:00', 'Repairs', user)).rejects.toThrow(/Check your input/)
})
test('SCRUM-170 list accepts nullable legacy metadata and rejects non-JSON', async () => {
 vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ closures: [{ ...closure, createdAt: null, createdBy: null }], nextCursor: null }))).mockResolvedValueOnce(new Response('bad')))
 expect((await listClosures('v1', user)).closures[0].createdBy).toBeNull()
 await expect(listClosures('v1', user)).rejects.toThrow(/Unable to load/)
})
test('SCRUM-170 creates ongoing closure through composite with exact body and staff headers', async () => {
 const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ closure }), { status: 201 }))
 vi.stubGlobal('fetch', fetcher)
 expect(await createClosure('v1', '2020-01-01T09:00', '2099-01-01T10:00', ' Repairs ', user)).toEqual(closure)
 const [url, init] = fetcher.mock.calls[0]
 expect(url).toBe('http://localhost:5007/venue-closures')
 expect(JSON.parse(init.body)).toEqual({ venueId: 'v1', startDateTime: closure.startDateTime, endDateTime: closure.endDateTime, reason: 'Repairs' })
 expect(init.headers).toMatchObject({ 'X-Dev-User-Id': user.id, 'X-Dev-Role': 'Venue Staff' })
})
