import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { eventApi } from '../features/event/submission'
import type { SubmittedEvent } from '../features/event/submission'
import { MyEventsPage } from './MyEventsPage'

vi.mock('../features/event/submission', () => ({ eventApi: vi.fn() }))

const coordinatorId = '11111111-1111-4111-8111-111111111111'
const submittedEvent: SubmittedEvent = {
  id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  eventName: 'Community Workshop',
  description: 'A practical workshop',
  purpose: 'Learning',
  preferredStartDate: '2026-10-10T09:00:00+08:00',
  preferredEndDate: '2026-10-10T12:00:00+08:00',
  expectedAttendance: '30',
  venueRequirements: 'Seminar room',
  accessibilityNeeds: '',
  equipmentRequirements: 'Projector',
  registrationNeeds: '',
  status: 'Submitted',
  submittedAt: '2026-10-01T08:00:00+08:00',
  coordinatorId,
  decision: null,
  decisionHistory: [],
  actionDetails: '',
  actionHistory: [],
}
const approvedEvent: SubmittedEvent = {
  ...submittedEvent,
  id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  eventName: 'Approved Conference',
  status: 'Approved',
}
const confirmedEvent: SubmittedEvent = {
  ...submittedEvent,
  id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
  eventName: 'Confirmed Summit',
  status: 'Confirmed',
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(eventApi).mockImplementation(async (path) => ({
    events: path.includes('status=Approved') ? [approvedEvent]
      : path.includes('status=Confirmed') ? [confirmedEvent]
        : [submittedEvent, approvedEvent, confirmedEvent],
  }))
})

test('shows the coordinator events and filters them by status', async () => {
  render(<MyEventsPage role="Event Coordinator" isManager={false} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" onViewDetails={vi.fn()} />)

  expect(await screen.findByText('Community Workshop')).toBeInTheDocument()
  expect(screen.getByText('Approved Conference')).toBeInTheDocument()
  expect(eventApi).toHaveBeenCalledWith(`/events?coordinatorId=${coordinatorId}`)
  expect(screen.getByRole('button', { name: 'Apply filters' })).toHaveClass('primary')

  fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'Approved' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply filters' }))

  await waitFor(() => expect(eventApi).toHaveBeenLastCalledWith(`/events?coordinatorId=${coordinatorId}&status=Approved`))
  expect(await screen.findByText('Approved Conference')).toBeInTheDocument()
  expect(screen.queryByText('Community Workshop')).not.toBeInTheDocument()

  fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'Confirmed' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply filters' }))
  await waitFor(() => expect(eventApi).toHaveBeenLastCalledWith(`/events?coordinatorId=${coordinatorId}&status=Confirmed`))
  expect(await screen.findByText('Confirmed Summit')).toBeInTheDocument()
})

test('opens the selected event details', async () => {
  const onViewDetails = vi.fn()
  render(<MyEventsPage role="Event Coordinator" isManager={false} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" onViewDetails={onViewDetails} />)

  fireEvent.click(await screen.findByRole('button', { name: /Community Workshop/ }))

  expect(onViewDetails).toHaveBeenCalledWith(submittedEvent.id)
})

test.each(['Venue Staff', 'Technical Support'] as const)('%s sees all events and can use the existing filters', async (role) => {
  render(<MyEventsPage role={role} isManager={false} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" onViewDetails={vi.fn()} />)

  expect(await screen.findByText('Community Workshop')).toBeInTheDocument()
  expect(screen.getByText(/Showing all events in the planning process/)).toBeInTheDocument()
  expect(eventApi).toHaveBeenCalledWith(
    `/events?coordinatorId=${coordinatorId}&isManager=true&viewerRole=${role.replace(' ', '+')}`,
  )

  fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'Approved' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply filters' }))
  await waitFor(() => expect(eventApi).toHaveBeenLastCalledWith(
    `/events?coordinatorId=${coordinatorId}&isManager=true&viewerRole=${role.replace(' ', '+')}&status=Approved`,
  ))
})

test('filters events by their venue requirements text', async () => {
  render(<MyEventsPage role="Event Coordinator" isManager={false} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" onViewDetails={vi.fn()} />)

  await screen.findByText('Community Workshop')
  fireEvent.change(screen.getByLabelText('Venue'), { target: { value: ' Seminar room ' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply filters' }))

  await waitFor(() => expect(eventApi).toHaveBeenLastCalledWith(
    `/events?coordinatorId=${coordinatorId}&venue=Seminar+room`,
  ))
})

test('does not load internal events for an attendee', () => {
  render(<MyEventsPage role="Attendee" isManager={false} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" onViewDetails={vi.fn()} />)

  expect(screen.getByText('Event information is visible to Event Coordinators, Venue Staff, and Technical Support.')).toBeInTheDocument()
  expect(eventApi).not.toHaveBeenCalled()
})
