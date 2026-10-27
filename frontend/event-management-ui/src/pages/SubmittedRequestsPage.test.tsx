import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { assignmentApi, eventApi } from '../features/event/submission'
import type { Coordinator, SubmittedEvent } from '../features/event/submission'
import { SubmittedRequestsPage } from './SubmittedRequestsPage'

vi.mock('../features/event/submission', () => ({ eventApi: vi.fn(), assignmentApi: vi.fn() }))

const leadId = '33333333-3333-4333-8333-333333333333'
const coordinatorId = '11111111-1111-4111-8111-111111111111'
const coordinators: Coordinator[] = [
  { user_id: leadId, username: 'Grace Lee', email: 'grace@example.com', role: 'Event Coordinator Lead', organization: '', contact_details: '' },
  { user_id: coordinatorId, username: 'Alicia Tan', email: 'alicia@example.com', role: 'Event Coordinator', organization: '', contact_details: '' },
]
const event: SubmittedEvent = {
  id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  eventName: 'Community Workshop',
  description: 'A practical workshop',
  purpose: 'Learning',
  preferredStartDate: '2026-10-10T09:00:00+08:00',
  preferredEndDate: '2026-10-10T12:00:00+08:00',
  expectedAttendance: '30',
  venueRequirements: '',
  accessibilityNeeds: '',
  equipmentRequirements: '',
  registrationNeeds: '',
  status: 'Under Review',
  submittedAt: '2026-10-01T08:00:00+08:00',
  coordinatorId,
  assignedBy: leadId,
  assignedAt: '2026-10-01T09:30:00+00:00',
  decision: null,
  decisionHistory: [],
  actionDetails: '',
  actionHistory: [],
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(eventApi).mockResolvedValue({ events: [event] })
  vi.mocked(assignmentApi).mockResolvedValue({ coordinators })
})

// Assign coordinator: an Event Coordinator who is not the Lead must not see
// any 'Reassign' option, even on an event assigned to them.
test('an Event Coordinator who is not the Lead sees no Reassign option', async () => {
  render(<SubmittedRequestsPage role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" onViewDetails={vi.fn()} />)

  expect(await screen.findByRole('heading', { name: 'Community Workshop' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /reassign/i })).not.toBeInTheDocument()
  expect(screen.queryByText(/reassign/i)).not.toBeInTheDocument()
})

test('the Lead sees the Reassign option', async () => {
  render(<SubmittedRequestsPage role="Event Coordinator Lead" currentCoordinatorId={leadId} currentCoordinatorName="Grace Lee" onViewDetails={vi.fn()} />)

  expect(await screen.findByRole('button', { name: 'Reassign Coordinator' })).toBeInTheDocument()
})

test('assigned coordinator must enter a question before requesting clarification', async () => {
  vi.mocked(eventApi)
    .mockResolvedValueOnce({ events: [event] })
    .mockResolvedValueOnce({ ...event, status: 'Clarification Requested' })
  render(<SubmittedRequestsPage role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" onViewDetails={vi.fn()} />)

  fireEvent.click(await screen.findByRole('button', { name: 'Request clarification' }))
  const submit = screen.getByRole('button', { name: 'Send request' })
  expect(submit).toBeDisabled()
  fireEvent.change(screen.getByLabelText(/Question or message/), { target: { value: 'Who is the intended audience?' } })
  fireEvent.click(submit)

  await waitFor(() => expect(eventApi).toHaveBeenLastCalledWith(
    `/events/${event.id}/clarification-request`,
    { coordinatorId, message: 'Who is the intended audience?' },
    'PATCH',
  ))
  expect(await screen.findByText(/question was sent/i)).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Community Workshop' })).not.toBeInTheDocument()
})

// SCRUM-16 AC1/AC2: the assigned coordinator flags fields and a reason; the
// request leaves the list and the toast confirms it.
test('assigned coordinator flags fields and a reason to request an amendment', async () => {
  vi.mocked(eventApi)
    .mockResolvedValueOnce({ events: [event] })
    .mockResolvedValueOnce({ ...event, status: 'Amendment Requested' })
  render(<SubmittedRequestsPage role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" onViewDetails={vi.fn()} />)

  fireEvent.click(await screen.findByRole('button', { name: 'Request amendment' }))
  expect(screen.getByRole('dialog', { name: 'Request amendment' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('checkbox', { name: 'Date/time' }))
  fireEvent.click(screen.getByRole('checkbox', { name: 'Expected attendance' }))
  fireEvent.change(screen.getByLabelText(/Reason or details/), { target: { value: '  The hall is booked that week.  ' } })
  fireEvent.click(screen.getByRole('button', { name: 'Send amendment request' }))

  await waitFor(() => expect(eventApi).toHaveBeenLastCalledWith(
    `/events/${event.id}/amendment-request`,
    { coordinatorId, fields: ['preferredStartDate', 'preferredEndDate', 'expectedAttendance'], reason: 'The hall is booked that week.' },
    'PATCH',
  ))
  expect(await screen.findByText('Amendment Requested')).toBeInTheDocument()
  expect(screen.getByText(/sent back to its organiser/i)).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Community Workshop' })).not.toBeInTheDocument()
})

test('a refused amendment request keeps the dialog open with the API message', async () => {
  vi.mocked(eventApi)
    .mockResolvedValueOnce({ events: [event] })
    .mockRejectedValueOnce(new Error('Amendment can only be requested for a submitted or under-review event request.'))
  render(<SubmittedRequestsPage role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" onViewDetails={vi.fn()} />)

  fireEvent.click(await screen.findByRole('button', { name: 'Request amendment' }))
  fireEvent.click(screen.getByRole('checkbox', { name: 'Venue requirements' }))
  fireEvent.change(screen.getByLabelText(/Reason or details/), { target: { value: 'Pick a larger room.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Send amendment request' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Amendment can only be requested')
  expect(screen.getByRole('dialog', { name: 'Request amendment' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('dialog', { name: 'Request amendment' })).not.toBeInTheDocument()
})

test('a non-Error amendment failure shows a generic message', async () => {
  vi.mocked(eventApi)
    .mockResolvedValueOnce({ events: [event] })
    .mockRejectedValueOnce('network down')
  render(<SubmittedRequestsPage role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" onViewDetails={vi.fn()} />)

  fireEvent.click(await screen.findByRole('button', { name: 'Request amendment' }))
  fireEvent.click(screen.getByRole('checkbox', { name: 'Purpose' }))
  fireEvent.change(screen.getByLabelText(/Reason or details/), { target: { value: 'Be specific.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Send amendment request' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to request an amendment.')
})
