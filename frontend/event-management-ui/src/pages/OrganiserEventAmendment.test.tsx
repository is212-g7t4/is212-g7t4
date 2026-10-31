import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { EventDetailPage } from './EventDetailPage'
import { eventApi, SubmissionError } from '../features/event/submission'
import type { SubmittedEvent } from '../features/event/submission'

// SCRUM-16 AC3/AC4: the organiser edits only the flagged fields and resubmits.

vi.mock('../features/event/submission', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../features/event/submission')>()),
  eventApi: vi.fn(),
}))
vi.mock('../features/registration/registrations', () => ({
  canListEventRegistrations: (status: string) => status === 'Approved' || status === 'Confirmed',
  fetchRegistrations: vi.fn(),
}))

const ORGANISER_ID = '33333333-3333-4333-8333-333333333333'
const COORDINATOR_ID = '11111111-1111-4111-8111-111111111111'
const amendment = {
  id: 'amendment-1',
  fields: ['preferredStartDate', 'preferredEndDate', 'expectedAttendance'],
  reason: 'The hall is booked that week and 300 exceeds every room.',
  requestedBy: COORDINATOR_ID,
  requestedAt: '2026-10-20T01:00:00+00:00',
  resubmittedBy: null,
  resubmittedAt: null,
  changes: null,
  note: null,
}
const event: SubmittedEvent = {
  id: 'submitted-1',
  eventName: 'Community Workshop',
  description: 'A practical workshop',
  purpose: 'Learning',
  preferredStartDate: '2030-03-01T09:00:00',
  preferredEndDate: '2030-03-01T17:00:00',
  expectedAttendance: '300',
  venueRequirements: 'Main hall',
  accessibilityNeeds: '',
  equipmentRequirements: '',
  registrationNeeds: '',
  status: 'Amendment Requested',
  submittedAt: '2026-10-01T08:00:00+00:00',
  coordinatorId: COORDINATOR_ID,
  organiserId: ORGANISER_ID,
  decision: null,
  decisionHistory: [],
  actionDetails: '',
  actionHistory: [],
  amendmentHistory: [amendment],
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(eventApi).mockResolvedValue(event)
})

function renderPage() {
  render(<EventDetailPage eventId={event.id} role="Event Organiser" currentCoordinatorId={ORGANISER_ID} resolveUserName={(id) => id === COORDINATOR_ID ? 'Alicia Tan' : null} backLabel="My events" onBack={vi.fn()} />)
  return screen.findByRole('heading', { name: 'Amendment required' })
}

const resubmit = () => screen.getByRole('button', { name: 'Resubmit' })

test('AC3: only the flagged fields get inputs, prefilled with the current values', async () => {
  await renderPage()

  // In the form and in the history below it.
  expect(screen.getAllByText(amendment.reason)).toHaveLength(2)
  expect(screen.getAllByText(/Requested by Alicia Tan on/)[0]).toBeInTheDocument()
  expect(screen.getByLabelText('Preferred Start Date & Time')).toHaveValue('2030-03-01T09:00')
  expect(screen.getByLabelText('Preferred End Date & Time')).toHaveValue('2030-03-01T17:00')
  expect(screen.getByLabelText('Expected Attendance')).toHaveValue(300)
  for (const locked of ['Event Name', 'Venue Requirements', 'Description', 'Purpose']) {
    expect(screen.queryByLabelText(locked)).not.toBeInTheDocument()
  }
  // Nor is a SCRUM-42 proposal offered mid-amendment.
  expect(screen.queryByRole('button', { name: 'Request changes' })).not.toBeInTheDocument()
})

test('AC3: Resubmit stays disabled until a flagged value changes', async () => {
  await renderPage()
  expect(resubmit()).toBeDisabled()
  expect(screen.getByRole('note')).toHaveTextContent('Change at least one flagged field before resubmitting.')

  fireEvent.change(screen.getByLabelText('Expected Attendance'), { target: { value: '120' } })
  expect(resubmit()).toBeEnabled()

  fireEvent.change(screen.getByLabelText('Expected Attendance'), { target: { value: '300' } })
  expect(resubmit()).toBeDisabled()
})

test('AC4: only the changed flagged fields are sent, and the event returns to Submitted', async () => {
  vi.mocked(eventApi)
    .mockResolvedValueOnce(event)
    .mockResolvedValueOnce({
      ...event,
      status: 'Submitted',
      expectedAttendance: '120',
      amendmentHistory: [{
        ...amendment,
        resubmittedBy: ORGANISER_ID,
        resubmittedAt: '2026-10-21T02:00:00+00:00',
        changes: { expectedAttendance: { from: '300', to: '120' } },
        note: 'Trimmed the guest list.',
      }],
    })
  await renderPage()

  fireEvent.change(screen.getByLabelText('Expected Attendance'), { target: { value: '120' } })
  fireEvent.change(screen.getByLabelText(/Note to coordinator/), { target: { value: '  Trimmed the guest list.  ' } })
  fireEvent.click(resubmit())

  await waitFor(() => expect(eventApi).toHaveBeenLastCalledWith(
    '/events/submitted-1/amendment-response',
    { organiserId: ORGANISER_ID, changes: { expectedAttendance: '120' }, note: 'Trimmed the guest list.' },
    'PATCH',
  ))
  expect(await screen.findByText('Your amended request was resubmitted. It is back with the same Event Coordinator.')).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Amendment required' })).not.toBeInTheDocument()
  expect(screen.getByText('Submitted', { selector: '.status-badge' })).toBeInTheDocument()
  expect(screen.getByText('Expected Attendance: 300 → 120')).toBeInTheDocument()
})

test('AC4: without a note, none is sent', async () => {
  vi.mocked(eventApi).mockResolvedValueOnce(event).mockResolvedValueOnce({ ...event, status: 'Submitted' })
  await renderPage()

  fireEvent.change(screen.getByLabelText('Preferred End Date & Time'), { target: { value: '2030-03-01T15:00' } })
  fireEvent.click(resubmit())

  await waitFor(() => expect(eventApi).toHaveBeenLastCalledWith(
    '/events/submitted-1/amendment-response',
    { organiserId: ORGANISER_ID, changes: { preferredEndDate: '2030-03-01T15:00' } },
    'PATCH',
  ))
})

test('AC3: the server\'s validation errors are shown inline', async () => {
  vi.mocked(eventApi)
    .mockResolvedValueOnce(event)
    .mockRejectedValueOnce(new SubmissionError(
      'Please correct the event details.', ['Expected Attendance'], ['Preferred End Date & Time must be after the start.'],
    ))
  await renderPage()

  fireEvent.change(screen.getByLabelText('Preferred End Date & Time'), { target: { value: '2030-03-01T08:00' } })
  fireEvent.click(resubmit())

  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent('Please correct the event details.')
  expect(alert).toHaveTextContent('Expected Attendance is required.')
  expect(alert).toHaveTextContent('Preferred End Date & Time must be after the start.')

  // Editing again clears the error.
  fireEvent.change(screen.getByLabelText('Preferred End Date & Time'), { target: { value: '2030-03-01T16:00' } })
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('AC3: a locked-field refusal shows its message; an unexpected failure a generic one', async () => {
  vi.mocked(eventApi)
    .mockResolvedValueOnce(event)
    .mockRejectedValueOnce(new SubmissionError('Only the fields the Event Coordinator flagged can be changed.', [], [], 'AMENDMENT_FIELD_LOCKED'))
    .mockRejectedValueOnce(new Error('boom'))
  await renderPage()

  fireEvent.change(screen.getByLabelText('Expected Attendance'), { target: { value: '120' } })
  fireEvent.click(resubmit())
  expect(await screen.findByRole('alert')).toHaveTextContent('Only the fields the Event Coordinator flagged can be changed.')
  expect(screen.queryByRole('listitem')).not.toBeInTheDocument()

  fireEvent.click(resubmit())
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to resubmit your amended request.')
})

test('text fields get a textarea', async () => {
  vi.mocked(eventApi).mockResolvedValue({
    ...event,
    amendmentHistory: [{ ...amendment, fields: ['description'] }],
  })
  await renderPage()
  expect(screen.getByLabelText('Description').tagName).toBe('TEXTAREA')
  fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'A two-part workshop' } })
  expect(resubmit()).toBeEnabled()
})

test('no form is shown when the status is stale and no round is open', async () => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, amendmentHistory: [] })
  render(<EventDetailPage eventId={event.id} role="Event Organiser" currentCoordinatorId={ORGANISER_ID} backLabel="My events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })
  expect(screen.queryByRole('heading', { name: 'Amendment required' })).not.toBeInTheDocument()
})
