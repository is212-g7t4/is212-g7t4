/**
 * # Test scope and acceptance mapping — SCRUM-171 integration
 *
 * - **SCRUM-171 AC4 — confirmation:** full named list/count and closure details before save; back/edit clears confirmation without writes; changed impact requires a refreshed preview and another explicit confirmation.
 * - **Supporting robustness:** failed refresh clears stale tokens while keeping drafts; uncertain-save reconciliation restarts page one, aborts/ignores stale pages and blocks replay until a fresh final page. Duplicate/pending/zero-impact cases do not prove AC5 rollback.
 *
 * ## Case/group traceability
 *
 * - `back and edits discard confirmation without writes; full list remains available`: AC4 — complete preview list/count, back/edit no save, explicit confirmation; mocked component scope.
 * - `changed-impact refresh failure clears stale token and keeps draft`: AC4 — changed-impact updated review and explicit reconfirmation; refresh failure handling supporting robustness.
 * - `uncertain save blocks replay until history is reconciled, including zero impact`: Supporting duplicate/uncertain-write robustness — one pending call and reconciliation before replay; no direct AC.
 * - `changed impact refreshes preview but requires another explicit confirmation`: AC4 — changed-impact updated review and explicit reconfirmation; refresh failure handling supporting robustness.
 * - `preview shows request count and complete named list before explicit confirmation`: AC4 — complete preview list/count, back/edit no save, explicit confirmation; mocked component scope.
 */
import { beforeEach, expect, test, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { VenueClosuresPanel } from './VenueClosuresPanel'
import * as api from './venueClosures'
vi.mock('./venueClosures', async original => ({ ...await original<typeof api>(), listClosures: vi.fn(), previewClosure: vi.fn(), createClosure: vi.fn() }))
const closure = { venueId: 'v1', startDateTime: '2099-01-01T10:00:00+08:00', endDateTime: '2099-01-01T12:00:00+08:00', reason: 'Maintenance' }
const preview = { closure, venueName: 'Hall', affectedCount: 2, confirmationToken: 'signed', affectedRequests: ['one', 'two'].map(id => ({ id, eventId: id, venueId: 'v1', eventName: `Event ${id}`, venueName: 'Hall', status: 'Approved', requestedStartTime: closure.startDateTime, requestedEndTime: closure.endDateTime })) }
beforeEach(() => { vi.resetAllMocks(); vi.mocked(api.listClosures).mockResolvedValue({ closures: [], nextCursor: null }); vi.mocked(api.previewClosure).mockResolvedValue(preview) })
async function draft() {
 render(<VenueClosuresPanel venueId="v1" venueName="Hall" />)
 fireEvent.click(screen.getByRole('button', { name: 'Record temporary closure' }))
 fireEvent.change(screen.getByLabelText('Closure start (SGT)'), { target: { value: '2099-01-01T10:00' } })
 fireEvent.change(screen.getByLabelText('Closure end (SGT)'), { target: { value: '2099-01-01T12:00' } })
 fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Maintenance' } })
 fireEvent.click(screen.getByRole('button', { name: 'Preview affected requests' }))
}

test('uncertain save restarts history and ignores a stale in-flight old page', async () => {
 const row = { ...closure, closureId: 'old', reason: 'Old history', createdBy: 'staff', createdAt: closure.startDateTime }
 let finishOld!: (value: Awaited<ReturnType<typeof api.listClosures>>) => void
 let finishFresh!: (value: Awaited<ReturnType<typeof api.listClosures>>) => void
 vi.mocked(api.listClosures).mockResolvedValueOnce({ closures: [row], nextCursor: 'old-cursor' })
  .mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
  .mockImplementationOnce(() => new Promise(resolve => { finishFresh = resolve }))
 await draft(); await screen.findByText('Event one')
 fireEvent.click(screen.getByRole('button', { name: 'Load more closures' }))
 const oldSignal = vi.mocked(api.listClosures).mock.calls[1][2]!
 vi.mocked(api.createClosure).mockRejectedValue(Object.assign(new Error('Maybe saved'), { uncertain: true }))
 fireEvent.click(screen.getByRole('button', { name: 'Confirm closure and reject requests' }))
 await screen.findByRole('alert')
 expect(oldSignal.aborted).toBe(true)
 expect(api.listClosures).toHaveBeenLastCalledWith('v1', undefined, expect.any(AbortSignal))
 expect(screen.queryByText('Old history')).not.toBeInTheDocument()
 await act(async () => { finishOld({ closures: [{ ...row, reason: 'Stale result' }], nextCursor: null }) })
 expect(screen.queryByText('Stale result')).not.toBeInTheDocument()
 expect(screen.getByRole('button', { name: 'I checked all recorded closures; start a new preview' })).toBeDisabled()
 await act(async () => { finishFresh({ closures: [{ ...row, closureId: 'saved', reason: 'Possibly saved closure' }], nextCursor: 'fresh-cursor' }) })
 expect(screen.getByText('Possibly saved closure')).toBeInTheDocument()
 expect(screen.getByRole('button', { name: 'I checked all recorded closures; start a new preview' })).toBeDisabled()
 vi.mocked(api.listClosures).mockResolvedValueOnce({ closures: [], nextCursor: null })
 fireEvent.click(screen.getByRole('button', { name: 'Load more closures' }))
 await waitFor(() => expect(screen.getByRole('button', { name: 'I checked all recorded closures; start a new preview' })).toBeEnabled())
 expect(api.listClosures).toHaveBeenLastCalledWith('v1', 'fresh-cursor', expect.any(AbortSignal))
})

test('back and edits discard confirmation without writes; full list remains available', async () => {
 vi.mocked(api.previewClosure).mockResolvedValue({ ...preview, affectedCount: 105, affectedRequests: Array.from({ length: 105 }, (_, i) => ({ ...preview.affectedRequests[0], id: `r${i}`, eventName: `Event ${i}` })) })
 await draft(); await screen.findByText('Event 104')
 expect(screen.getByRole('list', { name: 'Affected booking requests' }).children).toHaveLength(105)
 expect(screen.getByRole('region', { name: 'Confirm temporary closure' })).toHaveFocus()
 fireEvent.click(screen.getByRole('button', { name: 'Back to edit' }))
 expect(screen.queryByRole('region', { name: 'Confirm temporary closure' })).not.toBeInTheDocument()
 fireEvent.click(screen.getByRole('button', { name: 'Preview affected requests' })); await screen.findByText('Event 104')
 fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'New reason' } })
 expect(screen.queryByRole('region', { name: 'Confirm temporary closure' })).not.toBeInTheDocument()
 expect(api.createClosure).not.toHaveBeenCalled()
})
test('changed-impact refresh failure clears stale token and keeps draft', async () => {
 await draft(); await screen.findByText('Event one')
 vi.mocked(api.createClosure).mockRejectedValue(Object.assign(new Error('Changed'), { code: 'CLOSURE_PREVIEW_CHANGED' }))
 vi.mocked(api.previewClosure).mockRejectedValue(new Error('Preview offline'))
 fireEvent.click(screen.getByRole('button', { name: 'Confirm closure and reject requests' }))
 expect(await screen.findByRole('alert')).toHaveTextContent('Preview offline')
 expect(screen.queryByRole('region', { name: 'Confirm temporary closure' })).not.toBeInTheDocument()
 expect(screen.getByLabelText('Reason')).toHaveValue('Maintenance')
 expect(api.createClosure).toHaveBeenCalledTimes(1)
})
test('uncertain save blocks replay until history is reconciled, including zero impact', async () => {
 vi.mocked(api.previewClosure).mockResolvedValue({ ...preview, affectedCount: 0, affectedRequests: [] })
 await draft(); await screen.findByText('0 booking requests will be rejected.')
 vi.mocked(api.createClosure).mockRejectedValue(Object.assign(new Error('The closure may have been recorded.'), { uncertain: true }))
 fireEvent.click(screen.getByRole('button', { name: 'Confirm closure and reject requests' }))
 expect(await screen.findByRole('alert')).toHaveTextContent('may have been recorded')
 expect(screen.getByRole('button', { name: 'Preview affected requests' })).toBeDisabled()
 fireEvent.click(screen.getByRole('button', { name: 'Refresh closures' }))
 await waitFor(() => expect(screen.getByRole('button', { name: 'I checked all recorded closures; start a new preview' })).toBeEnabled())
 fireEvent.click(screen.getByRole('button', { name: 'I checked all recorded closures; start a new preview' }))
 expect(api.createClosure).toHaveBeenCalledTimes(1)
 expect(screen.getByRole('button', { name: 'Preview affected requests' })).toBeEnabled()
})
test('changed impact refreshes preview but requires another explicit confirmation', async () => {
 await draft(); await screen.findByText('Event one')
 vi.mocked(api.createClosure).mockRejectedValueOnce(Object.assign(new Error('Impact changed'), { code: 'CLOSURE_PREVIEW_CHANGED' }))
 vi.mocked(api.previewClosure).mockResolvedValueOnce({ ...preview, affectedCount: 0, affectedRequests: [], confirmationToken: 'fresh' })
 fireEvent.click(screen.getByRole('button', { name: 'Confirm closure and reject requests' }))
 expect(await screen.findByText('0 booking requests will be rejected.')).toBeInTheDocument()
 expect(screen.getByRole('alert')).toHaveTextContent('Review the refreshed impact and confirm again')
 expect(api.createClosure).toHaveBeenCalledTimes(1)
 expect(screen.getByLabelText('Reason')).toHaveValue('Maintenance')
 vi.mocked(api.createClosure).mockResolvedValueOnce({ ...closure, closureId: 'c', createdBy: 'staff', createdAt: closure.startDateTime, rejectedCount: 0 })
 fireEvent.click(screen.getByRole('button', { name: 'Confirm closure and reject requests' }))
 expect(await screen.findByText('Closure recorded.')).toBeInTheDocument()
 expect(api.createClosure).toHaveBeenCalledTimes(2)
 expect(api.createClosure).toHaveBeenLastCalledWith('v1', '2099-01-01T10:00', '2099-01-01T12:00', 'Maintenance', 'fresh', expect.any(AbortSignal))
})
test('preview shows request count and complete named list before explicit confirmation', async () => {
 await draft()
 const confirmation = await screen.findByRole('region', { name: 'Confirm temporary closure' })
 expect(within(confirmation).getByText('2 booking requests will be rejected.')).toBeInTheDocument()
 expect(within(confirmation).getByText('Maintenance')).toBeInTheDocument()
 expect(within(confirmation).getByText('Hall', { selector: 'strong' }).parentElement).toHaveTextContent('Hall: 1 Jan 2099, 10:00 SGT – 1 Jan 2099, 12:00 SGT')
 const requests = within(screen.getByRole('list', { name: 'Affected booking requests' })).getAllByRole('listitem')
 expect(requests).toHaveLength(2)
 for (const [index, id] of ['one', 'two'].entries()) {
  expect(requests[index]).toHaveTextContent(`Event ${id} · Hall`)
  expect(requests[index]).toHaveTextContent('1 Jan 2099, 10:00 SGT – 1 Jan 2099, 12:00 SGT')
  expect(requests[index]).toHaveTextContent(`Approved · Request ID: ${id}`)
 }
 expect(api.createClosure).not.toHaveBeenCalled()
 vi.mocked(api.createClosure).mockResolvedValue({ ...closure, closureId: 'c', createdBy: 'staff', createdAt: closure.startDateTime, rejectedCount: 2 })
 fireEvent.click(screen.getByRole('button', { name: 'Confirm closure and reject requests' }))
 await waitFor(() => expect(api.createClosure).toHaveBeenCalledWith('v1', '2099-01-01T10:00', '2099-01-01T12:00', 'Maintenance', 'signed', expect.any(AbortSignal)))
 expect(await screen.findByText('Closure recorded.')).toBeInTheDocument()
 expect(screen.getByText('2 booking requests rejected.')).toBeInTheDocument()
})
