import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { assignmentApi } from '../features/event/submission'
import type { Coordinator, SubmittedEvent } from '../features/event/submission'
import { UnassignedQueuePage } from './UnassignedQueuePage'

vi.mock('../features/event/submission', () => ({ assignmentApi: vi.fn() }))

const leadId = '33333333-3333-4333-8333-333333333333'
const coordinatorId = '11111111-1111-4111-8111-111111111111'
const otherCoordinatorId = '22222222-2222-4222-8222-222222222222'
const organiserId = '44444444-4444-4444-8444-444444444444'
const coordinators: Coordinator[] = [
  { user_id: coordinatorId, username: 'Alicia Tan', email: 'alicia@example.com', role: 'Event Coordinator', organization: '', contact_details: '' },
  { user_id: otherCoordinatorId, username: 'Marcus Lim', email: 'marcus@example.com', role: 'Event Coordinator', organization: '', contact_details: '' },
]

function makeEvent(overrides: Partial<SubmittedEvent>): SubmittedEvent {
  return {
    id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    eventName: 'Community Workshop',
    description: '',
    purpose: '',
    preferredStartDate: '2026-11-10T09:00:00+08:00',
    preferredEndDate: '2026-11-10T12:00:00+08:00',
    expectedAttendance: '30',
    venueRequirements: '',
    accessibilityNeeds: '',
    equipmentRequirements: '',
    registrationNeeds: '',
    status: 'Submitted',
    submittedAt: '2026-10-01T08:00:00+08:00',
    coordinatorId: null,
    organiserId,
    decision: null,
    decisionHistory: [],
    actionDetails: '',
    actionHistory: [],
    ...overrides,
  }
}

const unassigned = makeEvent({})
const assigned = makeEvent({
  id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  eventName: 'Innovation Expo',
  status: 'Under Review',
  coordinatorId,
})

const resolveUserName = (userId: string | null | undefined) => userId === organiserId ? 'Olivia Organiser' : null

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(assignmentApi).mockImplementation(async (path, method) => {
    if (path.startsWith('/queue?')) return { events: [unassigned, assigned] }
    if (path === '/coordinators') return { coordinators }
    if (method === 'POST' && path.includes(unassigned.id)) {
      return { ...unassigned, status: 'Under Review', coordinatorId, assignedBy: leadId, assignedAt: '2026-10-27T04:00:00+00:00' }
    }
    if (method === 'POST' && path.includes(assigned.id)) {
      return { ...assigned, coordinatorId: otherCoordinatorId, previousCoordinatorId: coordinatorId, assignedBy: leadId, assignedAt: '2026-10-27T04:05:00+00:00' }
    }
    throw new Error(`Unexpected request: ${method ?? 'GET'} ${path}`)
  })
})

test('AC1: the Lead sees submitted requests with required details and assignment status', async () => {
  render(<UnassignedQueuePage role="Event Coordinator Lead" currentUserId={leadId} resolveUserName={resolveUserName} onViewDetails={vi.fn()} />)

  const unassignedRow = await screen.findByRole('row', { name: /Community Workshop/ })
  expect(within(unassignedRow).getByText('Olivia Organiser')).toBeInTheDocument()
  expect(within(unassignedRow).getByText(/10 Nov 2026/)).toBeInTheDocument()
  expect(within(unassignedRow).getByText('Unassigned')).toBeInTheDocument()

  const assignedRow = screen.getByRole('row', { name: /Innovation Expo/ })
  expect(within(assignedRow).getByText('Assigned')).toBeInTheDocument()
  expect(within(assignedRow).getByText('Alicia Tan')).toBeInTheDocument()
  expect(assignmentApi).toHaveBeenCalledWith(`/queue?actingUserId=${leadId}`)
})

test('AC2: assigning records the Lead through the API and keeps the event visible as Assigned', async () => {
  render(<UnassignedQueuePage role="Event Coordinator Lead" currentUserId={leadId} resolveUserName={resolveUserName} onViewDetails={vi.fn()} />)

  const row = await screen.findByRole('row', { name: /Community Workshop/ })
  fireEvent.change(within(row).getByLabelText('Coordinator'), { target: { value: coordinatorId } })
  fireEvent.click(within(row).getByRole('button', { name: 'Assign' }))

  await waitFor(() => expect(assignmentApi).toHaveBeenCalledWith(
    `/events/${unassigned.id}/assign-coordinator/${coordinatorId}`,
    'POST',
    { actingUserId: leadId },
  ))
  expect(await within(row).findByText('Assigned')).toBeInTheDocument()
  expect(within(row).getByText('Alicia Tan')).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent('Community Workshop was assigned to Alicia Tan.')
})

test('AC3: reassignment replaces the displayed coordinator without removing the event', async () => {
  render(<UnassignedQueuePage role="Event Coordinator Lead" currentUserId={leadId} resolveUserName={resolveUserName} onViewDetails={vi.fn()} />)

  const row = await screen.findByRole('row', { name: /Innovation Expo/ })
  fireEvent.change(within(row).getByLabelText('New coordinator'), { target: { value: otherCoordinatorId } })
  fireEvent.click(within(row).getByRole('button', { name: 'Reassign' }))

  expect(await within(row).findByText('Marcus Lim')).toBeInTheDocument()
  expect(within(row).getByText('Assigned')).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent('Innovation Expo was reassigned to Marcus Lim.')
  expect(assignmentApi).toHaveBeenCalledWith(
    `/events/${assigned.id}/assign-coordinator/${otherCoordinatorId}`,
    'POST',
    { actingUserId: leadId },
  )
})

test('only the Event Coordinator Lead can view assignment controls', () => {
  render(<UnassignedQueuePage role="Event Coordinator" currentUserId={coordinatorId} onViewDetails={vi.fn()} />)

  expect(screen.getByText('Coordinator assignments are visible only to the Event Coordinator Lead.')).toBeInTheDocument()
  expect(assignmentApi).not.toHaveBeenCalled()
})
