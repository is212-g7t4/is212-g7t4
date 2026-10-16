/**
 * # Test scope and acceptance mapping — SCRUM-171 integration
 *
 * - **SCRUM-170 page regressions (no direct SCRUM-171 AC):** paginated history, identity/role/venue isolation, draft preservation across failed polling and in-flight saves, retry, duplicate-submit control, required fields and persistence feedback.
 * - **Supporting SCRUM-171 AC4 integration:** existing inline saves pass through preview/explicit confirmation; these tests do not prove the complete affected-list clause. The new main scheduling-conflict read is mocked independently.
 *
 * ## Case/group traceability
 *
 * The named test functions/cases below implement the groups above; their existing
 * names and assertions specify the scenario. No group is credited with all five ACs.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { VenueDetailPage } from './VenueDetailPage'
import { fetchVenue } from '../features/venue/venues'
import { createClosure, listClosures, previewClosure } from '../features/venue/venueClosures'
vi.mock('../features/venue/venues', () => ({ fetchVenue: vi.fn() }))
// Main added an independent scheduling-conflict read; keep this closure suite hermetic.
vi.mock('../features/venue/legacyConflicts', () => ({ fetchLegacyConflicts: vi.fn().mockResolvedValue({ venueId: 'v1', conflictCount: 0, conflicts: [] }) }))
vi.mock('../features/venue/venueHolds', () => ({ fetchActiveVenueHolds: vi.fn().mockResolvedValue([]), showVenueHoldStatus: (v: unknown) => v }))
vi.mock('../features/venue/venueClosures', () => ({ createClosure: vi.fn(), listClosures: vi.fn(), previewClosure: vi.fn() }))
const user = { id: 'staff1', role: 'Venue Staff' as const }
const props = { venueId: 'v1', role: 'Venue Staff' as const, user, onBack: vi.fn(), onEdit: vi.fn() }
const row = { rejectedCount: 0, closureId: 'c1', venueId: 'v1', startDateTime: '2020-01-01T01:00:00Z', endDateTime: '2099-01-01T02:00:00Z', reason: 'Maintenance', createdBy: 'staff1', createdAt: '2026-01-01T02:00:00Z' }
beforeEach(() => {
 vi.clearAllMocks()
 vi.mocked(fetchVenue).mockResolvedValue({ id: 'v1', name: 'Grand Hall', status: 'Maintenance', location: 'L1', capacity: 10, accessibility: '', facilities: [], supportedLayouts: [] })
 vi.mocked(listClosures).mockResolvedValue({ closures: [], nextCursor: null })
 vi.mocked(createClosure).mockResolvedValue(row)
 vi.mocked(previewClosure).mockResolvedValue({ closure: { ...row, venueId: 'v1' }, venueName: 'Grand Hall', affectedCount: 0, affectedRequests: [], confirmationToken: 'signed' })
})
test('SCRUM-170 persisted list uses Singapore dates, reaches later pages and refreshes from first page', async () => {
 vi.mocked(listClosures).mockResolvedValueOnce({ closures: [row], nextCursor: 'next' }).mockResolvedValueOnce({ closures: [{ ...row, closureId: 'c2', reason: 'Second page' }], nextCursor: null })
 render(<VenueDetailPage {...props} />)
 expect(await screen.findByText('Maintenance', { selector: 'strong' })).toBeInTheDocument()
 expect(screen.getByText(/1 Jan 2020, 09:00/)).toBeInTheDocument()
 fireEvent.click(screen.getByRole('button', { name: 'Load more closures' }))
 expect(await screen.findByText('Second page')).toBeInTheDocument()
 expect(listClosures).toHaveBeenLastCalledWith('v1', user, 'next', expect.any(AbortSignal))
 expect(screen.queryByRole('button', { name: 'Load more closures' })).not.toBeInTheDocument()
 fireEvent.click(screen.getByRole('button', { name: 'Refresh closures' }))
 expect(await screen.findByText('No recorded closures.')).toBeInTheDocument()
})
test('SCRUM-170 preserves input on save failure and exposes list retry', async () => {
 vi.mocked(createClosure).mockRejectedValue(new Error('The closure may have been recorded. Refresh before retrying.'))
 vi.mocked(listClosures).mockRejectedValueOnce(new Error('List unavailable'))
 render(<VenueDetailPage {...props} />)
 await fill()
 expect(await screen.findByText('List unavailable')).toBeInTheDocument()
 fireEvent.click(screen.getByRole('button', { name: 'Confirm closure and reject requests' }))
 expect(await screen.findByText(/may have been recorded/)).toBeInTheDocument()
 expect(screen.getByLabelText('Reason')).toHaveValue('Maintenance')
 expect(screen.getByLabelText('Closure start (SGT)')).toHaveValue('2020-01-01T09:00')
 expect(screen.queryByText('Closure recorded.')).not.toBeInTheDocument()
 fireEvent.click(screen.getByRole('button', { name: 'Refresh closures' }))
 expect(await screen.findByText('No recorded closures.')).toBeInTheDocument()
})
test('SCRUM-170 role change cancels list and save, clears state, ignores late replies', async () => {
 let finish!: (value: typeof row) => void
 vi.mocked(createClosure).mockReturnValue(new Promise(resolve => { finish = resolve }))
 const { rerender } = render(<VenueDetailPage {...props} />)
 await fill()
 fireEvent.click(screen.getByRole('button', { name: 'Confirm closure and reject requests' }))
 const saveSignal = vi.mocked(createClosure).mock.calls[0][6]
 const listSignal = vi.mocked(listClosures).mock.calls[0][3]
 rerender(<VenueDetailPage {...props} role="Event Coordinator" />)
 expect(saveSignal?.aborted).toBe(true)
 expect(listSignal?.aborted).toBe(true)
 await act(async () => finish(row))
 expect(listClosures).toHaveBeenCalledTimes(1)
 expect(screen.queryByRole('region', { name: 'Temporary venue closures' })).not.toBeInTheDocument()
 rerender(<VenueDetailPage {...props} />)
 await waitFor(() => expect(listClosures).toHaveBeenCalledTimes(2))
 fireEvent.click(await screen.findByRole('button', { name: 'Record temporary closure' }))
 expect(screen.getByLabelText('Reason')).toHaveValue('')
 expect(screen.queryByText('Closure recorded.')).not.toBeInTheDocument()
})
test.each(['Event Coordinator', 'Event Organiser', 'Technical Support', 'Attendee'] as const)('SCRUM-170 %s never reads closures', async role => {
 render(<VenueDetailPage {...props} role={role} />)
 await act(async () => {})
 expect(listClosures).not.toHaveBeenCalled()
 expect(screen.queryByText('Recorded closures')).not.toBeInTheDocument()
})
test('SCRUM-170 venue change aborts stale reads and never shows old closure data', async () => {
 let finish!: (value: { closures: typeof row[]; nextCursor: null }) => void
 vi.mocked(listClosures).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
 const { rerender } = render(<VenueDetailPage {...props} />)
 await screen.findByRole('button', { name: 'Record temporary closure' })
 const signal = vi.mocked(listClosures).mock.calls[0][3]
 vi.mocked(fetchVenue).mockResolvedValue({ id: 'v2', name: 'Other Hall', status: 'On Hold', location: '', capacity: 1, accessibility: '', facilities: [], supportedLayouts: [] })
 rerender(<VenueDetailPage {...props} venueId="v2" />)
 expect(signal?.aborted).toBe(true)
 await act(async () => finish({ closures: [row], nextCursor: null }))
 expect(await screen.findByText('No recorded closures.')).toBeInTheDocument()
 expect(screen.queryByText('Maintenance', { selector: 'strong' })).not.toBeInTheDocument()
})
test('SCRUM-170 venue polling refreshes every 30s without discarding closure draft, cleans up', async () => {
 const { unmount } = render(<VenueDetailPage {...props} />)
 await fill()
 vi.useFakeTimers()
 // Remount with fake timers so the polling interval is controlled.
 unmount()
 const view = render(<VenueDetailPage {...props} />)
 await act(async () => {})
 fireEvent.click(screen.getByRole('button', { name: 'Record temporary closure' }))
 fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Draft reason' } })
 const count = vi.mocked(fetchVenue).mock.calls.length
 try {
  await act(async () => vi.advanceTimersByTime(30_000))
  expect(fetchVenue).toHaveBeenCalledTimes(count + 1)
  expect(screen.getByLabelText('Reason')).toHaveValue('Draft reason')
  view.unmount()
  await act(async () => vi.advanceTimersByTime(30_000))
  expect(fetchVenue).toHaveBeenCalledTimes(count + 1)
 } finally { vi.useRealTimers() }
})
test.each([false, true])('SCRUM-170 failed polling preserves draft and pending save (saving=%s)', async saving => {
 vi.useFakeTimers()
 let finish!: (value: typeof row) => void
 if (saving) vi.mocked(createClosure).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
 const view = render(<VenueDetailPage {...props} />)
 try {
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: 'Record temporary closure' }))
  fireEvent.change(screen.getByLabelText('Closure start (SGT)'), { target: { value: '2020-01-01T09:00' } })
  fireEvent.change(screen.getByLabelText('Closure end (SGT)'), { target: { value: '2099-01-01T10:00' } })
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Maintenance' } })
  if (saving) {
   fireEvent.click(screen.getByRole('button', { name: 'Preview affected requests' }))
   await act(async () => {})
  }
  if (saving) fireEvent.click(screen.getByRole('button', { name: 'Confirm closure and reject requests' }))
  vi.mocked(fetchVenue).mockRejectedValueOnce(new Error('Venue refresh offline'))
  await act(async () => vi.advanceTimersByTime(30_000))
  expect(screen.getByLabelText('Reason')).toHaveValue('Maintenance')
  expect(screen.getByLabelText('Closure start (SGT)')).toHaveValue('2020-01-01T09:00')
  expect(screen.getByRole('alert')).toHaveTextContent('Venue refresh offline')
  expect(screen.getByRole('heading', { name: 'Grand Hall' })).toBeInTheDocument()
  if (saving) {
   expect(vi.mocked(createClosure).mock.calls[0][6]?.aborted).toBe(false)
   await act(async () => finish(row))
   expect(screen.getByText('Closure recorded.')).toBeInTheDocument()
   expect(listClosures).toHaveBeenCalledTimes(2)
  }
  await act(async () => vi.advanceTimersByTime(30_000))
  expect(screen.queryByText(/Venue refresh offline/)).not.toBeInTheDocument()
  if (!saving) expect(screen.getByLabelText('Reason')).toHaveValue('Maintenance')
 } finally { view.unmount(); vi.useRealTimers() }
})

test('SCRUM-170 failed new venue load never exposes the previous venue', async () => {
 const view = render(<VenueDetailPage {...props} />)
 await fill()
 vi.mocked(fetchVenue).mockRejectedValueOnce(new Error('Other venue unavailable'))
 view.rerender(<VenueDetailPage {...props} venueId="v2" />)
 expect(screen.queryByRole('heading', { name: 'Grand Hall' })).not.toBeInTheDocument()
 expect(await screen.findByRole('alert')).toHaveTextContent('Other venue unavailable')
 expect(screen.queryByRole('region', { name: 'Temporary venue closures' })).not.toBeInTheDocument()
})
test('SCRUM-170 initial load failure shows full error without closures', async () => {
 vi.mocked(fetchVenue).mockRejectedValueOnce(new Error('Initial venue unavailable'))
 render(<VenueDetailPage {...props} />)
 expect(await screen.findByRole('alert')).toHaveTextContent('Initial venue unavailable')
 expect(screen.queryByRole('region', { name: 'Temporary venue closures' })).not.toBeInTheDocument()
})

test('SCRUM-170 identity change clears previous staff errors and aborts late failures', async () => {
 let reject!: (cause: unknown) => void
 vi.mocked(listClosures).mockReturnValueOnce(new Promise((_, fail) => { reject = fail }))
 const view = render(<VenueDetailPage {...props} />)
 await fill()
 const signal = vi.mocked(listClosures).mock.calls[0][3]
 view.rerender(<VenueDetailPage {...props} user={{ ...user, id: 'staff2' }} />)
 expect(signal?.aborted).toBe(true)
 await act(async () => reject(new Error('Old staff error')))
 expect(await screen.findByText('No recorded closures.')).toBeInTheDocument()
 expect(screen.queryByText('Old staff error')).not.toBeInTheDocument()
})
test('SCRUM-170 cancel preserves draft, duplicate submit is ignored, non-Error save failure remains visible', async () => {
 let reject!: (cause: unknown) => void
 vi.mocked(createClosure).mockReturnValueOnce(new Promise((_, fail) => { reject = fail }))
 render(<VenueDetailPage {...props} />)
 await fill()
 fireEvent.click(screen.getByRole('button', { name: 'Discard closure draft' }))
 expect(screen.queryByLabelText('Reason')).not.toBeInTheDocument()
 fireEvent.click(screen.getByRole('button', { name: 'Record temporary closure' }))
 expect(screen.getByLabelText('Reason')).toHaveValue('Maintenance')
 fireEvent.click(screen.getByRole('button', { name: 'Preview affected requests' }))
 await screen.findByRole('region', { name: 'Confirm temporary closure' })
 const form = screen.getByRole('button', { name: 'Confirm closure and reject requests' }).closest('form')!
 fireEvent.submit(form); fireEvent.submit(form)
 expect(createClosure).toHaveBeenCalledTimes(1)
 await act(async () => reject('failure'))
 expect(await screen.findByText('Unable to record closure.')).toBeInTheDocument()
})
test('SCRUM-170 refresh supersedes stale page, nullable legacy metadata and duplicate page rows stay readable', async () => {
 let finish!: (value: { closures: typeof row[]; nextCursor: null }) => void
 vi.mocked(listClosures).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
 render(<VenueDetailPage {...props} />)
 const button = await screen.findByRole('button', { name: 'Refresh closures' })
 const signal = vi.mocked(listClosures).mock.calls[0][3]
 vi.mocked(listClosures).mockResolvedValueOnce({ closures: [{ ...row, createdBy: null, createdAt: null }], nextCursor: 'next' })
 fireEvent.click(button)
 expect(signal?.aborted).toBe(true)
 expect(await screen.findByText(/Creation time not recorded/)).toBeInTheDocument()
 await act(async () => finish({ closures: [], nextCursor: null }))
 vi.mocked(listClosures).mockResolvedValueOnce({ closures: [row, { ...row, closureId: 'c2', reason: 'Another' }], nextCursor: null })
 fireEvent.click(screen.getByRole('button', { name: 'Load more closures' }))
 expect(await screen.findByText('Another')).toBeInTheDocument()
 expect(screen.getAllByText('Maintenance', { selector: 'strong' })).toHaveLength(1)
})
test('SCRUM-170 list non-Error fallback and stale save failure do not leak to another identity', async () => {
 vi.mocked(listClosures).mockRejectedValueOnce('offline')
 let reject!: (cause: unknown) => void
 vi.mocked(createClosure).mockReturnValueOnce(new Promise((_, fail) => { reject = fail }))
 const view = render(<VenueDetailPage {...props} />)
 await fill()
 expect(await screen.findByText('Unable to load recorded closures.')).toBeInTheDocument()
 fireEvent.click(screen.getByRole('button', { name: 'Confirm closure and reject requests' }))
 view.rerender(<VenueDetailPage {...props} user={{ ...user, id: 'staff2' }} />)
 await act(async () => reject(new Error('Old save error')))
 expect(screen.queryByText('Old save error')).not.toBeInTheDocument()
})
test('closure form marks mandatory fields without changing labels and explains the preselected venue', async () => {
 render(<VenueDetailPage {...props} />)
 fireEvent.click(await screen.findByRole('button', { name: 'Record temporary closure' }))
 expect(screen.getByRole('form', { name: 'Record temporary closure' })).toBeInTheDocument()
 expect(screen.getByText('Required fields')).toHaveTextContent('* Required fields')
 for (const label of ['Closure start (SGT)', 'Closure end (SGT)', 'Reason']) {
  const control = screen.getByLabelText(label, { exact: true })
  expect(control).toBeRequired()
  expect(control.parentElement?.querySelector('.required-marker')).toHaveAttribute('aria-hidden', 'true')
 }
 expect(screen.getByLabelText('Closure venue', { exact: true })).toHaveAttribute('readonly')
 expect(screen.getByLabelText('Closure venue', { exact: true })).toHaveAccessibleDescription('Preselected venue. This cannot be changed here.')
})
async function fill() {
 fireEvent.click(await screen.findByRole('button', { name: 'Record temporary closure' }))
 fireEvent.change(screen.getByLabelText('Closure start (SGT)'), { target: { value: '2020-01-01T09:00' } })
 fireEvent.change(screen.getByLabelText('Closure end (SGT)'), { target: { value: '2099-01-01T10:00' } })
 fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Maintenance' } })
 fireEvent.click(screen.getByRole('button', { name: 'Preview affected requests' }))
 await screen.findByRole('region', { name: 'Confirm temporary closure' })
}
test('SCRUM-170 staff records ongoing closure inline for maintenance venue, only after persistence', async () => {
 let finish!: (value: typeof row) => void
 vi.mocked(createClosure).mockReturnValue(new Promise(resolve => { finish = resolve }))
 render(<VenueDetailPage {...props} />)
 await fill()
 expect(screen.getByLabelText('Closure venue')).toHaveValue('Grand Hall')
 expect(screen.getByLabelText('Closure venue')).toHaveAttribute('readonly')
 fireEvent.click(screen.getByRole('button', { name: 'Confirm closure and reject requests' }))
 expect(screen.getByRole('button', { name: 'Working…' })).toBeDisabled()
 expect(screen.queryByText('Closure recorded.')).not.toBeInTheDocument()
 await act(async () => finish(row))
 expect(await screen.findByText('Closure recorded.')).toBeInTheDocument()
 expect(createClosure).toHaveBeenCalledTimes(1)
 expect(listClosures).toHaveBeenCalledTimes(2)
 expect(screen.getByText(/Saving a closure rejects overlapping/)).toBeInTheDocument()
})
