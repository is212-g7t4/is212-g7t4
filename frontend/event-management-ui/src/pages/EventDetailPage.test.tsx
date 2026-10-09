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

// SCRUM-152 AC1: replaces "approved event can move to confirmed" — 'Confirmed'
// is the preparation stage and only the safety workflow sets it, so the
// coordinator is told what has to happen instead of being offered a dead option.
test('approved event offers only Approved and says to submit for safety check', async () => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, status: 'Approved' })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" isManager={false} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  const status = screen.getByLabelText('Status')
  expect(status.querySelectorAll('option')).toHaveLength(1)
  expect(status).toHaveTextContent('Approved')
  // 'Confirmed' isn't offered at all, not even as a disabled option.
  expect(screen.queryByRole('option', { name: 'Confirmed' })).not.toBeInTheDocument()
  expect(screen.getByRole('note')).toHaveTextContent(
    'Submit this event for safety check for it to progress to Confirmed.',
  )
})

test('pending safety check event shows the waiting reason', async () => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, status: 'Pending Safety Check' })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" isManager={false} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(screen.getByRole('note')).toHaveTextContent(
    "This event is waiting for the Safety Officer's decision.",
  )
})

test('safety changes requested event says what must happen', async () => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, status: 'Safety Changes Requested' })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" isManager={false} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(screen.getByRole('note')).toHaveTextContent(
    'The Safety Officer has requested changes that must be made and resubmitted.',
  )
})

test('API block on confirming is shown to the coordinator', async () => {
  const blocked = 'Submit this event for safety check for it to progress to Confirmed.'
  vi.mocked(eventApi)
    .mockResolvedValueOnce({ ...event, status: 'Approved' })
    .mockRejectedValueOnce(new Error(blocked))
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" isManager={false} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  // The dropdown gives no way to ask for this, so drive the save the way a
  // crafted request would and check the API's reason reaches the coordinator.
  fireEvent.change(screen.getByLabelText('Action details'), { target: { value: 'Starting preparation.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save progress' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(blocked)
})

// Boundary: the gate must not over-block an event that already passed its check.
test('a confirmed event has reached preparation and records progress', async () => {
  const confirmedEvent: SubmittedEvent = { ...event, status: 'Confirmed' }
  vi.mocked(eventApi).mockResolvedValueOnce(confirmedEvent).mockResolvedValueOnce({
    ...confirmedEvent,
    actionDetails: 'Preparation under way.',
  })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" isManager={false} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  // Already past the gate, so no hint — and nothing further to move to.
  expect(screen.queryByRole('note')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Status')).toHaveValue('Confirmed')
  fireEvent.change(screen.getByLabelText('Action details'), { target: { value: 'Preparation under way.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save progress' }))

  await waitFor(() => expect(eventApi).toHaveBeenLastCalledWith(
    `/events/${event.id}/progress`,
    { coordinatorId, status: 'Confirmed', actionDetails: 'Preparation under way.' },
    'PATCH',
  ))
  expect(await screen.findByText('Event progress updated successfully.')).toBeInTheDocument()
})

test.each(['Venue Staff', 'Technical Support'] as const)('%s views event details without edit controls', async (role) => {
  render(<EventDetailPage eventId={event.id} role={role} isManager={false} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" backLabel="my events" onBack={vi.fn()} />)

  expect(await screen.findByRole('heading', { name: 'Community Workshop' })).toBeInTheDocument()
  expect(eventApi).toHaveBeenCalledWith(
    `/events/${event.id}?coordinatorId=${coordinatorId}&isManager=true&viewerRole=${role.replace(' ', '+')}`,
  )
  expect(screen.getByText('Only the assigned Event Coordinator can update this event.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Save progress' })).not.toBeInTheDocument()
})

test('does not load event details for an attendee', () => {
  render(<EventDetailPage eventId={event.id} role="Attendee" isManager={false} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" backLabel="my events" onBack={vi.fn()} />)

  expect(screen.getByText('Event information is visible to Event Coordinators, Venue Staff, and Technical Support.')).toBeInTheDocument()
  expect(eventApi).not.toHaveBeenCalled()
})
