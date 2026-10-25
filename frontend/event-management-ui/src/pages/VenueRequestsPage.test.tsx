import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { VenueRequestsPage } from './VenueRequestsPage'
import { fetchVenueRequests, reviewVenueRequest } from '../features/venue/venueBookings'
import type { User } from '../types'

vi.mock('../features/venue/venueBookings', () => ({ fetchVenueRequests: vi.fn(), reviewVenueRequest: vi.fn() }))
const user: User = { id: 'staff', username: 'Vera', role: 'Venue Staff', email: '', organization: '' }
const booking = { id: 'b1', eventId: 'e1', venueId: 'v1', venueName: 'Grand Hall', requestedStartTime: '2026-11-01T10:00:00',
  requestedEndTime: '2026-11-01T12:00:00', requiredCapacity: 80, venueRequirements: 'Step-free route', status: 'Pending Review',
  requestedBy: 'coordinator', reviewedBy: null, safetyFeedback: { reason: 'Exit blocked.', requestedChanges: ['Move the stage.'] } }
const event = { eventId: 'e1', eventName: 'Community Fair', eventStatus: 'Safety Changes Requested', coordinatorId: 'coordinator', bookings: [booking] }
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(fetchVenueRequests).mockResolvedValue([event])
  vi.mocked(reviewVenueRequest).mockResolvedValue({ ...booking, status: 'Approved', reviewedBy: user.id })
})
const show = () => render(<VenueRequestsPage role="Venue Staff" user={user} resolveUserName={() => 'Priya'} />)

test('shows pending bookings, safety reason and staff review actions', async () => {
  show()
  expect(await screen.findByText('Grand Hall')).toBeInTheDocument()
  expect(screen.getByText('Move the stage.')).toBeInTheDocument()
  expect(screen.getByText('Reason: Exit blocked.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled()
  expect(screen.getByRole('button', { name: 'Reject' })).toBeEnabled()
  expect(screen.getAllByRole('columnheader').at(-1)).toHaveTextContent('Safety change reason')
})

// Safety revision AC2 (staff UI): reopened venue requests expose and submit a new approval/rejection decision.
test.each(['Approved', 'Rejected'] as const)('staff can save %s on a safety revision booking', async (status) => {
  vi.mocked(reviewVenueRequest).mockResolvedValue({ ...booking, status })
  show()
  fireEvent.click(await screen.findByRole('button', { name: status === 'Approved' ? 'Approve' : 'Reject' }))
  await waitFor(() => expect(reviewVenueRequest).toHaveBeenCalledWith('b1', status, user))
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument())
  expect(screen.getByText(status, { selector: '.status-badge' })).toBeInTheDocument()
})

// Safety revision AC4 (UI only): an unaffected Approved booking is not offered another review action.
test('already reviewed bookings have no approve/reject controls', async () => {
  vi.mocked(fetchVenueRequests).mockResolvedValue([{ ...event, bookings: [{ ...booking, status: 'Approved', safetyFeedback: null }] }])
  show()
  const row = (await screen.findByText('Grand Hall')).closest('tr')!
  expect(within(row).queryByRole('button')).not.toBeInTheDocument()
  expect(within(row).getByText('Not flagged')).toBeInTheDocument()
})

test('filtering and refresh reload requests', async () => {
  show()
  await screen.findByText('Grand Hall')
  fireEvent.change(screen.getByLabelText('Filter by status'), { target: { value: 'Pending' } })
  await waitFor(() => expect(fetchVenueRequests).toHaveBeenLastCalledWith(user, 'Pending'))
  fireEvent.click(screen.getByRole('button', { name: 'Refresh requests' }))
  await waitFor(() => expect(fetchVenueRequests).toHaveBeenCalledTimes(3))
})

test('review conflicts stay visible without hiding the request', async () => {
  vi.mocked(reviewVenueRequest).mockRejectedValue(new Error('Venue conflict.'))
  show()
  fireEvent.click(await screen.findByRole('button', { name: 'Approve' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Venue conflict.')
  expect(screen.getByText('Grand Hall')).toBeInTheDocument()
})

test('other roles cannot load or review venue requests', () => {
  render(<VenueRequestsPage role="Event Coordinator" user={{ ...user, role: 'Event Coordinator' }} />)
  expect(screen.getByText('Venue requests are visible only to Venue Staff.')).toBeInTheDocument()
  expect(fetchVenueRequests).not.toHaveBeenCalled()
})
// SCRUM-28 AC3: staff see the event's own dates with its requests.
test('SCRUM-28 AC3: each event card shows the event dates and when the request was submitted', async () => {
  vi.mocked(fetchVenueRequests).mockResolvedValue([{ ...event, eventStart: '2026-11-01T09:00:00', eventEnd: '2026-11-01T17:00:00',
    bookings: [{ ...booking, requestedAt: '2026-10-01T02:30:00+00:00' }] }])
  show()
  expect(await screen.findByText(/Event: Sun, 1 Nov · 9:00 am – 5:00 pm/)).toBeInTheDocument()
  expect(screen.getByText('Submitted 1 Oct 2026, 10:30 am')).toBeInTheDocument()
})

test('SCRUM-28 AC3: an event without dates says so, and a legacy request has no submitted line', async () => {
  vi.mocked(fetchVenueRequests).mockResolvedValue([{ ...event, eventStart: null, eventEnd: null, bookings: [{ ...booking, requestedAt: null }] }])
  show()
  expect(await screen.findByText(/Event dates not set/)).toBeInTheDocument()
  expect(screen.queryByText(/^Submitted /)).not.toBeInTheDocument()
})

// SCRUM-28 AC4: requests needing a decision are identifiable as awaiting review.
test('SCRUM-28 AC4: both pending spellings read "Awaiting review" and are counted', async () => {
  vi.mocked(fetchVenueRequests).mockResolvedValue([{ ...event, eventStatus: 'Under Review', bookings: [
    { ...booking, id: 'new', status: 'Pending Review' },
    { ...booking, id: 'legacy', status: 'Pending', venueName: 'Studio' },
    { ...booking, id: 'done', status: 'Approved', venueName: 'Annex' },
  ] }])
  show()
  expect(await screen.findByText('2 awaiting review')).toBeInTheDocument()
  expect(screen.getAllByText('Awaiting review', { selector: '.status-badge' })).toHaveLength(2)
  expect(screen.getByText('Approved', { selector: '.status-badge' })).toBeInTheDocument()
  expect(screen.queryByText('Pending Review', { selector: '.status-badge' })).not.toBeInTheDocument()
})

test('SCRUM-28 AC4: the count follows a decision made on the page', async () => {
  vi.mocked(fetchVenueRequests).mockResolvedValue([{ ...event, eventStatus: 'Under Review', bookings: [booking, { ...booking, id: 'b2' }] }])
  vi.mocked(reviewVenueRequest).mockResolvedValue({ ...booking, status: 'Approved' })
  show()
  expect(await screen.findByText('2 awaiting review')).toBeInTheDocument()
  fireEvent.click(screen.getAllByRole('button', { name: 'Approve' })[0])
  expect(await screen.findByText('1 awaiting review')).toBeInTheDocument()
})

test('SCRUM-28 AC4: the "Awaiting review" filter still asks the API for Pending', async () => {
  show()
  await screen.findByText('Grand Hall')
  expect(screen.getByRole('option', { name: 'Awaiting review' })).toHaveValue('Pending')
  fireEvent.change(screen.getByLabelText('Filter by status'), { target: { value: 'Pending' } })
  await waitFor(() => expect(fetchVenueRequests).toHaveBeenLastCalledWith(user, 'Pending'))
})

test.each([
  ['Submitted', 'Opens for review when the event is Under Review'],
  ['Pending Safety Check', 'Not open for review while the event is Pending Safety Check'],
])('SCRUM-28 AC4: an awaiting request on a %s event explains why it has no actions', async (eventStatus, text) => {
  vi.mocked(fetchVenueRequests).mockResolvedValue([{ ...event, eventStatus, bookings: [booking] }])
  show()
  const row = (await screen.findByText('Grand Hall')).closest('tr')!
  expect(within(row).queryByRole('button')).not.toBeInTheDocument()
  expect(within(row).getByText(text)).toBeInTheDocument()
  expect(within(row).getByText('Awaiting review', { selector: '.status-badge' })).toBeInTheDocument()
})
