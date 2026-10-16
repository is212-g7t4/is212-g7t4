import { beforeEach, expect, test, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { fetchSafetyReview } from './safetyCheck'
import type { SafetyReview as SafetyReviewData } from './safetyCheck'
import { SafetyReview } from './SafetyReview'

vi.mock('./safetyCheck', async () => {
  const actual = await vi.importActual<typeof import('./safetyCheck')>('./safetyCheck')
  return { ...actual, fetchSafetyReview: vi.fn() }
})

const eventId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const officerId = '33333333-3333-4333-8333-333333333333'

const review: SafetyReviewData = {
  event: { accessibilityNeeds: 'Step-free access' } as SafetyReviewData['event'],
  safetyCheck: {
    id: 'round-2', eventId, roundNumber: 2, submittedBy: officerId,
    submittedAt: '2026-10-01T09:00:00Z', equipmentPlacementNotes: null,
    crowdMovementNotes: 'Use east exit', status: 'Pending', decidedBy: null,
    decidedAt: null, remarks: null, withdrawnAt: null, withdrawnBy: null,
    withdrawalReason: null, flags: [],
  },
  venues: [{
    bookingId: 'booking-1', venueId: 'venue-1', name: 'Main Hall',
    expectedAttendance: '150', capacity: 100, overCapacity: true,
    layout: 'Theatre', emergencyAccess: null, accessibility: null,
    restrictions: null, venueRequirements: 'Stage access', status: 'Approved',
  }],
  equipment: [{
    requestId: 'request-1', name: 'Microphone', description: 'Wireless microphone',
    quantity: 2, technicalRequirements: null, status: 'Approved',
  }],
  history: [{
    id: 'round-1', eventId, roundNumber: 1, submittedBy: officerId,
    submittedAt: '2026-09-20T09:00:00Z', equipmentPlacementNotes: null,
    crowdMovementNotes: null, status: 'Changes Requested', decidedBy: officerId,
    decidedAt: '2026-09-21T09:00:00Z', remarks: 'Exit route is unclear.',
    withdrawnAt: null, withdrawnBy: null, withdrawalReason: null,
    flags: [{ id: 'flag-1', area: 'venue arrangement', bookingId: null,
      equipmentRequestId: null, changeRequired: 'Keep the west exit clear.' }],
  }],
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(fetchSafetyReview).mockResolvedValue(review)
})

test('shows capacity warnings, missing details and previous decision reasons and changes', async () => {
  render(<SafetyReview eventId={eventId} safetyOfficerId={officerId} />)

  expect(await screen.findByText('Over capacity: expected attendance exceeds this venue\'s capacity.')).toBeInTheDocument()
  expect(screen.getByText('150')).toBeInTheDocument()
  expect(screen.getByText('100')).toBeInTheDocument()
  expect(screen.getAllByText('Not provided').length).toBeGreaterThanOrEqual(4)
  expect(screen.getByText('Use east exit')).toBeInTheDocument()
  expect(screen.getByText('Exit route is unclear.')).toBeInTheDocument()
  expect(screen.getByText('Keep the west exit clear.')).toBeInTheDocument()
  expect(screen.getByText(/Microphone/)).toBeInTheDocument()
})