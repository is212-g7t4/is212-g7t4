import { render, screen, within } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { assignmentApi } from '../features/event/submission'
import type { Coordinator, SubmittedEvent } from '../features/event/submission'
import { CoordinatorWorkloadPage } from './CoordinatorWorkloadPage'

vi.mock('../features/event/submission', () => ({ assignmentApi: vi.fn() }))

const leadId = '33333333-3333-4333-8333-333333333333'
const coordinatorId = '11111111-1111-4111-8111-111111111111'
const organiserId = '44444444-4444-4444-8444-444444444444'
const lead: Coordinator = { user_id: leadId, username: 'Grace Lee', email: 'grace@example.com', role: 'Event Coordinator Lead', organization: '', contact_details: '' }
const coordinator: Coordinator = { user_id: coordinatorId, username: 'Alicia Tan', email: 'alicia@example.com', role: 'Event Coordinator', organization: '', contact_details: '' }

function makeEvent(overrides: Partial<SubmittedEvent>): SubmittedEvent {
  return {
    id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    eventName: 'Community Workshop',
    description: '',
    purpose: '',
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
    organiserId,
    decision: null,
    decisionHistory: [],
    actionDetails: '',
    actionHistory: [],
    ...overrides,
  }
}

const assigned = makeEvent({})
const unassigned = makeEvent({ id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', eventName: 'Charity Run', status: 'Submitted', coordinatorId: null })
const resolveUserName = (userId: string | null | undefined) => (userId === organiserId ? 'Olivia Organiser' : null)

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(assignmentApi).mockResolvedValue({
    coordinators: [{ ...lead, events: [] }, { ...coordinator, events: [assigned] }],
    unassigned: [unassigned],
    otherAssigned: [],
  })
})

test('AC1/AC2: the Lead sees every coordinator with their active events, each with name, organiser, date/time and status', async () => {
  const onViewDetails = vi.fn()
  render(<CoordinatorWorkloadPage role="Event Coordinator Lead" currentUserId={leadId} resolveUserName={resolveUserName} onViewDetails={onViewDetails} />)

  const alicia = await screen.findByRole('region', { name: 'Alicia Tan' })
  expect(within(alicia).getByText('alicia@example.com · 1 active event')).toBeInTheDocument()
  const row = within(alicia).getByRole('row', { name: /Community Workshop/ })
  expect(within(row).getByText('Olivia Organiser')).toBeInTheDocument()
  expect(within(row).getByText(/10 Oct 2026/)).toBeInTheDocument()
  expect(within(row).getByText('Under Review')).toBeInTheDocument()

  // A coordinator with nothing on still shows up, so the Lead can see who is free.
  const grace = screen.getByRole('region', { name: 'Grace Lee (Lead)' })
  expect(within(grace).getByText('No active events.')).toBeInTheDocument()

  within(row).getByRole('button', { name: 'View details' }).click()
  expect(onViewDetails).toHaveBeenCalledWith(assigned.id)
  expect(assignmentApi).toHaveBeenCalledWith(`/workload?actingUserId=${leadId}`)
})

test('AC3: unassigned events are listed and clearly marked as unassigned', async () => {
  render(<CoordinatorWorkloadPage role="Event Coordinator Lead" currentUserId={leadId} resolveUserName={resolveUserName} onViewDetails={vi.fn()} />)

  const section = await screen.findByRole('region', { name: 'Unassigned' })
  expect(within(section).getByText('Unassigned', { selector: '.status-badge' })).toBeInTheDocument()
  expect(within(section).getByRole('row', { name: /Charity Run/ })).toBeInTheDocument()
})

test('AC5: the view is read-only — no inputs, selects or assignment controls', async () => {
  render(<CoordinatorWorkloadPage role="Event Coordinator Lead" currentUserId={leadId} resolveUserName={resolveUserName} onViewDetails={vi.fn()} />)

  await screen.findByRole('region', { name: 'Alicia Tan' })
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  expect(screen.getAllByRole('button').every((button) => /View details|Refresh/.test(button.textContent ?? ''))).toBe(true)
})

test('events whose coordinator is no longer listed still appear', async () => {
  vi.mocked(assignmentApi).mockResolvedValue({
    coordinators: [],
    unassigned: [],
    otherAssigned: [makeEvent({ eventName: 'Orphaned Fair' })],
  })
  render(<CoordinatorWorkloadPage role="Event Coordinator Lead" currentUserId={leadId} resolveUserName={resolveUserName} onViewDetails={vi.fn()} />)

  const section = await screen.findByRole('region', { name: 'Assigned to someone who is no longer a coordinator' })
  expect(within(section).getByText('Orphaned Fair')).toBeInTheDocument()
})

test('AC6: anyone other than the Lead sees a warning and nothing is fetched', () => {
  render(<CoordinatorWorkloadPage role="Event Coordinator" currentUserId={coordinatorId} onViewDetails={vi.fn()} />)

  expect(screen.getByText('Coordinator workload is visible only to the Event Coordinator Lead.')).toBeInTheDocument()
  expect(assignmentApi).not.toHaveBeenCalled()
})

test('a service error is shown to the Lead', async () => {
  vi.mocked(assignmentApi).mockRejectedValue(new Error('Only the Event Coordinator Lead can view coordinator workload'))
  render(<CoordinatorWorkloadPage role="Event Coordinator Lead" currentUserId={leadId} onViewDetails={vi.fn()} />)

  expect(await screen.findByRole('alert')).toHaveTextContent('Only the Event Coordinator Lead can view coordinator workload')
})
