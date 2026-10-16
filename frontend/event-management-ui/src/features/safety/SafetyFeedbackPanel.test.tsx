import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { SafetySubmitError, fetchSafetyFeedback, fetchSafetyResubmissionReadiness, resubmitSafetyCheck } from './safetyCheck'
import type { SafetyCheckRecord } from './safetyCheck'
import { SafetyFeedbackPanel } from './SafetyFeedbackPanel'

vi.mock('./safetyCheck', async (importOriginal) => ({
  ...await importOriginal<typeof import('./safetyCheck')>(), fetchSafetyFeedback: vi.fn(),
  fetchSafetyResubmissionReadiness: vi.fn(), resubmitSafetyCheck: vi.fn(),
}))

const latest: SafetyCheckRecord = {
  id: 'round-2', eventId: 'event-1', roundNumber: 2, submittedBy: 'coordinator-1',
  submittedAt: '2026-10-15T01:00:00Z', equipmentPlacementNotes: null, crowdMovementNotes: null,
  status: 'Changes Requested', decidedBy: 'officer-1', decidedAt: '2026-10-16T02:00:00Z',
  remarks: 'Emergency access is obstructed.', withdrawnAt: null, withdrawnBy: null, withdrawalReason: null,
  flags: [
    { id: 'venue-flag', area: 'venue arrangement', bookingId: 'booking-1', equipmentRequestId: null, changeRequired: 'Keep the emergency exit clear.' },
    { id: 'equipment-flag', area: 'technical arrangement', bookingId: null, equipmentRequestId: 'request-1', changeRequired: 'Move cables away from the walkway.' },
  ],
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(fetchSafetyFeedback).mockResolvedValue([latest])
  vi.mocked(fetchSafetyResubmissionReadiness).mockResolvedValue({ ready: true, eventStatus: 'Safety Changes Requested', outstanding: [] })
  vi.mocked(resubmitSafetyCheck).mockResolvedValue({ safetyCheck: { ...latest, roundNumber: 3, status: 'Pending' }, event: {} as never })
})

const onResubmitted = vi.fn()
const renderPanel = () => render(<SafetyFeedbackPanel eventId="event-1" coordinatorId="coordinator-1" onResubmitted={onResubmitted} />)

test('resubmit stays disabled while equipment readiness is loading', async () => {
  vi.mocked(fetchSafetyResubmissionReadiness).mockReturnValue(new Promise(() => {}))
  renderPanel()
  await screen.findByText('Changes Requested')
  expect(screen.getByRole('button', { name: 'Resubmit Safety Check' })).toBeDisabled()
})

// Safety revision AC3: the coordinator cannot resubmit while equipment still awaits Technical Support review.
test('pending equipment disables resubmission even when venue feedback is present', async () => {
  vi.mocked(fetchSafetyResubmissionReadiness).mockResolvedValue({ ready: false, eventStatus: 'Safety Changes Requested', outstanding: [
    { type: 'equipment', id: 'request-1', status: 'Pending', label: 'Microphone', reason: 'Waiting for review.' },
  ] })
  renderPanel()
  expect(await screen.findByText(/Outstanding equipment requests: 1/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Resubmit Safety Check' })).toBeDisabled()
})

// Safety revision AC5 (UI): ready arrangements enable resubmission and preserve planning notes in the request.
// Readiness and the submission result are mocked; this does not prove database round creation.
test('no pending equipment enables resubmission and carries previous planning notes', async () => {
  vi.mocked(fetchSafetyFeedback).mockResolvedValue([{ ...latest, equipmentPlacementNotes: 'Cables secured.', crowdMovementNotes: 'Exit route clear.' }])
  renderPanel()
  const button = screen.getByRole('button', { name: 'Resubmit Safety Check' })
  await waitFor(() => expect(button).toBeEnabled())
  fireEvent.click(button)
  await waitFor(() => expect(onResubmitted).toHaveBeenCalledOnce())
  expect(resubmitSafetyCheck).toHaveBeenCalledWith({ eventId: 'event-1', coordinatorId: 'coordinator-1',
    equipmentPlacementNotes: 'Cables secured.', crowdMovementNotes: 'Exit route clear.' })
})

test('equipment lookup failure keeps feedback visible and resubmit disabled', async () => {
  vi.mocked(fetchSafetyResubmissionReadiness).mockRejectedValue(new Error('Equipment service unavailable.'))
  renderPanel()
  expect(await screen.findByRole('alert')).toHaveTextContent('Equipment service unavailable.')
  expect(await screen.findByText(latest.remarks!)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Resubmit Safety Check' })).toBeDisabled()
})

// Safety revision AC2: Venue Staff re-review must finish before the coordinator can resubmit.
test('pending venue blocks resubmission even when equipment is approved', async () => {
  vi.mocked(fetchSafetyResubmissionReadiness).mockResolvedValue({ ready: false, eventStatus: 'Safety Changes Requested', outstanding: [
    { type: 'venue', id: 'booking-1', status: 'Pending Review', label: 'Grand Hall', reason: 'Waiting for Venue Staff approval.' },
  ] })
  renderPanel()
  expect(await screen.findByText(/Outstanding venue requests: 1/)).toBeInTheDocument()
  expect(screen.getByText('Waiting for Venue Staff approval.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Resubmit Safety Check' })).toBeDisabled()
})

// Safety revision AC2: revising a booking invalidates displayed readiness until it is checked again.
test('venue edits trigger a new readiness check and disable resubmission', async () => {
  const view = render(<SafetyFeedbackPanel eventId="event-1" coordinatorId="coordinator-1" refreshKey={0} onResubmitted={onResubmitted} />)
  await waitFor(() => expect(screen.getByRole('button', { name: 'Resubmit Safety Check' })).toBeEnabled())
  vi.mocked(fetchSafetyResubmissionReadiness).mockResolvedValue({ ready: false, eventStatus: 'Safety Changes Requested', outstanding: [
    { type: 'venue', id: 'booking-1', status: 'Pending Review', label: 'Grand Hall', reason: 'Waiting for review.' },
  ] })
  view.rerender(<SafetyFeedbackPanel eventId="event-1" coordinatorId="coordinator-1" refreshKey={1} onResubmitted={onResubmitted} />)
  await waitFor(() => expect(fetchSafetyResubmissionReadiness).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Resubmit Safety Check' })).toBeDisabled())
})

test('new pending equipment reported by server disables resubmission', async () => {
  vi.mocked(resubmitSafetyCheck).mockRejectedValue(new SafetySubmitError('Equipment needs review.', {
    code: 'ARRANGEMENTS_OUTSTANDING', outstanding: [
      { type: 'equipment', id: 'new-request', status: 'Pending', label: 'Speaker', reason: 'Awaiting review.' },
    ],
  }))
  renderPanel()
  const button = screen.getByRole('button', { name: 'Resubmit Safety Check' })
  await waitFor(() => expect(button).toBeEnabled())
  fireEvent.click(button)
  expect(await screen.findByRole('alert')).toHaveTextContent('Equipment needs review.')
  expect(button).toBeDisabled()
  expect(onResubmitted).not.toHaveBeenCalled()
})

test('submission in flight is disabled to prevent duplicate review rounds', async () => {
  vi.mocked(resubmitSafetyCheck).mockReturnValue(new Promise(() => {}))
  renderPanel()
  const button = screen.getByRole('button', { name: 'Resubmit Safety Check' })
  await waitFor(() => expect(button).toBeEnabled())
  fireEvent.click(button)
  expect(await screen.findByRole('button', { name: 'Resubmitting...' })).toBeDisabled()
  expect(resubmitSafetyCheck).toHaveBeenCalledOnce()
})

test('an already-open round refreshes the event instead of creating another round', async () => {
  vi.mocked(resubmitSafetyCheck).mockRejectedValue(new SafetySubmitError('Already awaiting review.', { code: 'SAFETY_CHECK_ALREADY_PENDING' }))
  renderPanel()
  const button = screen.getByRole('button', { name: 'Resubmit Safety Check' })
  await waitFor(() => expect(button).toBeEnabled())
  fireEvent.click(button)
  await waitFor(() => expect(onResubmitted).toHaveBeenCalledOnce())
})

test('a failed resubmission leaves feedback intact and allows retry', async () => {
  vi.mocked(resubmitSafetyCheck).mockRejectedValue(new Error('Safety service unavailable.'))
  renderPanel()
  const button = screen.getByRole('button', { name: 'Resubmit Safety Check' })
  await waitFor(() => expect(button).toBeEnabled())
  fireEvent.click(button)
  expect(await screen.findByRole('alert')).toHaveTextContent('Safety service unavailable.')
  expect(screen.getByText(latest.remarks!)).toBeInTheDocument()
  await waitFor(() => expect(button).toBeEnabled())
  expect(onResubmitted).not.toHaveBeenCalled()
})

// Safety revision AC1: display the officer's decision, reason, requested changes and affected arrangements.
test('AC1: shows the decision, reason and requested change for each affected area', async () => {
  renderPanel()
  expect(await screen.findByText('Changes Requested')).toBeInTheDocument()
  expect(screen.getByText(latest.remarks!)).toBeInTheDocument()
  expect(screen.getByText('Venue arrangement').parentElement).toHaveTextContent('Keep the emergency exit clear.')
  expect(screen.getByText('Technical / equipment arrangement').parentElement).toHaveTextContent('Move cables away from the walkway.')
  expect(screen.getByText('Venue booking: booking-1')).toBeInTheDocument()
  expect(screen.getByText('Equipment request: request-1')).toBeInTheDocument()
  expect(screen.getByText(/10:00:00 am/)).toHaveTextContent('SGT')
  expect(fetchSafetyFeedback).toHaveBeenCalledWith('event-1', 'coordinator-1')
})

// Safety revision AC5 (history display): earlier rounds remain readable separately from the latest feedback.
test('shows the latest round first and preserves earlier feedback separately', async () => {
  vi.mocked(fetchSafetyFeedback).mockResolvedValue([
    { ...latest, id: 'round-1', roundNumber: 1, remarks: 'Earlier reason.', flags: [] }, latest,
  ])
  renderPanel()
  await screen.findByText(latest.remarks!)
  const history = screen.getByText('Earlier safety review rounds (1)').closest('details')!
  expect(within(history).getByText('Earlier reason.')).toBeInTheDocument()
  expect(within(history).queryByText(latest.remarks!)).not.toBeInTheDocument()
  expect(history).not.toHaveAttribute('open')
})

test('shows loading while feedback is being fetched', () => {
  vi.mocked(fetchSafetyFeedback).mockReturnValue(new Promise(() => {}))
  renderPanel()
  expect(screen.getByText('Loading safety feedback...')).toBeInTheDocument()
})

test('shows an explicit empty state rather than inventing feedback', async () => {
  vi.mocked(fetchSafetyFeedback).mockResolvedValue([])
  renderPanel()
  expect(await screen.findByText('No safety feedback is available for this event.')).toBeInTheDocument()
})

test.each([new Error('Safety service unavailable.'), 'unavailable'])(
  'explains a feedback load failure: %s', async (error) => {
    vi.mocked(fetchSafetyFeedback).mockRejectedValue(error)
    renderPanel()
    expect(await screen.findByRole('alert')).toHaveTextContent(error instanceof Error ? error.message : 'Unable to load safety feedback.')
  },
)

test('does not present an undecided round as an approval', async () => {
  vi.mocked(fetchSafetyFeedback).mockResolvedValue([{ ...latest, status: 'Pending', remarks: null, decidedAt: null, flags: [] }])
  renderPanel()
  expect(await screen.findByText('Awaiting decision')).toBeInTheDocument()
  expect(screen.getByText('No reason recorded.')).toBeInTheDocument()
  expect(screen.queryByText('Affected areas and requested changes')).not.toBeInTheDocument()
})