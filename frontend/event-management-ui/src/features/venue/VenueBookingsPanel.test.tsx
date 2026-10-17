/**
 * # Test scope and acceptance mapping — SCRUM-171 integration
 *
 * - **SCRUM-171 AC3 — request details:** the automatic-rejection case renders closure cause, full SGT closure period and operational reason; manual-null history remains readable.
 * - **Separately approved immutability/replacement rule:** rejected controls are absent, stale writes refresh history, replacement drafts survive; failed cancellation of A preserves an update draft for B. These are not AC2 closure-time assertions.
 * - **Supporting timezone regression:** naive, explicit-offset and fractional booking timestamps display/edit in SGT, not direct AC3.
 * - **Existing booking/SCRUM-30 regressions (no direct SCRUM-171 AC):** sibling CRUD, request-level capacity, validation, failed/conflicting requests, cancellation and generic feedback retain their original scope.
 *
 * ## Case/group traceability
 *
 * - `booking dates render and edit in SGT for naive and explicit UTC timestamps`: Generic booking timezone display/edit regression — UTC/naive SGT values; no direct AC3 closure-rejection detail assertion.
 * - `stale edit refreshes immutable request while retaining replacement draft`: Separate approved immutability/replacement rule — stale edit/cancel handling and retained draft; no direct closure AC.
 * - `stale cancel refreshes immutable request while retaining replacement draft`: Separate approved immutability/replacement rule — stale edit/cancel handling and retained draft; no direct closure AC.
 * - `all rejected requests are immutable and automatic rejection shows full SGT period and reason`: AC3 — rejected-request full SGT period/reason rendered; separate immutability rule and manual-null compatibility.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { fetchVenues } from './venues'
import { fetchActiveVenueHolds } from './venueHolds'
import { VenueBookingError, cancelVenueBooking, createVenueBooking, fetchVenueBookings, updateVenueBooking } from './venueBookings'
import { VenueBookingsPanel } from './VenueBookingsPanel'

vi.mock('./venues', () => ({ fetchVenues: vi.fn() }))
vi.mock('./venueHolds', () => ({ fetchActiveVenueHolds: vi.fn() }))
vi.mock('./venueBookings', async (importOriginal) => ({
  ...await importOriginal<typeof import('./venueBookings')>(),
  cancelVenueBooking: vi.fn(),
  createVenueBooking: vi.fn(),
  fetchVenueBookings: vi.fn(),
  updateVenueBooking: vi.fn(),
}))

const eventId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const coordinatorId = '11111111-1111-4111-8111-111111111111'
const venues = [
  { id: 'venue-a', name: 'Auditorium A', location: '', capacity: 500, facilities: [], accessibility: '', supportedLayouts: [], status: 'Available' },
  { id: 'venue-b', name: 'Breakout Room B', location: '', capacity: 60, facilities: [], accessibility: '', supportedLayouts: [], status: 'Available' },
]
const bookings = [
  {
    id: 'booking-a', eventId, venueId: 'venue-a', venueName: 'Auditorium A',
    requestedStartTime: '2026-10-20T09:00', requestedEndTime: '2026-10-20T12:00',
    requiredCapacity: 500, venueRequirements: 'Main stage', status: 'Approved',
    requestedBy: coordinatorId, reviewedBy: null,
  },
  {
    id: 'booking-b', eventId, venueId: 'venue-b', venueName: 'Breakout Room B',
    requestedStartTime: '2026-10-20T09:00', requestedEndTime: '2026-10-20T12:00',
    requiredCapacity: 50, venueRequirements: 'Workshop tables', status: 'Pending Review',
    requestedBy: coordinatorId, reviewedBy: null,
  },
]

const renderPanel = () => render(<VenueBookingsPanel
  eventId={eventId}
  coordinatorId={coordinatorId}
  eventStart="2026-10-20T09:00"
  eventEnd="2026-10-20T17:00"
  eventExpectedAttendance="500"
  eventVenueRequirements="Main programme space"
/>)

beforeEach(() => {
  vi.resetAllMocks()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  vi.mocked(fetchVenues).mockResolvedValue(venues)
  vi.mocked(fetchActiveVenueHolds).mockResolvedValue([])
  vi.mocked(fetchVenueBookings).mockResolvedValue(bookings)
})

test('active holds are labeled and unavailable in the venue booking selector', async () => {
  vi.mocked(fetchActiveVenueHolds).mockResolvedValue([
    { id: 'hold-a', venueId: 'venue-a', createdAt: '2026-10-19T09:00:00+08:00', expiresAt: '2026-10-21T09:00:00+08:00', heldBy: null },
  ])
  renderPanel()

  const heldVenue = await screen.findByRole('option', { name: 'Auditorium A · capacity 500 (On Hold)' })
  expect(heldVenue).toBeDisabled()
  expect(screen.getByRole('option', { name: 'Breakout Room B · capacity 60' })).toBeEnabled()

  fireEvent.change(screen.getByLabelText('Booking start *'), { target: { value: '2026-10-22T09:00' } })
  fireEvent.change(screen.getByLabelText('Booking end *'), { target: { value: '2026-10-22T12:00' } })
  expect(screen.getByRole('option', { name: 'Auditorium A · capacity 500' })).toBeEnabled()
})

test('hold lookup failure prevents submitting a booking with unknown hold status', async () => {
  vi.mocked(fetchActiveVenueHolds).mockRejectedValue(new Error('Hold service offline'))
  renderPanel()

  expect(await screen.findByRole('alert')).toHaveTextContent('Hold service offline')
  expect(screen.getByLabelText(/Venue \*/)).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Submit venue booking' })).toBeDisabled()
})

test('immutable cancellation preserves an unrelated edit and submits an update, not a replacement', async () => {
 renderPanel(); await screen.findByText('Auditorium A', { selector: 'strong' })
 fireEvent.click(screen.getAllByRole('button', { name: 'Edit booking' })[1])
 fireEvent.change(screen.getByLabelText('Venue requirements'), { target: { value: 'Keep sibling edit' } })
 vi.mocked(fetchVenueBookings).mockResolvedValue([{ ...bookings[0], status: 'Rejected' }, bookings[1]])
 vi.mocked(cancelVenueBooking).mockRejectedValue(new VenueBookingError(409, { code: 'BOOKING_IMMUTABLE', message: 'Immutable' }))
 fireEvent.click(screen.getAllByRole('button', { name: 'Cancel booking' })[0])
 await screen.findByText('Rejected', { selector: '.status-badge' })
 expect(screen.getByRole('heading', { name: 'Edit venue booking' })).toBeInTheDocument()
 expect(screen.getByRole('alert')).toHaveTextContent('This request is now read-only. Your other booking draft is unchanged.')
 expect(screen.getByLabelText('Venue requirements')).toHaveValue('Keep sibling edit')
 vi.mocked(updateVenueBooking).mockResolvedValue({ ...bookings[1], venueRequirements: 'Keep sibling edit' })
 fireEvent.click(screen.getByRole('button', { name: 'Save venue booking' }))
 await waitFor(() => expect(updateVenueBooking).toHaveBeenCalledWith('booking-b', expect.objectContaining({ venueRequirements: 'Keep sibling edit' })))
 expect(createVenueBooking).not.toHaveBeenCalled()
 expect(await screen.findByText('Breakout Room B booking updated and returned to pending review.')).toBeInTheDocument()
})

test.each([
 ['2099-01-01T09:00:00.123456', '2099-01-01T12:00:00.654321'],
 ['2099-01-01T01:00:00.123456Z', '2099-01-01T05:00:00.654321+01:00'],
])('fractional booking timestamps display and edit the same SGT period: %s', async (requestedStartTime, requestedEndTime) => {
 vi.mocked(fetchVenueBookings).mockResolvedValue([{ ...bookings[0], requestedStartTime, requestedEndTime }])
 renderPanel(); await screen.findByText('Auditorium A', { selector: 'strong' })
 expect(screen.getByText('1 Jan 2099, 09:00 SGT – 1 Jan 2099, 12:00 SGT')).toBeInTheDocument()
 fireEvent.click(screen.getByRole('button', { name: 'Edit booking' }))
 expect(screen.getByLabelText('Booking start *')).toHaveValue('2099-01-01T09:00')
 expect(screen.getByLabelText('Booking end *')).toHaveValue('2099-01-01T12:00')
})

test('booking dates render and edit in SGT for naive and explicit UTC timestamps', async () => {
 vi.mocked(fetchVenueBookings).mockResolvedValue([{ ...bookings[0], requestedStartTime: '2099-01-01T02:00:00Z', requestedEndTime: '2099-01-01T12:00:00' }])
 renderPanel(); await screen.findByText('Auditorium A', { selector: 'strong' })
 expect(screen.getByText(/1 Jan 2099, 10:00 SGT/)).toHaveTextContent('1 Jan 2099, 12:00 SGT')
 fireEvent.click(screen.getByRole('button', { name: 'Edit booking' }))
 expect(screen.getByLabelText('Booking start *')).toHaveValue('2099-01-01T10:00')
 expect(screen.getByLabelText('Booking end *')).toHaveValue('2099-01-01T12:00')
})
test.each(['edit', 'cancel'])('stale %s refreshes immutable request while retaining replacement draft', async action => {
 renderPanel(); await screen.findByText('Auditorium A', { selector: 'strong' })
 fireEvent.click(screen.getAllByRole('button', { name: 'Edit booking' })[0])
 fireEvent.change(screen.getByLabelText('Venue requirements'), { target: { value: 'Keep this draft' } })
 vi.mocked(fetchVenueBookings).mockResolvedValue([{ ...bookings[0], status: 'Rejected' }, bookings[1]])
 const error = new VenueBookingError(409, { code: 'BOOKING_IMMUTABLE', message: 'Immutable' })
 vi.mocked(updateVenueBooking).mockRejectedValue(error); vi.mocked(cancelVenueBooking).mockRejectedValue(error)
 fireEvent.click(action === 'edit' ? screen.getByRole('button', { name: 'Save venue booking' }) : screen.getAllByRole('button', { name: 'Cancel booking' })[0])
 expect(await screen.findByRole('alert')).toHaveTextContent('This request is now read-only')
 expect(await screen.findByText('Rejected', { selector: '.status-badge' })).toBeInTheDocument()
 expect(screen.getByLabelText('Venue requirements')).toHaveValue('Keep this draft')
 expect(screen.getByRole('heading', { name: 'Add venue booking' })).toBeInTheDocument()
})
test('all rejected requests are immutable and automatic rejection shows full SGT period and reason', async () => {
 vi.mocked(fetchVenueBookings).mockResolvedValue([
  { ...bookings[0], status: 'Rejected', closureRejection: { closureId: 'c', startDateTime: '2099-01-01T02:00:00Z', endDateTime: '2099-01-02T04:00:00Z', reason: '<Maintenance>\nSafety inspection', rejectedAt: '2098-12-01T02:00:00Z' } },
  { ...bookings[1], status: 'Rejected', closureRejection: null },
 ])
 renderPanel(); await screen.findByText('Auditorium A', { selector: 'strong' })
 expect(screen.queryByRole('button', { name: 'Edit booking' })).not.toBeInTheDocument()
 expect(screen.queryByRole('button', { name: 'Cancel booking' })).not.toBeInTheDocument()
 expect(screen.getAllByText('Rejected due to temporary venue closure')).toHaveLength(1)
 expect(screen.getByText(/<Maintenance>/)).toHaveTextContent('Safety inspection')
 expect(screen.getByText(/1 Jan 2099, 10:00 SGT/)).toHaveTextContent('2 Jan 2099, 12:00 SGT')
 expect(screen.getByRole('heading', { name: 'Add venue booking' })).toBeInTheDocument()
})
test('displays multiple bookings for one event as separate records', async () => {
  renderPanel()

  expect(await screen.findByText('Auditorium A', { selector: 'strong' })).toBeInTheDocument()
  expect(screen.getByText('Breakout Room B', { selector: 'strong' })).toBeInTheDocument()
  expect(screen.getByText('500', { selector: 'dd' })).toBeInTheDocument()
  expect(screen.getByText('50', { selector: 'dd' })).toBeInTheDocument()
  expect(fetchVenueBookings).toHaveBeenCalledWith(eventId, coordinatorId)
})

test('submits booking-level capacity instead of the event total attendance', async () => {
  vi.mocked(createVenueBooking).mockResolvedValue({
    ...bookings[1], id: 'booking-c', venueName: '', requiredCapacity: 50,
  })
  renderPanel()
  await screen.findByText('Auditorium A', { selector: 'strong' })

  fireEvent.change(screen.getByLabelText(/Venue \*/), { target: { value: 'venue-b' } })
  fireEvent.change(screen.getByLabelText('Expected attendance / required capacity *'), { target: { value: '50' } })
  fireEvent.change(screen.getByLabelText('Venue requirements'), { target: { value: 'Breakout tables' } })
  fireEvent.click(screen.getByRole('button', { name: 'Submit venue booking' }))

  await waitFor(() => expect(createVenueBooking).toHaveBeenCalledWith({
    eventId,
    venueId: 'venue-b',
    coordinatorId,
    requestedStartTime: '2026-10-20T09:00',
    requestedEndTime: '2026-10-20T17:00',
    requiredCapacity: 50,
    venueRequirements: 'Breakout tables',
  }))
  expect(await screen.findByText('Breakout Room B booking request submitted. Status: Pending Review.')).toBeInTheDocument()
})

test('one failed request leaves existing bookings intact and permits another submission', async () => {
  vi.mocked(createVenueBooking)
    .mockRejectedValueOnce(new Error('Breakout Room B is already booked for that time.'))
    .mockResolvedValueOnce({ ...bookings[1], id: 'booking-c', venueName: '' })
  renderPanel()
  await screen.findByText('Auditorium A', { selector: 'strong' })

  fireEvent.change(screen.getByLabelText(/Venue \*/), { target: { value: 'venue-b' } })
  fireEvent.change(screen.getByLabelText('Expected attendance / required capacity *'), { target: { value: '50' } })
  fireEvent.click(screen.getByRole('button', { name: 'Submit venue booking' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('already booked')
  expect(screen.getByText('Auditorium A', { selector: 'strong' })).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'Submit venue booking' }))
  expect(await screen.findByText('Breakout Room B booking request submitted. Status: Pending Review.')).toBeInTheDocument()
  expect(createVenueBooking).toHaveBeenCalledTimes(2)
})

test('editing one booking replaces only that booking and resets it to pending review', async () => {
  vi.mocked(updateVenueBooking).mockResolvedValue({
    ...bookings[0],
    requiredCapacity: 450,
    venueRequirements: 'Revised main stage',
    status: 'Pending Review',
    reviewedBy: null,
  })
  renderPanel()
  await screen.findByText('Auditorium A', { selector: 'strong' })

  fireEvent.click(screen.getAllByRole('button', { name: 'Edit booking' })[0])
  expect(screen.getByRole('heading', { name: 'Edit venue booking' })).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Expected attendance / required capacity *'), { target: { value: '450' } })
  fireEvent.change(screen.getByLabelText('Venue requirements'), { target: { value: 'Revised main stage' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save venue booking' }))

  await waitFor(() => expect(updateVenueBooking).toHaveBeenCalledWith('booking-a', {
    eventId,
    venueId: 'venue-a',
    coordinatorId,
    requestedStartTime: '2026-10-20T09:00',
    requestedEndTime: '2026-10-20T12:00',
    requiredCapacity: 450,
    venueRequirements: 'Revised main stage',
  }))
  expect(await screen.findByText('Auditorium A booking updated and returned to pending review.')).toBeInTheDocument()
  expect(screen.getByText('Breakout Room B', { selector: 'strong' })).toBeInTheDocument()
  expect(screen.getByText('450', { selector: 'dd' })).toBeInTheDocument()
  expect(screen.getByText('50', { selector: 'dd' })).toBeInTheDocument()
})

test('cancelling one booking retains it as cancelled and leaves its sibling unchanged', async () => {
  vi.mocked(cancelVenueBooking).mockResolvedValue({ ...bookings[0], status: 'Cancelled' })
  renderPanel()
  await screen.findByText('Auditorium A', { selector: 'strong' })

  fireEvent.click(screen.getAllByRole('button', { name: 'Cancel booking' })[0])

  await waitFor(() => expect(cancelVenueBooking).toHaveBeenCalledWith('booking-a', eventId, coordinatorId))
  expect(await screen.findByText('Auditorium A booking cancelled. Other venue bookings were not changed.')).toBeInTheDocument()
  expect(screen.getByText('Cancelled')).toBeInTheDocument()
  expect(screen.getByText('Pending Review')).toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: 'Edit booking' })).toHaveLength(1)
})

test('SCRUM-30 edit conflict preserves original records and draft; discard removes stale feedback', async () => {
  vi.mocked(updateVenueBooking).mockRejectedValue(new VenueBookingError(409, { code: 'VENUE_UNAVAILABLE', conflictTypes: ['VENUE_CLOSURE'] }))
  renderPanel()
  await screen.findByText('Auditorium A', { selector: 'strong' })
  fireEvent.click(screen.getAllByRole('button', { name: 'Edit booking' })[0])
  fireEvent.change(screen.getByLabelText('Expected attendance / required capacity *'), { target: { value: '450' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save venue booking' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Request not submitted. The venue is closed during this time.')
  expect(screen.getByText('Approved')).toBeInTheDocument()
  expect(screen.getByText('500', { selector: 'dd' })).toBeInTheDocument()
  expect(screen.getByLabelText('Expected attendance / required capacity *')).toHaveValue(450)
  fireEvent.click(screen.getByRole('button', { name: 'Discard changes' }))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test.each([
  ['Booking start *', ''], ['Booking end *', ''],
  ['Expected attendance / required capacity *', '0'],
  ['Expected attendance / required capacity *', '1.5'],
])('invalid %s never sends a request', async (label, value) => {
  renderPanel()
  await screen.findByText('Auditorium A', { selector: 'strong' })
  fireEvent.change(screen.getByLabelText(/Venue \*/), { target: { value: 'venue-a' } })
  fireEvent.change(screen.getByLabelText(label), { target: { value } })
  fireEvent.submit(screen.getByRole('button', { name: 'Submit venue booking' }).closest('form')!)
  expect(await screen.findByRole('alert')).toHaveTextContent('Select a venue and provide valid dates and a positive required capacity.')
  expect(createVenueBooking).not.toHaveBeenCalled()
})

test('missing venue and reversed interval never send a request', async () => {
  renderPanel()
  await screen.findByText('Auditorium A', { selector: 'strong' })
  const form = screen.getByRole('button', { name: 'Submit venue booking' }).closest('form')!
  fireEvent.submit(form)
  expect(await screen.findByRole('alert')).toHaveTextContent('Select a venue')
  fireEvent.change(screen.getByLabelText(/Venue \*/), { target: { value: 'venue-a' } })
  fireEvent.change(screen.getByLabelText('Booking end *'), { target: { value: '2026-10-20T08:00' } })
  fireEvent.submit(form)
  expect(await screen.findByRole('alert')).toHaveTextContent('Booking end date and time must be after the start.')
  expect(createVenueBooking).not.toHaveBeenCalled()
})

test.each([new Error('Service offline'), null])('load errors remain accessible and prevent booking without a catalogue: %j', async (error) => {
  vi.mocked(fetchVenueBookings).mockRejectedValue(error)
  vi.mocked(fetchVenues).mockRejectedValue(error)
  renderPanel()
  expect(await screen.findAllByRole('alert')).toHaveLength(2)
  expect(screen.getByRole('button', { name: 'Submit venue booking' })).toBeDisabled()
})

test.each([new Error('Cancellation failed'), null])('failed cancellation preserves records: %j', async (error) => {
  vi.mocked(cancelVenueBooking).mockRejectedValue(error)
  renderPanel()
  await screen.findByText('Auditorium A', { selector: 'strong' })
  fireEvent.click(screen.getAllByRole('button', { name: 'Cancel booking' })[0])
  expect(await screen.findByRole('alert')).toHaveTextContent(error?.message || 'Unable to cancel this venue booking.')
  expect(screen.getByText('Approved')).toBeInTheDocument()
})

test('cancelling the edited record exits editing without removing its sibling', async () => {
  vi.mocked(cancelVenueBooking).mockResolvedValue({ ...bookings[0], status: 'Cancelled' })
  renderPanel()
  await screen.findByText('Auditorium A', { selector: 'strong' })
  fireEvent.click(screen.getAllByRole('button', { name: 'Edit booking' })[0])
  fireEvent.click(screen.getAllByRole('button', { name: 'Cancel booking' })[0])
  await screen.findByText('Cancelled')
  expect(screen.getByRole('heading', { name: 'Add venue booking' })).toBeInTheDocument()
  expect(screen.getByText('Breakout Room B', { selector: 'strong' })).toBeInTheDocument()
})

test('non-Error submit failures still show generic feedback', async () => {
  vi.mocked(createVenueBooking).mockRejectedValue(null)
  renderPanel()
  await screen.findByText('Auditorium A', { selector: 'strong' })
  fireEvent.change(screen.getByLabelText(/Venue \*/), { target: { value: 'venue-a' } })
  fireEvent.click(screen.getByRole('button', { name: 'Submit venue booking' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to save this venue booking.')
})

test('declining cancellation leaves the selected booking unchanged', async () => {
  vi.mocked(window.confirm).mockReturnValue(false)
  renderPanel()
  await screen.findByText('Auditorium A', { selector: 'strong' })

  fireEvent.click(screen.getAllByRole('button', { name: 'Cancel booking' })[0])

  expect(cancelVenueBooking).not.toHaveBeenCalled()
  expect(screen.getByText('Approved')).toBeInTheDocument()
})
