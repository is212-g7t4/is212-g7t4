/**
 * # Test scope and acceptance mapping — SCRUM-171 integration
 *
 * - **Supporting SCRUM-171 AC4 API contract:** SGT preview inputs, complete-preview validation, token and changed-impact error transport. Malformed count/list/venue responses fail closed.
 * - **Supporting save-response contract:** actual returned rejection count is preserved, not guessed from preview; a mocked response is not AC1 persistence or AC5 transaction evidence.
 *
 * ## Case/group traceability
 *
 * - `save returns actual persisted rejection count, not a guessed preview count`: Supporting save-response contract — returns the actual response rejection count; mocked transport does not prove database persistence or AC5.
 * - `save preserves changed-impact error code`: Supporting AC4 changed-impact contract — preserves the server conflict code for the UI to request renewed confirmation; no UI assertion here.
 * - `preview sends SGT inputs without write confirmation`: Supporting AC4 preview contract — sends normalized SGT closure inputs to preview without save confirmation; no persistence assertion.
 */
import { afterEach, expect, test, vi } from 'vitest'
import { createClosure, previewClosure } from './venueClosures'
const args = ['v1', '2099-01-01T10:00', '2099-01-01T12:00', ' Reason '] as const
const closure = { venueId: 'v1', startDateTime: '2099-01-01T10:00:00+08:00', endDateTime: '2099-01-01T12:00:00+08:00', reason: 'Reason' }
const valid = { closure, venueName: 'Hall', affectedCount: 0, affectedRequests: [], confirmationToken: 'signed' }
afterEach(() => vi.unstubAllGlobals())
test('save returns actual persisted rejection count, not a guessed preview count', async () => {
 const saved = { ...closure, closureId: 'c', createdBy: null, createdAt: null }
 vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ closure: saved, rejectedCount: 4 }), { status: 201 })))
 await expect(createClosure(...args, 'signed')).resolves.toEqual({ ...saved, rejectedCount: 4 })
})
test('save preserves changed-impact error code', async () => {
 vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ message: 'Changed', code: 'CLOSURE_PREVIEW_CHANGED' }), { status: 409 })))
 await expect(createClosure(...args, 'signed')).rejects.toMatchObject({ code: 'CLOSURE_PREVIEW_CHANGED' })
})
test.each([
 { ...valid, affectedCount: 1 }, { ...valid, confirmationToken: '' }, { ...valid, closure: { ...closure, venueId: 'other' } },
 { ...valid, affectedCount: 1, affectedRequests: [{ id: 'a' }] },
])('incomplete preview fails closed: %j', async body => {
 vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body))))
 await expect(previewClosure(...args)).rejects.toThrow('Unable to verify the complete affected-request preview')
})
test('preview sends SGT inputs without write confirmation', async () => {
 const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(valid))); vi.stubGlobal('fetch', fetcher)
 expect(await previewClosure(...args)).toEqual(valid)
 expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual(closure)
 expect(fetcher.mock.calls[0][0]).toContain('/venue-closures/preview')
})
