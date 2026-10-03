import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { eventApi } from '../features/event/submission'
import type { SubmittedEvent } from '../features/event/submission'
import { fetchRegistrations } from '../features/registration/registrations'
import { EventDetailPage } from './EventDetailPage'

vi.mock('../features/event/submission', () => ({ eventApi: vi.fn() }))
vi.mock('../features/registration/registrations', () => ({ fetchRegistrations: vi.fn() }))

const coordinatorId = '11111111-1111-4111-8111-111111111111'
const event: SubmittedEvent = {
  id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  eventName: 'Community Workshop',
  description: 'A practical workshop',
  purpose: 'Learning',
  preferredStartDate: '2026-10-10T09:00:00+08:00',
  preferredEndDate: '2026-10-10T12:00:00+08:00',
  expectedAttendance: '30',
  venueId: '',
  venueRequirements: 'Seminar room',
  accessibilityNeeds: 'Wheelchair access',
  equipmentRequirements: 'Projector',
  registrationNeeds: 'Online registration',
  status: 'Rejected',
  submittedAt: '2026-10-01T08:00:00+08:00',
  coordinatorId,
  decision: {
    status: 'Rejected',
    coordinatorId,
    decidedAt: '2026-10-02T10:00:00+08:00',
    reason: 'Date unavailable',
  },
  decisionHistory: [],
  actionDetails: 'Venue availability checked.',
  actionHistory: [{
    status: 'Rejected',
    details: 'Venue availability checked.',
    coordinatorId,
    recordedAt: '2026-10-02T10:00:00+08:00',
  }],
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(eventApi).mockResolvedValue(event)
  vi.mocked(fetchRegistrations).mockResolvedValue([])
})

test('shows the selected event status and full recorded details', async () => {
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" isManager={false} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)

  expect(await screen.findByRole('heading', { name: 'Community Workshop' })).toBeInTheDocument()
  expect(screen.getByText('Rejected', { selector: '.status-badge' })).toBeInTheDocument()
  expect(screen.getByText('A practical workshop')).toBeInTheDocument()
  expect(screen.getByText('Learning')).toBeInTheDocument()
  expect(screen.getByText('Seminar room')).toBeInTheDocument()
  expect(screen.getByText('Wheelchair access')).toBeInTheDocument()
  expect(screen.getByText('Projector')).toBeInTheDocument()
  expect(screen.getByText('Online registration')).toBeInTheDocument()
  expect(screen.getByDisplayValue('Venue availability checked.')).toBeInTheDocument()
  expect(screen.getByText('Venue availability checked.', { selector: 'dd' })).toBeInTheDocument()
  expect(screen.getByText(/Assigned to/)).toHaveTextContent('Alicia Tan')
  expect(eventApi).toHaveBeenCalledWith(`/events/${event.id}?coordinatorId=${coordinatorId}`)
  expect(fetchRegistrations).not.toHaveBeenCalled()
})

test('assigned coordinator updates the status and action details', async () => {
  const submittedEvent: SubmittedEvent = {
    ...event,
    status: 'Under Review',
    decision: null,
    actionDetails: 'Initial review completed.',
    actionHistory: [],
  }
  vi.mocked(eventApi).mockResolvedValueOnce(submittedEvent).mockResolvedValueOnce({
    ...submittedEvent,
    status: 'Approved',
    actionDetails: 'Venue and equipment confirmed.',
    actionHistory: [{
      status: 'Approved',
      details: 'Venue and equipment confirmed.',
      coordinatorId,
      recordedAt: '2026-10-03T10:00:00+08:00',
    }],
  })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" isManager={false} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'Approved' } })
  fireEvent.change(screen.getByLabelText('Action details'), { target: { value: 'Venue and equipment confirmed.' } })
  expect(screen.getByText('Unsaved changes')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Save progress' }))

  await waitFor(() => expect(eventApi).toHaveBeenLastCalledWith(
    `/events/${event.id}/progress`,
    { coordinatorId, status: 'Approved', actionDetails: 'Venue and equipment confirmed.' },
    'PATCH',
  ))
  expect(await screen.findByText('Event progress updated successfully.')).toBeInTheDocument()
  expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument()
})

test('rejected event status cannot be changed while action details remain editable', async () => {
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" isManager={false} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)

  await screen.findByRole('heading', { name: 'Community Workshop' })
  const status = screen.getByLabelText('Status')
  expect(status).toHaveValue('Rejected')
  expect(status.querySelectorAll('option')).toHaveLength(1)
  expect(status).toHaveTextContent('Rejected')

  fireEvent.change(screen.getByLabelText('Action details'), { target: { value: 'Follow-up recorded.' } })
  expect(screen.getByText('Unsaved changes')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Save progress' })).toBeEnabled()
})

test('approved event can move to confirmed', async () => {
  const approvedEvent: SubmittedEvent = { ...event, status: 'Approved' }
  vi.mocked(eventApi).mockResolvedValueOnce(approvedEvent).mockResolvedValueOnce({
    ...approvedEvent,
    status: 'Confirmed',
    actionDetails: 'Event arrangements confirmed.',
  })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" isManager={false} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  const status = screen.getByLabelText('Status')
  expect(status).toHaveTextContent('Approved')
  expect(status).toHaveTextContent('Confirmed')
  fireEvent.change(status, { target: { value: 'Confirmed' } })
  fireEvent.change(screen.getByLabelText('Action details'), { target: { value: 'Event arrangements confirmed.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save progress' }))

  await waitFor(() => expect(eventApi).toHaveBeenLastCalledWith(
    `/events/${event.id}/progress`,
    { coordinatorId, status: 'Confirmed', actionDetails: 'Event arrangements confirmed.' },
    'PATCH',
  ))
})

test('does not load event details for another role', () => {
  render(<EventDetailPage eventId={event.id} role="Event Organiser" isManager={false} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" backLabel="my events" onBack={vi.fn()} />)

  expect(screen.getByText('Event details are visible to Event Coordinators.')).toBeInTheDocument()
  expect(eventApi).not.toHaveBeenCalled()
})
