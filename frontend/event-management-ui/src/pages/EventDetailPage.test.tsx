import { render, screen } from '@testing-library/react'
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
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(eventApi).mockResolvedValue(event)
  vi.mocked(fetchRegistrations).mockResolvedValue([])
})

test('shows the selected event status and full recorded details', async () => {
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" isManager={false} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)

  expect(await screen.findByRole('heading', { name: 'Community Workshop' })).toBeInTheDocument()
  expect(screen.getByText('Rejected')).toBeInTheDocument()
  expect(screen.getByText('A practical workshop')).toBeInTheDocument()
  expect(screen.getByText('Learning')).toBeInTheDocument()
  expect(screen.getByText('Seminar room')).toBeInTheDocument()
  expect(screen.getByText('Wheelchair access')).toBeInTheDocument()
  expect(screen.getByText('Projector')).toBeInTheDocument()
  expect(screen.getByText('Online registration')).toBeInTheDocument()
  expect(screen.getByText(/Assigned to/)).toHaveTextContent('Alicia Tan')
  expect(eventApi).toHaveBeenCalledWith(`/events/${event.id}?coordinatorId=${coordinatorId}`)
  expect(fetchRegistrations).not.toHaveBeenCalled()
})

test('does not load event details for another role', () => {
  render(<EventDetailPage eventId={event.id} role="Event Organiser" isManager={false} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" backLabel="my events" onBack={vi.fn()} />)

  expect(screen.getByText('Event details are visible to Event Coordinators.')).toBeInTheDocument()
  expect(eventApi).not.toHaveBeenCalled()
})
