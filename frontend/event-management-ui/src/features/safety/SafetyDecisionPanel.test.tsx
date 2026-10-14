/**
 * SCRUM-150/151: the Safety Officer's three decisions — Approve, Request
 * changes, Reject.
 *
 * AC1 request changes needs at least one area with its own change text.
 * AC2/AC6 approving and requesting changes send remarks/reason, tell the
 *     officer, and reload the event.
 * AC3 reject needs a reason and an explicit confirmation before anything sends.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import type { Mock } from 'vitest'
import {
  SafetySubmitError,
  approveSafetyCheck,
  rejectSafetyCheck,
  requestSafetyChanges,
} from './safetyCheck'
import { SafetyDecisionPanel } from './SafetyDecisionPanel'

vi.mock('./safetyCheck', async () => {
  const actual = await vi.importActual<typeof import('./safetyCheck')>('./safetyCheck')
  return {
    ...actual,
    approveSafetyCheck: vi.fn(),
    requestSafetyChanges: vi.fn(),
    rejectSafetyCheck: vi.fn(),
  }
})

const eventId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const safetyOfficerId = '33333333-3333-4333-8333-333333333333'

let onDecided: Mock<() => void>

const renderPanel = () => render(<SafetyDecisionPanel
  eventId={eventId}
  eventName="Community Workshop"
  safetyOfficerId={safetyOfficerId}
  onDecided={onDecided}
/>)

beforeEach(() => {
  vi.resetAllMocks()
  onDecided = vi.fn<() => void>()
})

// --- Approve -------------------------------------------------------------

test('Approve is the default view, alongside Request changes and Reject', () => {
  renderPanel()

  expect(screen.getByLabelText('Remarks')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Request changes' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Reject' })).toBeInTheDocument()
})

test('clicking Approve shows a confirm step before anything is sent', () => {
  renderPanel()

  fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

  expect(screen.getByText(/Approve this event's safety arrangements\? It will move to Confirmed\./)).toBeInTheDocument()
  expect(approveSafetyCheck).not.toHaveBeenCalled()
})

test('cancelling the approve confirm step sends nothing', () => {
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
  expect(onDecided).toHaveBeenCalled()
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

test('AC3 (approve): a 409 shows the API message and does not reload', async () => {
  vi.mocked(approveSafetyCheck).mockRejectedValue(new SafetySubmitError(
    "Only an event 'Pending Safety Check' can be decided (current status: 'Approved').",
    { code: 'EVENT_NOT_PENDING_SAFETY_CHECK' },
  ))
  renderPanel()
  fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

  fireEvent.click(screen.getByRole('button', { name: 'Yes, approve' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(
    "Only an event 'Pending Safety Check' can be decided",
  )
  expect(onDecided).not.toHaveBeenCalled()
})

// --- Request changes -------------------------------------------------------

test('AC1: request changes is disabled until an area, its change text and a reason are filled', async () => {
  renderPanel()
  fireEvent.click(screen.getByRole('button', { name: 'Request changes' }))

  expect(screen.getByRole('button', { name: 'Request changes' })).toBeDisabled()

  fireEvent.click(screen.getByRole('checkbox', { name: /Venue arrangement/ }))
  expect(screen.getByRole('button', { name: 'Request changes' })).toBeDisabled()

  fireEvent.change(screen.getByLabelText('Change needed for Venue arrangement'), {
    target: { value: 'Move the stage.' },
  })
  expect(screen.getByRole('button', { name: 'Request changes' })).toBeDisabled()

  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Needs another look.' } })
  expect(screen.getByRole('button', { name: 'Request changes' })).not.toBeDisabled()
})

test('AC1: sends the expected flags and reason', async () => {
  vi.mocked(requestSafetyChanges).mockResolvedValue({
    safetyCheck: { status: 'Changes Requested' },
    event: { status: 'Safety Changes Requested' },
  } as never)
  renderPanel()
  fireEvent.click(screen.getByRole('button', { name: 'Request changes' }))

  fireEvent.click(screen.getByRole('checkbox', { name: /Venue arrangement/ }))
  fireEvent.change(screen.getByLabelText('Change needed for Venue arrangement'), {
    target: { value: 'Move the stage.' },
  })
  fireEvent.click(screen.getByRole('checkbox', { name: /Event details/ }))
  fireEvent.change(screen.getByLabelText('Change needed for Event details'), {
    target: { value: 'Fix the start time.' },
  })
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Needs another look.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Request changes' }))

  await waitFor(() => expect(requestSafetyChanges).toHaveBeenCalledWith({
    eventId,
    safetyOfficerId,
    reason: 'Needs another look.',
    flags: [
      { area: 'venue arrangement', changeRequired: 'Move the stage.' },
      { area: 'event details', changeRequired: 'Fix the start time.' },
    ],
  }))
  expect(await screen.findByText('Changes requested. The event has moved to Safety Changes Requested.')).toBeInTheDocument()
  expect(onDecided).toHaveBeenCalled()
})

test('cancelling request changes sends nothing', () => {
  renderPanel()
  fireEvent.click(screen.getByRole('button', { name: 'Request changes' }))

  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

  expect(screen.queryByLabelText('Reason')).not.toBeInTheDocument()
  expect(requestSafetyChanges).not.toHaveBeenCalled()
})

test('request changes: an API error is shown', async () => {
  vi.mocked(requestSafetyChanges).mockRejectedValue(new Error('Unable to request changes to this safety check right now.'))
  renderPanel()
  fireEvent.click(screen.getByRole('button', { name: 'Request changes' }))
  fireEvent.click(screen.getByRole('checkbox', { name: /Venue arrangement/ }))
  fireEvent.change(screen.getByLabelText('Change needed for Venue arrangement'), {
    target: { value: 'Move the stage.' },
  })
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Needs another look.' } })

  fireEvent.click(screen.getByRole('button', { name: 'Request changes' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Unable to request changes to this safety check right now.',
  )
  expect(onDecided).not.toHaveBeenCalled()
})

// --- Reject ------------------------------------------------------------------

const openRejectDialog = () => {
  fireEvent.click(screen.getByRole('button', { name: 'Reject' }))
  return screen.getByRole('dialog', { name: 'Reject and cancel this event?' })
}

test('AC3: Reject opens a dialog that names the consequence, before anything is sent', () => {
  renderPanel()

  const dialog = openRejectDialog()

  expect(dialog).toHaveTextContent('Community Workshop')
  expect(dialog).toHaveTextContent(/venue\s+bookings are released/)
  expect(dialog).toHaveTextContent(/can't be undone/)
  expect(rejectSafetyCheck).not.toHaveBeenCalled()
})

test('AC3: the confirm button stays disabled until a reason is given', () => {
  renderPanel()
  const dialog = openRejectDialog()
  const confirm = within(dialog).getByRole('button', { name: 'Confirm rejection' })

  expect(confirm).toBeDisabled()

  fireEvent.change(within(dialog).getByLabelText(/Reason for rejection/), {
    target: { value: 'Unsafe egress plan.' },
  })

  expect(confirm).not.toBeDisabled()
})

test('AC3, AC5: confirming sends the reason and shows the release message', async () => {
  vi.mocked(rejectSafetyCheck).mockResolvedValue({
    safetyCheck: { status: 'Safety Rejected' },
    event: { status: 'Cancelled' },
    release: { venueBookingsReleased: ['b1'], venueBookingsNotReleased: [], equipment: 'Released.' },
  } as never)
  renderPanel()
  const dialog = openRejectDialog()
  fireEvent.change(within(dialog).getByLabelText(/Reason for rejection/), {
    target: { value: 'Unsafe egress plan.' },
  })

  fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm rejection' }))

  expect(await screen.findByText(
    'Rejected. The event is cancelled and its venue bookings were released.',
  )).toBeInTheDocument()
  expect(rejectSafetyCheck).toHaveBeenCalledWith({
    eventId,
    safetyOfficerId,
    reason: 'Unsafe egress plan.',
  })
  expect(onDecided).toHaveBeenCalled()
})

test('a release that could not clear every booking is flagged in the message', async () => {
  vi.mocked(rejectSafetyCheck).mockResolvedValue({
    safetyCheck: { status: 'Safety Rejected' },
    event: { status: 'Cancelled' },
    release: { venueBookingsReleased: [], venueBookingsNotReleased: ['b1'], equipment: 'Released.' },
  } as never)
  renderPanel()
  const dialog = openRejectDialog()
  fireEvent.change(within(dialog).getByLabelText(/Reason for rejection/), {
    target: { value: 'Unsafe egress plan.' },
  })

  fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm rejection' }))

  expect(await screen.findByText(/must be cancelled by Venue Staff/)).toBeInTheDocument()
})

test('the confirm button reports progress while the rejection is in flight', async () => {
  let release: () => void = () => {}
  vi.mocked(rejectSafetyCheck).mockImplementation(
    () => new Promise((resolve) => {
      release = () => resolve({
        safetyCheck: {}, event: {},
        release: { venueBookingsReleased: [], venueBookingsNotReleased: [], equipment: '' },
      } as never)
    }),
  )
  renderPanel()
  const dialog = openRejectDialog()
  fireEvent.change(within(dialog).getByLabelText(/Reason for rejection/), {
    target: { value: 'Unsafe egress plan.' },
  })

  fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm rejection' }))

  expect(await screen.findByRole('button', { name: 'Rejecting…' })).toBeDisabled()
  release()
  await waitFor(() => expect(rejectSafetyCheck).toHaveBeenCalledTimes(1))
})

test('cancelling the reject dialog sends nothing and returns to the decision', () => {
  renderPanel()
  const dialog = openRejectDialog()

  fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))

  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Reject' })).toBeInTheDocument()
  expect(rejectSafetyCheck).not.toHaveBeenCalled()
})

test('reject: an API refusal is shown as an error', async () => {
  vi.mocked(rejectSafetyCheck).mockRejectedValue(new SafetySubmitError(
    'This safety check has already been decided.',
    { code: 'SAFETY_CHECK_ALREADY_DECIDED' },
  ))
  renderPanel()
  const dialog = openRejectDialog()
  fireEvent.change(within(dialog).getByLabelText(/Reason for rejection/), {
    target: { value: 'Unsafe egress plan.' },
  })

  fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm rejection' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('This safety check has already been decided.')
  expect(onDecided).not.toHaveBeenCalled()
})
