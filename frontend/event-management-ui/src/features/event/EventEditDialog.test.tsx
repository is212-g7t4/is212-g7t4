/**
 * SCRUM-153: the coordinator's edit dialog and its confirm step.
 *
 * AC1 A high-impact change to a 'Confirmed' event is never saved silently:
 *     the coordinator is told what it costs, confirms, and the success line
 *     says why the status changed.
 * AC2 A low-impact edit saves and the event stays 'Confirmed'.
 *
 * The dialog is the explanation, not the enforcement — Event Service's gate
 * decides, and these tests drive it through the two calls that gate implies.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import type { Mock } from 'vitest'
import { EventEditDialog } from './EventEditDialog'
import { EventEditError, SafetyRecheckRequired, updateEventDetails } from './eventDetails'
import { recheckSafety } from '../safety/safetyCheck'
import type { SubmittedEvent } from './submission'

vi.mock('./eventDetails', async () => {
  const actual = await vi.importActual<typeof import('./eventDetails')>('./eventDetails')
  return { ...actual, updateEventDetails: vi.fn() }
})
vi.mock('../safety/safetyCheck', async () => {
  const actual = await vi.importActual<typeof import('../safety/safetyCheck')>('../safety/safetyCheck')
  return { ...actual, recheckSafety: vi.fn() }
})

const eventId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const coordinatorId = '11111111-1111-4111-8111-111111111111'

const confirmedEvent = (status: SubmittedEvent['status'] = 'Confirmed'): SubmittedEvent => ({
  id: eventId,
  status,
  eventName: 'Community Workshop',
  description: 'A workshop for the community.',
  purpose: 'Skills sharing.',
  preferredStartDate: '2026-11-10T09:00',
  preferredEndDate: '2026-11-10T12:00',
  expectedAttendance: '120',
  venueRequirements: 'Hall A',
  equipmentRequirements: 'Two microphones',
  accessibilityNeeds: 'Step-free access',
  registrationNeeds: 'Name and email',
  submittedAt: '2026-10-01T00:00:00+00:00',
  coordinatorId,
  decision: null,
  decisionHistory: [],
  actionDetails: '',
  actionHistory: [],
})

let onSaved: Mock<(event: SubmittedEvent, message: string) => void>
let onCancel: Mock<() => void>

const renderDialog = (status: SubmittedEvent['status'] = 'Confirmed') => render(<EventEditDialog
  event={confirmedEvent(status)}
  coordinatorId={coordinatorId}
  onCancel={onCancel}
  onSaved={onSaved}
/>)

const save = () => fireEvent.click(screen.getByRole('button', { name: 'Save details' }))

beforeEach(() => {
  vi.resetAllMocks()
  onSaved = vi.fn()
  onCancel = vi.fn()
})

// --- The form ----------------------------------------------------------------

test('the fields are prefilled and grouped by whether they affect the safety review', () => {
  renderDialog()

  expect(screen.getByLabelText('Event Name *')).toHaveValue('Community Workshop')
  expect(screen.getByLabelText('Expected Attendance *')).toHaveValue(120)
  expect(screen.getByLabelText('Venue Requirements')).toHaveValue('Hall A')
  expect(screen.getByText('Safety-relevant details')).toBeInTheDocument()
  expect(screen.getByText('Other details')).toBeInTheDocument()
  expect(
    screen.getByText('Changing safety-relevant details withdraws the safety approval.'),
  ).toBeInTheDocument()
})

test('saving is blocked until something actually changes', () => {
  renderDialog()

  expect(screen.getByRole('button', { name: 'Save details' })).toBeDisabled()
  expect(screen.getByText('Change a detail to save.')).toBeInTheDocument()

  fireEvent.change(screen.getByLabelText('Event Name *'), { target: { value: 'Renamed' } })

  expect(screen.getByRole('button', { name: 'Save details' })).toBeEnabled()
})

test('only the fields the coordinator touched are sent', async () => {
  vi.mocked(updateEventDetails).mockResolvedValue(confirmedEvent())
  renderDialog()

  fireEvent.change(screen.getByLabelText('Event Name *'), { target: { value: 'Renamed' } })
  save()

  await waitFor(() => expect(updateEventDetails).toHaveBeenCalledWith(eventId, coordinatorId, {
    eventName: 'Renamed',
  }))
})

test('a locally invalid edit never reaches the service', () => {
  renderDialog()

  fireEvent.change(screen.getByLabelText('Preferred End Date & Time *'), {
    target: { value: '2026-11-10T08:00' },
  })

  expect(
    screen.getByText('Preferred End Date & Time must be after the start.'),
  ).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Save details' })).toBeDisabled()
  expect(updateEventDetails).not.toHaveBeenCalled()
})

test('blanking a required field is refused locally', () => {
  renderDialog()

  fireEvent.change(screen.getByLabelText('Purpose *'), { target: { value: '  ' } })

  expect(screen.getByText('Purpose is required.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Save details' })).toBeDisabled()
})

// --- AC2: a low-impact edit --------------------------------------------------

test('AC2: a low-impact edit saves straight away and says so', async () => {
  const saved = { ...confirmedEvent(), eventName: 'Renamed' }
  vi.mocked(updateEventDetails).mockResolvedValue(saved)
  renderDialog()

  fireEvent.change(screen.getByLabelText('Event Name *'), { target: { value: 'Renamed' } })
  save()

  await waitFor(() => expect(onSaved).toHaveBeenCalledWith(saved, 'Event details saved.'))
  // No confirm step, and nothing asked of the safety workflow.
  expect(recheckSafety).not.toHaveBeenCalled()
  expect(screen.queryByText('Withdraw safety approval?')).not.toBeInTheDocument()
})

// --- AC1: the confirm step ---------------------------------------------------

const recheckRequired = () => new SafetyRecheckRequired(
  'Changing Date/time and Expected attendance will withdraw this event’s safety approval.',
  {
    changedFields: ['preferredStartDate', 'expectedAttendance'],
    highImpactFields: ['preferredStartDate', 'expectedAttendance'],
    labels: ['Date/time', 'Expected attendance'],
  },
)

const changeAttendance = () => fireEvent.change(
  screen.getByLabelText('Expected Attendance *'),
  { target: { value: '400' } },
)

test('AC1: a high-impact change asks for confirmation, naming what changed', async () => {
  vi.mocked(updateEventDetails).mockRejectedValue(recheckRequired())
  renderDialog()

  changeAttendance()
  save()

  await screen.findByText('Withdraw safety approval?')
  const dialog = screen.getByRole('dialog', { name: 'Withdraw safety approval?' })
  expect(dialog).toHaveTextContent('Date/time and Expected attendance')
  expect(dialog).toHaveTextContent('Pending Safety Check')
  expect(dialog).toHaveTextContent('New attendee registrations close until then.')
  // Nothing has been withdrawn yet.
  expect(recheckSafety).not.toHaveBeenCalled()
})

test('AC1: the dialog warns before saving that confirmation will be asked for', () => {
  renderDialog()

  changeAttendance()

  expect(screen.getByRole('status')).toHaveTextContent(
    'Changing: Expected attendance. Saving will ask you to confirm withdrawing the safety approval.',
  )
})

test('"Go back" returns to the form and sends nothing', async () => {
  vi.mocked(updateEventDetails).mockRejectedValue(recheckRequired())
  renderDialog()

  changeAttendance()
  save()
  fireEvent.click(await screen.findByRole('button', { name: 'Go back' }))

  expect(screen.getByLabelText('Expected Attendance *')).toHaveValue(400)
  expect(recheckSafety).not.toHaveBeenCalled()
  expect(onSaved).not.toHaveBeenCalled()
})

test('AC1: confirming withdraws the approval and the message says why', async () => {
  vi.mocked(updateEventDetails).mockRejectedValue(recheckRequired())
  const movedBack = confirmedEvent('Pending Safety Check')
  vi.mocked(recheckSafety).mockResolvedValue({
    event: movedBack,
    safetyCheck: { roundNumber: 3 } as never,
    withdrawnSafetyCheck: { roundNumber: 2 } as never,
    changedFields: ['expectedAttendance'],
    reason: 'Expected attendance changed after safety approval.',
  })
  renderDialog()

  changeAttendance()
  save()
  fireEvent.click(await screen.findByRole('button', { name: 'Save and withdraw approval' }))

  await waitFor(() => expect(recheckSafety).toHaveBeenCalledWith({
    eventId,
    coordinatorId,
    // The same changes the first call was refused for.
    changes: { expectedAttendance: '400' },
  }))
  expect(onSaved).toHaveBeenCalledWith(
    movedBack,
    'Saved. Safety approval withdrawn because Expected attendance changed. '
      + 'The event is back to Pending Safety Check.',
  )
})

test('a re-check that fails returns to the form with the reason shown', async () => {
  vi.mocked(updateEventDetails).mockRejectedValue(recheckRequired())
  vi.mocked(recheckSafety).mockRejectedValue(
    new Error('This safety check round is not the approval this event holds.'),
  )
  renderDialog()

  changeAttendance()
  save()
  fireEvent.click(await screen.findByRole('button', { name: 'Save and withdraw approval' }))

  await screen.findByRole('alert')
  expect(screen.getByRole('alert')).toHaveTextContent(
    'This safety check round is not the approval this event holds.',
  )
  // Back on the form, with the edit still there to retry.
  expect(screen.getByLabelText('Expected Attendance *')).toHaveValue(400)
  expect(onSaved).not.toHaveBeenCalled()
})

// --- Other refusals ----------------------------------------------------------

test('EVENT_UNDER_SAFETY_REVIEW is shown inline, with no confirm step', async () => {
  const message = 'This event is waiting for its Operational Safety Check.'
  vi.mocked(updateEventDetails).mockRejectedValue(
    new EventEditError(message, { code: 'EVENT_UNDER_SAFETY_REVIEW' }),
  )
  renderDialog('Pending Safety Check')

  changeAttendance()
  save()

  await screen.findByRole('alert')
  expect(screen.getByRole('alert')).toHaveTextContent(message)
  expect(screen.queryByText('Withdraw safety approval?')).not.toBeInTheDocument()
  expect(recheckSafety).not.toHaveBeenCalled()
})

test('a pending event says which details it will not accept yet', () => {
  renderDialog('Pending Safety Check')

  expect(screen.getByText(/only the other details/)).toHaveTextContent(
    'only the other details below can be changed until the Safety Officer decides',
  )
})

test('the service\'s own validation errors are listed', async () => {
  vi.mocked(updateEventDetails).mockRejectedValue(new EventEditError(
    'Please correct the event details.',
    { missingFields: ['Purpose'], errors: ['Expected Attendance must be a positive whole number.'] },
  ))
  renderDialog()

  fireEvent.change(screen.getByLabelText('Event Name *'), { target: { value: 'Renamed' } })
  save()

  await screen.findByRole('alert')
  expect(screen.getByText('Purpose')).toBeInTheDocument()
  expect(
    screen.getByText('Expected Attendance must be a positive whole number.'),
  ).toBeInTheDocument()
})

test('any other failure shows its message', async () => {
  vi.mocked(updateEventDetails).mockRejectedValue(new Error('Service unavailable.'))
  renderDialog()

  fireEvent.change(screen.getByLabelText('Event Name *'), { target: { value: 'Renamed' } })
  save()

  await screen.findByRole('alert')
  expect(screen.getByRole('alert')).toHaveTextContent('Service unavailable.')
})

test('a non-Error failure still shows something readable', async () => {
  vi.mocked(updateEventDetails).mockRejectedValue('kaboom')
  renderDialog()

  fireEvent.change(screen.getByLabelText('Event Name *'), { target: { value: 'Renamed' } })
  save()

  await screen.findByRole('alert')
  expect(screen.getByRole('alert')).toHaveTextContent('Unable to save these event details.')
})

test('Cancel closes the dialog without saving', () => {
  renderDialog()

  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

  expect(onCancel).toHaveBeenCalled()
  expect(updateEventDetails).not.toHaveBeenCalled()
})
