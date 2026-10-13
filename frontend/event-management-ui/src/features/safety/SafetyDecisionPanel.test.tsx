/**
 * SCRUM-150: the Safety Officer's Approve panel.
 *
 * AC1/AC2 approving sends remarks, tells the officer, and reloads the event.
 * AC3 the confirm step must be accepted before anything is sent.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import type { Mock } from 'vitest'
import { SafetySubmitError, approveSafetyCheck } from './safetyCheck'
import { SafetyDecisionPanel } from './SafetyDecisionPanel'

vi.mock('./safetyCheck', async () => {
  const actual = await vi.importActual<typeof import('./safetyCheck')>('./safetyCheck')
  return { ...actual, approveSafetyCheck: vi.fn() }
})

const eventId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const safetyOfficerId = '33333333-3333-4333-8333-333333333333'

let onApproved: Mock<() => void>

const renderPanel = () => render(<SafetyDecisionPanel
  eventId={eventId}
  safetyOfficerId={safetyOfficerId}
  onApproved={onApproved}
/>)

beforeEach(() => {
  vi.resetAllMocks()
  onApproved = vi.fn<() => void>()
})

test('clicking Approve shows a confirm step before anything is sent', () => {
  renderPanel()

  fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

  expect(screen.getByText(/Approve this event's safety arrangements\? It will move to Confirmed\./)).toBeInTheDocument()
  expect(approveSafetyCheck).not.toHaveBeenCalled()
})

test('cancelling the confirm step sends nothing', () => {
  renderPanel()
  fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

  expect(screen.queryByText(/It will move to Confirmed/)).not.toBeInTheDocument()
  expect(approveSafetyCheck).not.toHaveBeenCalled()
})

test('AC1, AC2: confirming sends remarks and reloads the page', async () => {
  vi.mocked(approveSafetyCheck).mockResolvedValue({
    safetyCheck: { roundNumber: 1, status: 'Safety Approved' },
    event: { status: 'Confirmed' },
  } as never)
  renderPanel()

  fireEvent.change(screen.getByLabelText('Remarks'), { target: { value: 'Looks safe.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
  fireEvent.click(screen.getByRole('button', { name: 'Yes, approve' }))

  expect(await screen.findByText('Approved. The event has moved to Confirmed.')).toBeInTheDocument()
  expect(approveSafetyCheck).toHaveBeenCalledWith({
    eventId,
    safetyOfficerId,
    remarks: 'Looks safe.',
  })
  expect(onApproved).toHaveBeenCalled()
})

test('remarks are optional and blank ones are not sent', async () => {
  vi.mocked(approveSafetyCheck).mockResolvedValue({ safetyCheck: {}, event: {} } as never)
  renderPanel()

  fireEvent.change(screen.getByLabelText('Remarks'), { target: { value: '   ' } })
  fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
  fireEvent.click(screen.getByRole('button', { name: 'Yes, approve' }))

  await waitFor(() => expect(approveSafetyCheck).toHaveBeenCalledWith({
    eventId,
    safetyOfficerId,
    remarks: undefined,
  }))
})

test('remarks are capped at 2000 characters, with a running count', () => {
  renderPanel()
  const textarea = screen.getByLabelText('Remarks')

  expect(textarea).toHaveAttribute('maxLength', '2000')
  fireEvent.change(textarea, { target: { value: 'x'.repeat(12) } })
  expect(screen.getByText('12 / 2000')).toBeInTheDocument()
})

test('the confirm button is disabled while the approval is in flight', async () => {
  let release: () => void = () => {}
  vi.mocked(approveSafetyCheck).mockImplementation(
    () => new Promise((resolve) => { release = () => resolve({ safetyCheck: {}, event: {} } as never) }),
  )
  renderPanel()
  fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

  fireEvent.click(screen.getByRole('button', { name: 'Yes, approve' }))

  expect(await screen.findByRole('button', { name: 'Approving…' })).toBeDisabled()
  release()
  await waitFor(() => expect(approveSafetyCheck).toHaveBeenCalledTimes(1))
})

test('AC3: a 409 shows the API message and does not reload', async () => {
  vi.mocked(approveSafetyCheck).mockRejectedValue(new SafetySubmitError(
    "Only an event 'Pending Safety Check' can be approved (current status: 'Approved').",
    { code: 'EVENT_NOT_PENDING_SAFETY_CHECK' },
  ))
  renderPanel()
  fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

  fireEvent.click(screen.getByRole('button', { name: 'Yes, approve' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(
    "Only an event 'Pending Safety Check' can be approved",
  )
  expect(onApproved).not.toHaveBeenCalled()
})

test('any other approval failure is announced', async () => {
  vi.mocked(approveSafetyCheck).mockRejectedValue(new Error('Unable to approve this safety check right now.'))
  renderPanel()
  fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

  fireEvent.click(screen.getByRole('button', { name: 'Yes, approve' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to approve this safety check right now.')
  expect(onApproved).not.toHaveBeenCalled()
})
