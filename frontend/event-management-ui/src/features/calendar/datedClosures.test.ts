import { afterEach, expect, test, vi } from 'vitest'
import { fetchCalendar } from './api'
const id = '00000000-0000-0000-0000-000000000001'
const user = {id, role: 'Event Coordinator'}
const window = {start: '2026-10-01', end: '2026-10-02'}
const closure = {closureId: id, venueId: id, startDateTime: '2026-09-30T23:00:00.000001+08:00', endDateTime: '2026-10-02T10:00:00.000002+08:00', reason: 'Maintenance'}
afterEach(() => vi.unstubAllGlobals())
test.each([{bookings: []}, {bookings: [], closures: null}, {bookings: [], closures: [ {...closure, venueId: 'wrong'} ]}, {bookings: [], closures: [closure, closure]}, {bookings: [], closures: [{...closure, reason: ' '}]}, {bookings: [], closures: [{...closure, endDateTime: closure.startDateTime}]}])('SCRUM174 unsafe closure envelope rejects instead of showing free time', async body => {
 respond(body)
 await expect(fetchCalendar(id, window, user)).rejects.toThrow('Invalid availability')
})
test('SCRUM174 active hold with no event is a blocking calendar entry', async () => {
 respond({bookings: [{id, eventId:null, venueId:id, requestedBy:null, reviewedBy:null, status:'On Hold', blocksSelection:true, requestedStartTime:closure.startDateTime, requestedEndTime:closure.endDateTime}], closures:[]})
 expect(await fetchCalendar(id, window, user)).toEqual([expect.objectContaining({status:'On Hold', blocksSelection:true})])
})
function respond(body: unknown) { vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body)))) }
test('SCRUM174 closure becomes a distinct entry preserving original dates, microseconds and reason', async () => {
 respond({bookings: [], closures: [closure]})
 expect(await fetchCalendar(id, window, user)).toEqual([expect.objectContaining({id: `closure:${id}`, status: 'Closed', reason: 'Maintenance', requestedStartTime: closure.startDateTime, requestedEndTime: closure.endDateTime, blocksSelection: true})])
})
