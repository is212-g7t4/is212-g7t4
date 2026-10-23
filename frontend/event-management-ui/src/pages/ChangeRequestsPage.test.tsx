import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { ChangeRequestsPage } from './ChangeRequestsPage'
import { ChangeRequestReviewError, decideChangeRequest, fetchPendingChangeRequests } from '../features/event/changeRequests'
import type { EventChangeRequest } from '../features/event/changeRequests'

vi.mock('../features/event/changeRequests', async (original) => ({
  ...await original<typeof import('../features/event/changeRequests')>(),
  fetchPendingChangeRequests: vi.fn(),
  decideChangeRequest: vi.fn(),
}))

const coordinatorId = '11111111-1111-4111-8111-111111111111'
const change: EventChangeRequest = {
  id: '22222222-2222-4222-8222-222222222222',
  eventId: '33333333-3333-4333-8333-333333333333',
  proposedChanges: { expectedAttendance: '60', venueRequirements: 'Main hall' },
  status: 'Pending Review',
  requestedAt: '2026-10-23T04:05:00+00:00',
  requestedBy: '44444444-4444-4444-8444-444444444444',
  reason: 'More community members registered.',
  reviewedBy: null,
  reviewedAt: null,
  rejectionReason: null,
  event: {
    id: '33333333-3333-4333-8333-333333333333',
    eventName: 'Community Workshop',
    description: 'Original description',
    purpose: 'Learning',
    preferredStartDate: '2026-11-01T09:00:00',
    preferredEndDate: '2026-11-01T12:00:00',
    expectedAttendance: '30',
    venueRequirements: 'Seminar room',
    accessibilityNeeds: '',
    equipmentRequirements: '',
    registrationNeeds: '',
    status: 'Approved',
    submittedAt: '2026-10-01T00:00:00Z',
    coordinatorId,
    decision: null,
    decisionHistory: [],
    actionDetails: '',
    actionHistory: [],
  },
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(fetchPendingChangeRequests).mockResolvedValue([change])
  vi.mocked(decideChangeRequest).mockResolvedValue({
    id: change.id,
    eventId: change.eventId,
    status: 'Approved',
    reviewedBy: coordinatorId,
    reviewedAt: '2026-10-24T02:00:00Z',
    rejectionReason: null,
    event: change.event,
  })
})

test('AC1 AC2 shows pending requests with original and proposed values, reason and timestamp', async () => {
  render(<ChangeRequestsPage role="Event Coordinator" coordinatorId={coordinatorId} coordinatorName="Alicia Tan" />)

  expect(await screen.findByRole('heading', { name: 'Community Workshop' })).toBeInTheDocument()
  expect(screen.getByText('More community members registered.')).toBeInTheDocument()
  expect(screen.getByRole('columnheader', { name: 'Original value' })).toBeInTheDocument()
  expect(screen.getByRole('columnheader', { name: 'Proposed value' })).toBeInTheDocument()
  expect(screen.getByText('30')).toBeInTheDocument()
  expect(screen.getByText('60')).toBeInTheDocument()
  expect(screen.getByText('Seminar room')).toBeInTheDocument()
  expect(screen.getByText('Main hall')).toBeInTheDocument()
  expect(screen.getByText(/Requested .* SGT/)).toBeInTheDocument()
})

test('AC3 approves a request and removes it from the pending queue', async () => {
  render(<ChangeRequestsPage role="Event Coordinator" coordinatorId={coordinatorId} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Approve changes' }))

  await waitFor(() => expect(decideChangeRequest).toHaveBeenCalledWith(change.id, coordinatorId, 'Approved', undefined))
  expect(await screen.findByText('Community Workshop change request approved.')).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Community Workshop' })).not.toBeInTheDocument()
})

test('AC4 rejection requires a reason and sends it', async () => {
  vi.mocked(decideChangeRequest).mockResolvedValueOnce({
    id: change.id, eventId: change.eventId, status: 'Rejected', reviewedBy: coordinatorId,
    reviewedAt: '2026-10-24T02:00:00Z', rejectionReason: 'Insufficient venue capacity.', event: change.event,
  })
  render(<ChangeRequestsPage role="Event Coordinator" coordinatorId={coordinatorId} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Reject changes' }))
  const confirm = screen.getByRole('button', { name: 'Confirm rejection' })
  expect(confirm).toBeDisabled()
  fireEvent.change(screen.getByLabelText(/Reason for rejection/), { target: { value: 'Insufficient venue capacity.' } })
  fireEvent.click(confirm)

  await waitFor(() => expect(decideChangeRequest).toHaveBeenCalledWith(
    change.id, coordinatorId, 'Rejected', 'Insufficient venue capacity.',
  ))
})

test('an impact conflict remains visible and the request stays pending', async () => {
  vi.mocked(decideChangeRequest).mockRejectedValueOnce(new ChangeRequestReviewError(
    'This request cannot be approved.',
    'CHANGE_CONTRADICTS_ARRANGEMENTS',
    [{ field: 'expectedAttendance', area: 'venue', message: 'Venue too small.' }],
  ))
  render(<ChangeRequestsPage role="Event Coordinator" coordinatorId={coordinatorId} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Approve changes' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Venue too small.')
  expect(screen.getByRole('heading', { name: 'Community Workshop' })).toBeInTheDocument()
})

test('non-coordinators cannot view the queue', () => {
  render(<ChangeRequestsPage role="Event Organiser" coordinatorId="organiser" />)
  expect(screen.getByText('Change requests are visible to Event Coordinators.')).toBeInTheDocument()
  expect(fetchPendingChangeRequests).not.toHaveBeenCalled()
})
