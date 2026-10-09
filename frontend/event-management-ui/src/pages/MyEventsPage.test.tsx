import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { eventApi } from '../features/event/submission'
import type { SubmittedEvent } from '../features/event/submission'
import { fetchVenues } from '../features/venue/venues'
import type { Venue } from '../features/venue/venues'
import { MyEventsPage } from './MyEventsPage'

vi.mock('../features/event/submission', () => ({ eventApi: vi.fn() }))
vi.mock('../features/venue/venues', () => ({ fetchVenues: vi.fn() }))

const coordinatorId = '11111111-1111-4111-8111-111111111111'
const venue: Venue = {
  id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', name: 'Grand Hall', location: 'Level 1',
  capacity: 100, facilities: [], accessibility: '', supportedLayouts: [], status: 'Available',
}
const unrelatedVenue: Venue = {
  ...venue, id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', name: 'Unassigned Auditorium',
}
const submittedEvent: SubmittedEvent = {
  id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  eventName: 'Community Workshop',
  description: 'A practical workshop',
  purpose: 'Learning',
  preferredStartDate: '2026-10-10T09:00:00+08:00',
  preferredEndDate: '2026-10-10T12:00:00+08:00',
  expectedAttendance: '30',
  venueId: venue.id,
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
  vi.mocked(fetchVenues).mockResolvedValue([venue, unrelatedVenue])
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

test('filters events using a registered venue dropdown', async () => {
  render(<MyEventsPage role="Event Coordinator" isManager={false} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" onViewDetails={vi.fn()} />)

  await screen.findByRole('option', { name: 'Grand Hall' })
  expect(screen.queryByRole('option', { name: 'Unassigned Auditorium' })).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Venue'), { target: { value: venue.id } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply filters' }))

  await waitFor(() => expect(eventApi).toHaveBeenLastCalledWith(
    `/events?coordinatorId=${coordinatorId}&venueId=${venue.id}`,
  ))
})

test('does not load internal events for an attendee', () => {
  render(<MyEventsPage role="Attendee" isManager={false} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" onViewDetails={vi.fn()} />)

  expect(screen.getByText('Event information is visible to Event Coordinators, Venue Staff, and Technical Support.')).toBeInTheDocument()
  expect(eventApi).not.toHaveBeenCalled()
})
