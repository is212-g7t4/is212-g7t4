import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { MyEventsPage } from './MyEventsPage'
import { EventDetailPage } from './EventDetailPage'
import { eventApi } from '../features/event/submission'
import { fetchRegistrationCounts, fetchRegistrations } from '../features/registration/registrations'

vi.mock('../features/event/submission', () => ({ eventApi: vi.fn() }))
vi.mock('../features/registration/registrations', () => ({
  fetchRegistrationCounts: vi.fn(),
  fetchRegistrations: vi.fn(),
}))

const ORGANISER_ID = '33333333-3333-4333-8333-333333333333'
const baseEvent = {
  description: 'd', purpose: 'p', preferredStartDate: '2026-10-01T09:00', preferredEndDate: '2026-10-01T17:00',
  expectedAttendance: '25', venueId: '', venueRequirements: 'Hall', accessibilityNeeds: '', equipmentRequirements: '',
  registrationNeeds: '', submittedAt: null, coordinatorId: null, organiserId: ORGANISER_ID, decision: null, decisionHistory: [],
}
const events = [
  { ...baseEvent, id: 'approved-1', eventName: 'Approved Fair', status: 'Approved' },
  { ...baseEvent, id: 'submitted-1', eventName: 'Pending Fair', status: 'Submitted' },
  { ...baseEvent, id: 'rejected-1', eventName: 'Rejected Fair', status: 'Rejected' },
]

beforeEach(() => {
  vi.resetAllMocks()
})

function renderList(onViewDetails = vi.fn()) {
  render(<MyEventsPage role="Event Organiser" isManager={false} currentCoordinatorId={ORGANISER_ID} currentCoordinatorName="Michael" onViewDetails={onViewDetails} />)
  return onViewDetails
}

test('organiser list shows every event they created; every event opens; only approved ones show a registration count', async () => {
  vi.mocked(eventApi).mockResolvedValue({ events })
  vi.mocked(fetchRegistrationCounts).mockResolvedValue({ 'approved-1': { total: 3, confirmed: 2 } })
  const onViewDetails = renderList()

  expect(await screen.findByText('Approved Fair')).toBeInTheDocument()
  expect(eventApi).toHaveBeenCalledWith(`/events?organiserId=${ORGANISER_ID}`)
  expect(fetchRegistrationCounts).toHaveBeenCalledWith(['approved-1'])
  expect(screen.getByText('3 registrations')).toBeInTheDocument()
  expect(screen.getByText('Pending Fair')).toBeInTheDocument()
  expect(screen.getByText('Rejected Fair')).toBeInTheDocument()
  expect(screen.getByText('The event has been rejected. Submit a new request.')).toBeInTheDocument()
  expect(screen.getByText('Registrations are available once the event is approved')).toBeInTheDocument()
  expect(screen.getAllByRole('button')).toHaveLength(3)

  fireEvent.click(screen.getByRole('button', { name: /Approved Fair/ }))
  expect(onViewDetails).toHaveBeenCalledWith('approved-1')
  fireEvent.click(screen.getByRole('button', { name: /Pending Fair/ }))
  expect(onViewDetails).toHaveBeenCalledWith('submitted-1')
  fireEvent.click(screen.getByRole('button', { name: /Rejected Fair/ }))
  expect(onViewDetails).toHaveBeenCalledWith('rejected-1')
})

test('organiser list still shows events when counts cannot be loaded', async () => {
  vi.mocked(eventApi).mockResolvedValue({ events })
  vi.mocked(fetchRegistrationCounts).mockRejectedValue(new Error('down'))
  renderList()

  expect(await screen.findByText('Approved Fair')).toBeInTheDocument()
  expect(screen.getByRole('alert')).toHaveTextContent('Unable to load registration counts.')
  expect(screen.getByText('Registrations unavailable')).toBeInTheDocument()
})

test('organiser with no events sees an empty state', async () => {
  vi.mocked(eventApi).mockResolvedValue({ events: [] })
  vi.mocked(fetchRegistrationCounts).mockResolvedValue({})
  renderList()
  expect(await screen.findByText('You have not created any events yet.')).toBeInTheDocument()
})

test('organiser list shows the service error', async () => {
  vi.mocked(eventApi).mockRejectedValue(new Error('Event service unavailable'))
  renderList()
  expect(await screen.findByRole('alert')).toHaveTextContent('Event service unavailable')
})

function renderDetail() {
  render(<EventDetailPage eventId="approved-1" role="Event Organiser" isManager={false} currentCoordinatorId={ORGANISER_ID} backLabel="My events" onBack={vi.fn()} />)
}

test('organiser detail lists attendees with status and totals', async () => {
  vi.mocked(eventApi).mockResolvedValue(events[0])
  vi.mocked(fetchRegistrations).mockResolvedValue([
    { id: 'r1', attendeeName: 'Lena Ho', attendeeEmail: 'lena@example.com', attendeeOrganization: 'Acme', registrationDate: '2026-09-13T09:15:00', status: 'Confirmed' },
    { id: 'r2', attendeeName: 'Sam Lim', attendeeEmail: 'sam@example.com', attendeeOrganization: '', registrationDate: null, status: 'Withdrawn' },
  ])
  renderDetail()

  expect(await screen.findByText('Lena Ho')).toBeInTheDocument()
  expect(eventApi).toHaveBeenCalledWith(`/events/approved-1?organiserId=${ORGANISER_ID}`)
  expect(screen.getByText('lena@example.com')).toBeInTheDocument()
  expect(screen.getByText('Acme')).toBeInTheDocument()
  expect(screen.getByText('Not recorded')).toBeInTheDocument()
  expect(screen.getByText('Withdrawn', { selector: 'td' })).toBeInTheDocument()
  expect(screen.getByText('Total registrations').nextSibling).toHaveTextContent('2')
  expect(screen.getByText('Confirmed', { selector: 'dt' }).nextSibling).toHaveTextContent('1')
})

test('organiser who did not create the event sees the refusal and no registrations are requested', async () => {
  vi.mocked(eventApi).mockRejectedValue(new Error('You can only view registrations for events you created.'))
  renderDetail()

  expect(await screen.findByRole('alert')).toHaveTextContent('You can only view registrations for events you created.')
  expect(fetchRegistrations).not.toHaveBeenCalled()
})

test('organiser detail for a non-approved event shows no registrations', async () => {
  vi.mocked(eventApi).mockResolvedValue(events[1])
  renderDetail()

  expect(await screen.findByText('Registrations are only available for approved events.')).toBeInTheDocument()
  expect(fetchRegistrations).not.toHaveBeenCalled()
})

test('organiser detail shows a registrations error', async () => {
  vi.mocked(eventApi).mockResolvedValue(events[0])
  vi.mocked(fetchRegistrations).mockRejectedValue(new Error('Unable to load registrations.'))
  renderDetail()
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load registrations.')
})
