/**
 * SCRUM-149: the submit-for-safety-check panel.
 *
 * AC1 a successful submission tells the coordinator, and the page reloads so
 *     the badge reads 'Pending Safety Check'.
 * AC2 outstanding arrangements are listed and submit is disabled.
 * AC3 both notes are optional, limited to 2000 characters, and sent.
 * AC4 the button can't be clicked twice, and a 409 is explained.
 *
 * Rule changed 29 Oct 2026: rejected equipment no longer blocks (dead-end
 * fix). The server drops rejected items from `outstanding`; the panel only
 * adds a hint saying so.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import type { Mock } from 'vitest'
import { SafetySubmitError, fetchSafetyReadiness, submitSafetyCheck } from './safetyCheck'
import { SafetySubmitPanel } from './SafetySubmitPanel'

vi.mock('./safetyCheck', async () => {
  const actual = await vi.importActual<typeof import('./safetyCheck')>('./safetyCheck')
  return { ...actual, fetchSafetyReadiness: vi.fn(), submitSafetyCheck: vi.fn() }
})

const eventId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const coordinatorId = '11111111-1111-4111-8111-111111111111'

const ready = { ready: true, eventStatus: 'Approved', outstanding: [], openSafetyCheck: null }
const outstanding = [
  {
    type: 'venue' as const, id: 'booking-a', status: 'Pending Review',
    label: 'Booking 12 Nov 2026 09:00–17:00 (120 people)',
    reason: 'Waiting for Venue Staff approval.',
  },
  {
    type: 'equipment' as const, id: 'request-a', status: 'Pending',
    label: 'Equipment request × 2',
    reason: 'Waiting for Technical Support approval.',
  },
]

let onSubmitted: Mock<() => void>

const renderPanel = (refreshKey = 0) => render(<SafetySubmitPanel
  eventId={eventId}
  coordinatorId={coordinatorId}
  refreshKey={refreshKey}
  onSubmitted={onSubmitted}
/>)

const submitButton = () => screen.getByRole('button', { name: /Submit for safety check/ })

beforeEach(() => {
  vi.resetAllMocks()
  onSubmitted = vi.fn<() => void>()
  vi.mocked(fetchSafetyReadiness).mockResolvedValue(ready)
})

test('AC2: outstanding arrangements are listed and submit stays disabled', async () => {
  vi.mocked(fetchSafetyReadiness).mockResolvedValue({
    ready: false, eventStatus: 'Approved', outstanding, openSafetyCheck: null,
  })
  renderPanel()

  expect(await screen.findByText('Before you can submit for a safety check')).toBeInTheDocument()
  expect(screen.getByText('Booking 12 Nov 2026 09:00–17:00 (120 people)')).toBeInTheDocument()
  expect(screen.getByText('Waiting for Venue Staff approval.')).toBeInTheDocument()
  expect(screen.getByText('Equipment request × 2')).toBeInTheDocument()
  expect(screen.getByText('Waiting for Technical Support approval.')).toBeInTheDocument()
  expect(screen.getByText('Pending Review')).toBeInTheDocument()
  expect(submitButton()).toBeDisabled()
})

test('AC2: a ready event shows no blocked list and an enabled button', async () => {
  renderPanel()

  await waitFor(() => expect(submitButton()).toBeEnabled())
  expect(screen.queryByText('Before you can submit for a safety check')).not.toBeInTheDocument()
  expect(fetchSafetyReadiness).toHaveBeenCalledWith(eventId, coordinatorId)
})

const rejectedHint = "Rejected venue bookings and equipment requests don't block a safety check. The Safety Officer still sees them in the review."

test('shows the rejected-requests hint once readiness has loaded (ready)', async () => {
  renderPanel()

  expect(await screen.findByText(rejectedHint)).toBeInTheDocument()
  expect(submitButton()).toBeEnabled()
})

test('shows the rejected-requests hint once readiness has loaded (not ready)', async () => {
  vi.mocked(fetchSafetyReadiness).mockResolvedValue({
    ready: false, eventStatus: 'Approved', outstanding, openSafetyCheck: null,
  })
  renderPanel()

  expect(await screen.findByText(rejectedHint)).toBeInTheDocument()
  expect(submitButton()).toBeDisabled()
})

test('AC1, AC3: submitting sends both notes and reloads the page', async () => {
  vi.mocked(submitSafetyCheck).mockResolvedValue({
    safetyCheck: { roundNumber: 1 },
    event: {},
  } as never)
  renderPanel()
  await waitFor(() => expect(submitButton()).toBeEnabled())

  fireEvent.change(screen.getByLabelText('Equipment placement notes'), {
    target: { value: 'Speakers either side of the stage.' },
  })
  fireEvent.change(screen.getByLabelText('Expected crowd movement notes'), {
    target: { value: 'Entry through Door A.' },
  })
  fireEvent.click(submitButton())

  expect(await screen.findByText('Submitted for safety check.')).toBeInTheDocument()
  expect(submitSafetyCheck).toHaveBeenCalledWith({
    eventId,
    coordinatorId,
    equipmentPlacementNotes: 'Speakers either side of the stage.',
    crowdMovementNotes: 'Entry through Door A.',
  })
  expect(onSubmitted).toHaveBeenCalled()
})

test('AC3: the notes are optional, and blank ones are not sent', async () => {
  vi.mocked(submitSafetyCheck).mockResolvedValue({ safetyCheck: {}, event: {} } as never)
  renderPanel()
  await waitFor(() => expect(submitButton()).toBeEnabled())

  fireEvent.change(screen.getByLabelText('Equipment placement notes'), { target: { value: '   ' } })
  fireEvent.click(submitButton())

  await waitFor(() => expect(submitSafetyCheck).toHaveBeenCalledWith({
    eventId,
    coordinatorId,
    equipmentPlacementNotes: undefined,
    crowdMovementNotes: undefined,
  }))
})

test('AC3: both notes are capped at 2000 characters, with a running count', async () => {
  renderPanel()
  const placement = await screen.findByLabelText('Equipment placement notes')

  expect(placement).toHaveAttribute('maxLength', '2000')
  expect(screen.getByLabelText('Expected crowd movement notes')).toHaveAttribute('maxLength', '2000')
  fireEvent.change(placement, { target: { value: 'x'.repeat(12) } })
  expect(screen.getByText('12 / 2000')).toBeInTheDocument()
})

test('AC4: the button is disabled while the submission is in flight', async () => {
  let release: () => void = () => {}
  vi.mocked(submitSafetyCheck).mockImplementation(
    () => new Promise((resolve) => { release = () => resolve({ safetyCheck: {}, event: {} } as never) }),
  )
  renderPanel()
  await waitFor(() => expect(submitButton()).toBeEnabled())

  fireEvent.click(submitButton())

  expect(await screen.findByRole('button', { name: 'Submitting…' })).toBeDisabled()
  release()
  await waitFor(() => expect(submitSafetyCheck).toHaveBeenCalledTimes(1))
})

test('AC4: a 409 explains that the event is already waiting, and reloads', async () => {
  vi.mocked(submitSafetyCheck).mockRejectedValue(new SafetySubmitError(
    'This event is already waiting for its safety check. It was submitted on 2026-11-01T02:30:00+00:00.',
    { code: 'SAFETY_CHECK_ALREADY_PENDING' },
  ))
  renderPanel()
  await waitFor(() => expect(submitButton()).toBeEnabled())

  fireEvent.click(submitButton())

  expect(await screen.findByRole('alert')).toHaveTextContent('already waiting for its safety check')
  expect(onSubmitted).toHaveBeenCalled()
})

test('AC2: a 422 at submit time replaces the list with the server\'s', async () => {
  vi.mocked(submitSafetyCheck).mockRejectedValue(new SafetySubmitError(
    "This event can't be submitted for a safety check until it has an approved venue booking and no venue booking or equipment request is still waiting for a decision.",
    { code: 'ARRANGEMENTS_OUTSTANDING', outstanding },
  ))
  renderPanel()
  await waitFor(() => expect(submitButton()).toBeEnabled())

  fireEvent.click(submitButton())

  // An arrangement changed since the readiness read: the list appears and the
  // button closes again.
  expect(await screen.findByText('Booking 12 Nov 2026 09:00–17:00 (120 people)')).toBeInTheDocument()
  await waitFor(() => expect(submitButton()).toBeDisabled())
  expect(onSubmitted).not.toHaveBeenCalled()
})

test('any other submit failure is announced without reloading', async () => {
  vi.mocked(submitSafetyCheck).mockRejectedValue(new Error('Unable to submit for a safety check right now.'))
  renderPanel()
  await waitFor(() => expect(submitButton()).toBeEnabled())

  fireEvent.click(submitButton())

  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to submit for a safety check right now.')
  expect(onSubmitted).not.toHaveBeenCalled()
})

test('a readiness failure hides the form rather than offering a submit', async () => {
  vi.mocked(fetchSafetyReadiness).mockRejectedValue(
    new Error("Unable to check the event's arrangements right now."),
  )
  renderPanel()

  expect(await screen.findByRole('alert')).toHaveTextContent(
    "Unable to check the event's arrangements right now.",
  )
  expect(screen.queryByRole('button', { name: /Submit for safety check/ })).not.toBeInTheDocument()
})

test('readiness is re-read when a venue booking changes', async () => {
  const { rerender } = renderPanel(0)
  await waitFor(() => expect(fetchSafetyReadiness).toHaveBeenCalledTimes(1))

  rerender(<SafetySubmitPanel
    eventId={eventId}
    coordinatorId={coordinatorId}
    refreshKey={1}
    onSubmitted={onSubmitted}
  />)

  await waitFor(() => expect(fetchSafetyReadiness).toHaveBeenCalledTimes(2))
})
