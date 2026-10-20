import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { assignmentApi, SubmissionError } from './submission'
import type { Coordinator, EventStatus, SubmittedEvent } from './submission'
import { ReassignCoordinatorPanel } from './ReassignCoordinatorPanel'
import { NO_CHANGE_MESSAGE, canReassign } from './eventStatus'

vi.mock('./submission', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./submission')>()),
  assignmentApi: vi.fn(),
}))

const leadId = '33333333-3333-4333-8333-333333333333'
const currentId = '11111111-1111-4111-8111-111111111111'
const newId = '22222222-2222-4222-8222-222222222222'
const coordinators: Coordinator[] = [
  { user_id: currentId, username: 'Alicia Tan', email: 'alicia@example.com', role: 'Event Coordinator', organization: '', contact_details: '' },
  { user_id: newId, username: 'Marcus Lim', email: 'marcus@example.com', role: 'Event Coordinator', organization: '', contact_details: '' },
]
const event: SubmittedEvent = {
  id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', eventName: 'Community Workshop', description: '', purpose: '',
  preferredStartDate: '2026-10-10T09:00:00+08:00', preferredEndDate: '2026-10-10T12:00:00+08:00', expectedAttendance: '30',
  venueRequirements: '', accessibilityNeeds: '', equipmentRequirements: '', registrationNeeds: '',
  status: 'Approved', submittedAt: '2026-10-01T08:00:00+08:00', coordinatorId: currentId,
  decision: null, decisionHistory: [], actionDetails: '', actionHistory: [],
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(assignmentApi).mockResolvedValue({ coordinators })
})

async function openPicker() {
  fireEvent.click(screen.getByRole('button', { name: 'Reassign Coordinator' }))
  await screen.findByRole('option', { name: /Marcus Lim/ })
}

test.each<[EventStatus, boolean]>([
  ['Under Review', true], ['Approved', true], ['Pending Safety Check', true],
  ['Confirmed', true], ['Safety Changes Requested', true],
  ['Rejected', false], ['Cancelled', false], ['Clarification Requested', false],
])('canReassign: %s → %s', (status, expected) => {
  expect(canReassign({ ...event, status })).toBe(expected)
})

test('canReassign is false for an event with no coordinator yet (that is assignment)', () => {
  expect(canReassign({ ...event, status: 'Submitted', coordinatorId: null })).toBe(false)
})

test('choosing the current coordinator is rejected as no change, without calling the service', async () => {
  const onReassigned = vi.fn()
  render(<ReassignCoordinatorPanel event={event} leadId={leadId} onReassigned={onReassigned} />)
  await openPicker()

  expect(screen.getByRole('option', { name: /Alicia Tan.*\(current\)/ })).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('New coordinator'), { target: { value: currentId } })
  fireEvent.click(screen.getByRole('button', { name: 'Confirm Reassignment' }))

  expect(screen.getByRole('alert')).toHaveTextContent(NO_CHANGE_MESSAGE)
  expect(assignmentApi).toHaveBeenCalledTimes(1) // only the coordinator list
  expect(onReassigned).not.toHaveBeenCalled()
})

test('confirming without choosing asks for a coordinator', async () => {
  render(<ReassignCoordinatorPanel event={event} leadId={leadId} onReassigned={vi.fn()} />)
  await openPicker()
  fireEvent.click(screen.getByRole('button', { name: 'Confirm Reassignment' }))
  expect(screen.getByRole('alert')).toHaveTextContent('Choose a coordinator before confirming.')
})

test('the Lead reassigns to a different coordinator', async () => {
  const updated = { ...event, coordinatorId: newId, previousCoordinatorId: currentId, assignedBy: leadId, assignedAt: '2026-10-16T13:05:00+00:00' }
  vi.mocked(assignmentApi).mockResolvedValueOnce({ coordinators }).mockResolvedValueOnce(updated)
  const onReassigned = vi.fn()
  render(<ReassignCoordinatorPanel event={event} leadId={leadId} onReassigned={onReassigned} />)
  await openPicker()

  fireEvent.change(screen.getByLabelText('New coordinator'), { target: { value: newId } })
  fireEvent.click(screen.getByRole('button', { name: 'Confirm Reassignment' }))

  await waitFor(() => expect(onReassigned).toHaveBeenCalledWith(updated))
  expect(assignmentApi).toHaveBeenLastCalledWith(`/events/${event.id}/assign-coordinator/${newId}`, 'POST', { actingUserId: leadId })
  expect(screen.getByRole('status')).toHaveTextContent('Community Workshop was reassigned to Marcus Lim.')
})

test('a refusal from the service is shown to the Lead', async () => {
  vi.mocked(assignmentApi).mockResolvedValueOnce({ coordinators }).mockRejectedValueOnce(new SubmissionError("A Cancelled event can't be reassigned."))
  const onReassigned = vi.fn()
  render(<ReassignCoordinatorPanel event={event} leadId={leadId} onReassigned={onReassigned} />)
  await openPicker()

  fireEvent.change(screen.getByLabelText('New coordinator'), { target: { value: newId } })
  fireEvent.click(screen.getByRole('button', { name: 'Confirm Reassignment' }))

  expect(await screen.findByRole('alert')).toHaveTextContent("A Cancelled event can't be reassigned.")
  expect(onReassigned).not.toHaveBeenCalled()
})

test('a failure loading coordinators is shown', async () => {
  vi.mocked(assignmentApi).mockRejectedValueOnce(new Error('Coordinator service down'))
  render(<ReassignCoordinatorPanel event={event} leadId={leadId} onReassigned={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Reassign Coordinator' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Coordinator service down')
})

test('cancel closes the picker', async () => {
  render(<ReassignCoordinatorPanel event={event} leadId={leadId} onReassigned={vi.fn()} />)
  await openPicker()
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByLabelText('New coordinator')).not.toBeInTheDocument()
})

test('uses the coordinator list the page already has instead of fetching it', async () => {
  render(<ReassignCoordinatorPanel event={event} leadId={leadId} coordinators={coordinators} onReassigned={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Reassign Coordinator' }))

  expect(screen.getByRole('option', { name: /Marcus Lim/ })).toBeInTheDocument()
  expect(assignmentApi).not.toHaveBeenCalled()
})
