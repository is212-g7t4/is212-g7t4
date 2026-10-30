import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
  { ...baseEvent, id: 'confirmed-1', eventName: 'Confirmed Fair', status: 'Confirmed' },
]

beforeEach(() => {
  vi.resetAllMocks()
})

// The page loads submitted events and drafts separately; answer each request on its own.
function mockOrganiserApi(loadEvents: () => Promise<unknown>, drafts: object[] = []) {
  vi.mocked(eventApi).mockImplementation(async (path: string) => path.startsWith('/events/drafts') ? { events: drafts } : loadEvents())
}

function renderList(onViewDetails = vi.fn()) {
  render(<MyEventsPage role="Event Organiser" currentCoordinatorId={ORGANISER_ID} currentCoordinatorName="Michael" onViewDetails={onViewDetails} />)
  return onViewDetails
}

test('organiser list shows every event they created; every event opens; only confirmed ones show a registration count', async () => {
  mockOrganiserApi(async () => ({ events }))
  vi.mocked(fetchRegistrationCounts).mockResolvedValue({ 'confirmed-1': { total: 3, confirmed: 2 } })
  const onViewDetails = renderList()

  expect(await screen.findByText('Confirmed Fair')).toBeInTheDocument()
  expect(eventApi).toHaveBeenCalledWith(`/events?organiserId=${ORGANISER_ID}`)
  expect(fetchRegistrationCounts).toHaveBeenCalledWith(['confirmed-1'])
  expect(screen.getByText('3 registrations')).toBeInTheDocument()
  expect(screen.getByText('Pending Fair')).toBeInTheDocument()
  expect(screen.getByText('Rejected Fair')).toBeInTheDocument()
  expect(screen.getByText('The event has been rejected. Submit a new request.')).toBeInTheDocument()
  // Approved and Submitted events can't take registrations yet.
  expect(screen.getAllByText('Registrations are available once the event is confirmed')).toHaveLength(2)
  expect(screen.getAllByRole('button')).toHaveLength(4)

  fireEvent.click(screen.getByRole('button', { name: /Approved Fair/ }))
  expect(onViewDetails).toHaveBeenCalledWith('approved-1')
  fireEvent.click(screen.getByRole('button', { name: /Pending Fair/ }))
  expect(onViewDetails).toHaveBeenCalledWith('submitted-1')
  fireEvent.click(screen.getByRole('button', { name: /Rejected Fair/ }))
  expect(onViewDetails).toHaveBeenCalledWith('rejected-1')
})

test('organiser list still shows events when counts cannot be loaded', async () => {
  mockOrganiserApi(async () => ({ events }))
  vi.mocked(fetchRegistrationCounts).mockRejectedValue(new Error('down'))
  renderList()

  expect(await screen.findByText('Approved Fair')).toBeInTheDocument()
  expect(screen.getByRole('alert')).toHaveTextContent('Unable to load registration counts.')
  expect(screen.getByText('Registrations unavailable')).toBeInTheDocument()
})

test('organiser with no events sees an empty state', async () => {
  mockOrganiserApi(async () => ({ events: [] }))
  vi.mocked(fetchRegistrationCounts).mockResolvedValue({})
  renderList()
  expect(await screen.findByText('You have not created any events yet.')).toBeInTheDocument()
})

test('organiser list shows the service error', async () => {
  mockOrganiserApi(async () => { throw new Error('Event service unavailable') })
  renderList()
  expect(await screen.findByRole('alert')).toHaveTextContent('Event service unavailable')
})

const drafts = [
  { ...baseEvent, id: 'draft-1', eventName: 'Spring Fair', status: 'Draft', preferredStartDate: '', preferredEndDate: '' },
  { ...baseEvent, id: 'draft-2', eventName: 'Winter Gala', status: 'Draft', preferredStartDate: '', preferredEndDate: '' },
]

test('AC2: lists each draft separately and opens the chosen one', async () => {
  mockOrganiserApi(async () => ({ events: [] }), drafts)
  const onOpenDraft = vi.fn()
  render(<MyEventsPage role="Event Organiser" currentCoordinatorId={ORGANISER_ID} onViewDetails={vi.fn()} onOpenDraft={onOpenDraft} />)

  fireEvent.click(await screen.findByRole('button', { name: 'Open draft Winter Gala' }))

  expect(eventApi).toHaveBeenCalledWith(`/events/drafts?organiserId=${ORGANISER_ID}`)
  expect(screen.getByRole('button', { name: 'Open draft Spring Fair' })).toBeInTheDocument()
  expect(onOpenDraft).toHaveBeenCalledExactlyOnceWith('draft-2')
})

test('AC3: deleting a draft removes it from the draft list', async () => {
  mockOrganiserApi(async () => ({ events: [] }), drafts)
  renderList()

  fireEvent.click(await screen.findByRole('button', { name: 'Delete draft Spring Fair' }))
  expect(screen.getByRole('dialog', { name: 'Delete draft?' })).toHaveTextContent('Spring Fair')
  fireEvent.click(screen.getByRole('button', { name: 'Delete draft' }))

  await waitFor(() => expect(screen.queryByText('Spring Fair')).not.toBeInTheDocument())
  expect(eventApi).toHaveBeenCalledWith(`/events/drafts/draft-1?organiserId=${ORGANISER_ID}`, undefined, 'DELETE')
  expect(screen.getByText('Winter Gala')).toBeInTheDocument()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

test('AC2: clicking Delete on a draft card does not also open the draft', async () => {
  mockOrganiserApi(async () => ({ events: [] }), drafts)
  const onOpenDraft = vi.fn()
  render(<MyEventsPage role="Event Organiser" currentCoordinatorId={ORGANISER_ID} onViewDetails={vi.fn()} onOpenDraft={onOpenDraft} />)

  fireEvent.click(await screen.findByRole('button', { name: 'Delete draft Spring Fair' }))

  expect(screen.getByRole('dialog', { name: 'Delete draft?' })).toBeInTheDocument()
  expect(onOpenDraft).not.toHaveBeenCalled()
})

test('AC3: cancelling the delete confirmation keeps the draft', async () => {
  mockOrganiserApi(async () => ({ events: [] }), drafts)
  renderList()

  fireEvent.click(await screen.findByRole('button', { name: 'Delete draft Spring Fair' }))
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.getByText('Spring Fair')).toBeInTheDocument()
  expect(eventApi).not.toHaveBeenCalledWith(expect.stringContaining('/events/drafts/draft-1'), undefined, 'DELETE')
})

function renderDetail() {
  render(<EventDetailPage eventId="approved-1" role="Event Organiser" currentCoordinatorId={ORGANISER_ID} backLabel="My events" onBack={vi.fn()} />)
}

test('organiser detail lists attendees with status and totals once the event is confirmed', async () => {
  vi.mocked(eventApi).mockResolvedValue({ ...events[0], status: 'Confirmed' })
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

test.each([events[0], events[1]])('organiser detail for a $status event shows no registrations', async (event) => {
  vi.mocked(eventApi).mockResolvedValue(event)
  renderDetail()

  expect(await screen.findByText('Registrations are only available for confirmed events.')).toBeInTheDocument()
  expect(fetchRegistrations).not.toHaveBeenCalled()
})

test('organiser detail shows a registrations error', async () => {
  vi.mocked(eventApi).mockResolvedValue({ ...events[0], status: 'Confirmed' })
  vi.mocked(fetchRegistrations).mockRejectedValue(new Error('Unable to load registrations.'))
  renderDetail()
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load registrations.')
})

test('organiser can answer the open clarification without editing the request', async () => {
  const clarificationEvent = {
    ...events[1],
    status: 'Clarification Requested',
    coordinatorId: '11111111-1111-4111-8111-111111111111',
    clarificationHistory: [{
      id: 'clarification-1',
      question: 'Who is the intended audience?',
      requestedBy: '11111111-1111-4111-8111-111111111111',
      requestedAt: '2026-10-20T01:00:00+00:00',
      response: null,
      respondedBy: null,
      respondedAt: null,
    }],
  }
  vi.mocked(eventApi)
    .mockResolvedValueOnce(clarificationEvent)
    .mockResolvedValueOnce({
      ...clarificationEvent,
      status: 'Submitted',
      clarificationHistory: [{
        ...clarificationEvent.clarificationHistory[0],
        response: 'All enrolled students.',
        respondedBy: ORGANISER_ID,
        respondedAt: '2026-10-20T02:00:00+00:00',
      }],
    })
  render(<EventDetailPage eventId="submitted-1" role="Event Organiser" currentCoordinatorId={ORGANISER_ID} backLabel="My events" onBack={vi.fn()} />)

  expect(await screen.findByText('Who is the intended audience?')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /edit/i })).not.toBeInTheDocument()
  const submit = screen.getByRole('button', { name: 'Submit response' })
  expect(submit).toBeDisabled()
  fireEvent.change(screen.getByLabelText(/Clarification response/), { target: { value: 'All enrolled students.' } })
  fireEvent.click(submit)

  await waitFor(() => expect(eventApi).toHaveBeenLastCalledWith(
    '/events/submitted-1/clarification-response',
    { organiserId: ORGANISER_ID, response: 'All enrolled students.' },
    'PATCH',
  ))
  expect(await screen.findByText(/back with the same Event Coordinator/i)).toBeInTheDocument()
  expect(screen.getByText('All enrolled students.')).toBeInTheDocument()
})
