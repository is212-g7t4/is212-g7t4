/**
 * SCRUM-48 supporting targeted equipment-view rules for original AC1/AC2/AC3.
 * Public component seam with API doubles. Existing review behaviors are exercised
 * only where they protect a notification target; no dispatch/persistence claim.
 * Retrospective regression coverage, not a claimed RED→GREEN implementation.
 * Runs in jsdom with doubled API functions, not a browser E2E journey.
 * AC = acceptance criterion; all target/filter/dialog cases here are supporting
 * rules for AC1 submission, AC2 approval and AC3 rejection, not additional ACs.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { EquipmentRequestsPage } from './EquipmentRequestsPage'
import { fetchEventReservations, reviewEquipmentRequest } from '../features/equipment/requests'
import type { EquipmentRequest, EventReservation, ReviewedRequest } from '../features/equipment/requests'
import type { User } from '../types'

vi.mock('../features/equipment/requests', async original => ({
  ...await original<typeof import('../features/equipment/requests')>(),
  fetchEventReservations: vi.fn(), reviewEquipmentRequest: vi.fn(),
}))
// Deliberately short IDs isolate component filtering; UUID validation belongs to
// scrum48-destination.test.ts. API models follow features/equipment/requests.ts.
const user: User = { id: 'tech', role: 'Technical Support', username: 'Tech', organization: '', email: '' }
const first: EquipmentRequest = { id: 'mic', eventId: 'symposium', equipmentId: 'eq1', quantityRequested: 5, technicalRequirements: '', status: 'Pending', reviewedBy: null, equipment: { description: 'Mic', type: 'AV', totalQuantity: 10, status: 'Available' }, availability: null }
const event = (requests: EquipmentRequest[]): EventReservation => ({ eventId: 'symposium', eventName: 'Symposium', eventStatus: 'Under Review', coordinatorId: null, startTime: null, endTime: null, requests })
const show = (targetSearch = '?event=symposium&request=mic&request=projector') => render(<EquipmentRequestsPage role={user.role} user={user} targetSearch={targetSearch} />)
beforeEach(() => {
  vi.mocked(fetchEventReservations).mockReset().mockResolvedValue([event([first, { ...first, id: 'projector', equipment: { ...first.equipment!, description: 'Projector' } }])])
  vi.mocked(reviewEquipmentRequest).mockReset().mockResolvedValue({ ...first, status: 'Approved' })
})

describe('SCRUM-48 supporting target-view decision boundaries', () => {
  it('reviewing under Pending removes only the decided target and warns that it left this view', async () => {
    // Arrange: two targeted pending records and the public status filter.
    show()
    await screen.findByText('Mic')
    await userEvent.selectOptions(screen.getByLabelText('Filter by status'), 'Pending')
    const row = (await screen.findByText('Mic')).closest('tr')!
    // Act: decide one visible target rather than an event-wide batch.
    await userEvent.click(within(row).getByRole('button', { name: 'Approve' }))
    // Assert: second target survives; the removed first record is not substituted.
    await waitFor(() => expect(screen.queryByText('Mic')).not.toBeInTheDocument())
    expect(screen.getByText('Projector')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Some requested equipment is unavailable or you no longer have access.')
    expect(reviewEquipmentRequest).toHaveBeenCalledWith('mic', 'Approved')
  })

  it('an ordinary empty list is not incorrectly described as a missing notification target', async () => {
    // Arrange / Act: explicitly no target and no accessible records.
    vi.mocked(fetchEventReservations).mockResolvedValue([])
    show('')
    // Assert: distinguish ordinary navigation from an unavailable deep link.
    expect(await screen.findByText('No equipment requests found.')).toBeInTheDocument()
    expect(screen.queryByText('This equipment request is unavailable or you no longer have access.')).not.toBeInTheDocument()
  })

  it('catalogue-deleted equipment remains safely identifiable for a targeted rejection', async () => {
    // Arrange: request still exists but catalogue enrichment is unavailable.
    vi.mocked(fetchEventReservations).mockResolvedValue([event([{ ...first, equipment: null }])])
    show('?event=symposium&request=mic')
    await screen.findByText('Unknown equipment')
    // Act / Assert: the real dialog names the fallback and current event, not stale data.
    await userEvent.click(screen.getByRole('button', { name: 'Reject' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('Unknown equipment for Symposium')
    expect(screen.getByRole('button', { name: 'Confirm rejection' })).toBeDisabled()
    expect(reviewEquipmentRequest).not.toHaveBeenCalled()
  })

  it('native dialog cancel during an unresolved rejection cannot discard the pending decision', async () => {
    // Arrange: only the external decision response is deferred.
    let finish!: (value: ReviewedRequest) => void
    vi.mocked(reviewEquipmentRequest).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    show('?event=symposium&request=mic')
    await userEvent.click(await screen.findByRole('button', { name: 'Reject' }))
    await userEvent.type(screen.getByRole('textbox', { name: /Reason for rejection/ }), 'No technician.')
    // Act: submit, then simulate the native Escape/cancel event in jsdom while saving.
    // Why: pending rejection state must not disappear or permit a duplicate write.
    await userEvent.click(screen.getByRole('button', { name: 'Confirm rejection' }))
    const dialog = screen.getByRole('dialog')
    fireEvent(dialog, new Event('cancel', { bubbles: false, cancelable: true }))
    // Assert: cancel is ignored during the write; public controls cannot duplicate it.
    expect(dialog).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Rejecting...' })).toBeDisabled()
    expect(reviewEquipmentRequest).toHaveBeenCalledTimes(1)
    finish({ ...first, status: 'Rejected', rejectionReason: 'No technician.' })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(within(screen.getByText('Mic').closest('tr')!).getByText('Rejected')).toBeInTheDocument()
  })
})
