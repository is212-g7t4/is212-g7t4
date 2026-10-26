import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { VenueRequestsPage } from './VenueRequestsPage'
import { VenueBookingError, fetchVenueRequestDetail, fetchVenueRequests, reviewVenueRequest } from '../features/venue/venueBookings'
import type { VenueBooking, VenueRequestDetail } from '../features/venue/venueBookings'
import type { User } from '../types'

vi.mock('../features/venue/venueBookings', async (original) => ({
  ...await original<typeof import('../features/venue/venueBookings')>(),
  fetchVenueRequests: vi.fn(), reviewVenueRequest: vi.fn(), fetchVenueRequestDetail: vi.fn(),
}))
const user: User = { id: 'staff', username: 'Vera', role: 'Venue Staff', email: '', organization: '' }
const booking: VenueBooking = { id: 'b1', eventId: 'e1', venueId: 'v1', venueName: 'Grand Hall', requestedStartTime: '2026-11-01T10:00:00',
  requestedEndTime: '2026-11-01T12:00:00', requiredCapacity: 80, venueRequirements: 'Step-free route', status: 'Pending Review',
  requestedBy: 'coordinator', reviewedBy: null, safetyFeedback: { reason: 'Exit blocked.', requestedChanges: ['Move the stage.'] } }
const event = { eventId: 'e1', eventName: 'Community Fair', eventStatus: 'Safety Changes Requested', coordinatorId: 'coordinator', bookings: [booking] }
const detail = (overrides: Partial<VenueRequestDetail> = {}): VenueRequestDetail => ({
  booking: { ...booking, awaitingReview: true, occupiedFrom: '2026-11-01T09:30:00', occupiedTo: '2026-11-01T12:45:00' },
  event: { id: 'e1', eventName: 'Community Fair', status: 'Safety Changes Requested', coordinatorId: 'coordinator',
    preferredStartDate: '2026-11-01T09:00:00', preferredEndDate: '2026-11-01T17:00:00', expectedAttendance: '80',
    venueRequirements: 'Stage', accessibilityNeeds: null },
  venue: { id: 'v1', name: 'Grand Hall', capacity: 100, status: 'Available', setupTimeMinutes: 30, turnaroundTimeMinutes: 45 },
  canDecide: true, decisionBlockedReason: null, ...overrides,
})
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(fetchVenueRequests).mockResolvedValue([event])
  vi.mocked(fetchVenueRequestDetail).mockResolvedValue(detail())
  vi.mocked(reviewVenueRequest).mockResolvedValue({ ...booking, status: 'Approved', reviewedBy: user.id })
})
const show = () => render(<VenueRequestsPage role="Venue Staff" user={user} resolveUserName={() => 'Priya'} />)
const openReview = async (index = 0) => {
  fireEvent.click((await screen.findAllByRole('button', { name: 'Review' }))[index])
  return screen.findByRole('dialog')
}

test('shows pending bookings, safety reason and a staff review action', async () => {
  show()
  expect(await screen.findByText('Grand Hall')).toBeInTheDocument()
  expect(screen.getByText('Move the stage.')).toBeInTheDocument()
  expect(screen.getByText('Reason: Exit blocked.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Review' })).toBeEnabled()
  expect(screen.getAllByRole('columnheader').at(-1)).toHaveTextContent('Safety change reason')
})

// Safety revision AC2 (staff UI): reopened venue requests expose and submit a new approval/rejection decision.
test('staff can save Approved on a safety revision booking', async () => {
  show()
  fireEvent.click(within(await openReview()).getByRole('button', { name: 'Approve' }))
  await waitFor(() => expect(reviewVenueRequest).toHaveBeenCalledWith('b1', 'Approved', user, undefined))
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Review' })).not.toBeInTheDocument())
  expect(screen.getByText('Approved', { selector: '.status-badge' })).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent('Venue request approved.')
})

test('staff can save Rejected on a safety revision booking with a reason', async () => {
  vi.mocked(reviewVenueRequest).mockResolvedValue({ ...booking, status: 'Rejected', rejectionReason: 'Too small.' })
  show()
  fireEvent.click(within(await openReview()).getByRole('button', { name: 'Reject' }))
  fireEvent.change(await screen.findByLabelText(/Reason for rejection/), { target: { value: '  Too small.  ' } })
  fireEvent.click(screen.getByRole('button', { name: 'Confirm rejection' }))
  await waitFor(() => expect(reviewVenueRequest).toHaveBeenCalledWith('b1', 'Rejected', user, 'Too small.'))
  expect(await screen.findByText('Rejected', { selector: '.status-badge' })).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent('Venue request rejected.')
})

// Safety revision AC4 (UI only): an unaffected Approved booking is not offered another review action.
test('already reviewed bookings can be viewed but not reviewed again', async () => {
  vi.mocked(fetchVenueRequests).mockResolvedValue([{ ...event, bookings: [{ ...booking, status: 'Approved', safetyFeedback: null }] }])
  show()
  const row = (await screen.findByText('Grand Hall')).closest('tr')!
  expect(within(row).queryByRole('button', { name: 'Review' })).not.toBeInTheDocument()
  expect(within(row).getByRole('button', { name: 'View' })).toBeInTheDocument()
  expect(within(row).getByText('Reviewed')).toBeInTheDocument()
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
  vi.mocked(reviewVenueRequest).mockRejectedValue(new VenueBookingError(409, { code: 'VENUE_UNAVAILABLE', conflictTypes: ['APPROVED_BOOKING'] }))
  show()
  const dialog = await openReview()
  fireEvent.click(within(dialog).getByRole('button', { name: 'Approve' }))
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('Not approved. An approved booking overlaps this time.')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
  expect(screen.getByText('Grand Hall')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Review' })).toBeInTheDocument()
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
  fireEvent.click(within(await openReview()).getByRole('button', { name: 'Approve' }))
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
  expect(within(row).queryByRole('button', { name: 'Review' })).not.toBeInTheDocument()
  expect(within(row).getByText(text)).toBeInTheDocument()
  expect(within(row).getByText('Awaiting review', { selector: '.status-badge' })).toBeInTheDocument()
})

// SCRUM-29 AC5: a decided request is no longer presented as awaiting a decision.
test('SCRUM-29 AC5: "Review" is offered only on awaiting rows; decided rows show their outcome', async () => {
  vi.mocked(fetchVenueRequests).mockResolvedValue([{ ...event, eventStatus: 'Under Review', bookings: [
    booking,
    { ...booking, id: 'ok', venueName: 'Annex', status: 'Approved', reviewedAt: '2026-10-02T01:00:00+00:00' },
    { ...booking, id: 'no', venueName: 'Studio', status: 'Rejected', reviewedAt: '2026-10-03T01:00:00+00:00', rejectionReason: 'Too small for the stage.' },
  ] }])
  show()
  const rows = (name: string) => screen.getByText(name).closest('tr')!
  await screen.findByText('Grand Hall')
  expect(within(rows('Grand Hall')).getByRole('button', { name: 'Review' })).toBeInTheDocument()
  expect(within(rows('Annex')).queryByRole('button', { name: 'Review' })).not.toBeInTheDocument()
  expect(within(rows('Annex')).getByText('Approved on 2 Oct 2026, 9:00 am')).toBeInTheDocument()
  expect(within(rows('Studio')).getByText('Rejected on 3 Oct 2026, 9:00 am')).toBeInTheDocument()
  expect(within(rows('Studio')).getByTitle('Too small for the stage.')).toBeInTheDocument()
})

test('SCRUM-29 AC5: after a decision the row shows "Approved on" and drops out of the awaiting filter', async () => {
  vi.mocked(fetchVenueRequests).mockResolvedValue([{ ...event, bookings: [booking, { ...booking, id: 'b2', venueName: 'Studio' }] }])
  vi.mocked(reviewVenueRequest).mockResolvedValue({ ...booking, status: 'Approved', reviewedAt: '2026-10-02T01:00:00+00:00' })
  show()
  await screen.findByText('Grand Hall')
  fireEvent.change(screen.getByLabelText('Filter by status'), { target: { value: 'Pending' } })
  fireEvent.click(within(await openReview()).getByRole('button', { name: 'Approve' }))
  await waitFor(() => expect(screen.queryByText('Grand Hall')).not.toBeInTheDocument())
  expect(screen.getByText('Studio')).toBeInTheDocument()
})

test('SCRUM-29 AC5: the outcome text appears on the row decided under "All requests"', async () => {
  vi.mocked(reviewVenueRequest).mockResolvedValue({ ...booking, status: 'Rejected', reviewedAt: '2026-10-02T01:00:00+00:00', rejectionReason: 'No.' })
  show()
  fireEvent.click(within(await openReview()).getByRole('button', { name: 'Reject' }))
  fireEvent.change(await screen.findByLabelText(/Reason for rejection/), { target: { value: 'No.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Confirm rejection' }))
  expect(await screen.findByText('Rejected on 2 Oct 2026, 9:00 am')).toBeInTheDocument()
  expect(screen.getByText('Grand Hall')).toBeInTheDocument()
})

test('SCRUM-29 AC5: a request someone else decided first reloads the list with the server message', async () => {
  vi.mocked(reviewVenueRequest).mockRejectedValue(new VenueBookingError(409, {
    code: 'BOOKING_ALREADY_DECIDED', message: 'This venue request is not awaiting staff review.' }))
  show()
  fireEvent.click(within(await openReview()).getByRole('button', { name: 'Approve' }))
  await waitFor(() => expect(fetchVenueRequests).toHaveBeenCalledTimes(2))
  await screen.findByText('Grand Hall')
  expect(screen.getByRole('status')).toHaveTextContent('This venue request is not awaiting staff review. The list has been refreshed.')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})
