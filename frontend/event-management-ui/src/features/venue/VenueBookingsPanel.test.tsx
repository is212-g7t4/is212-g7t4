import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { fetchVenues } from './venues'
import { VenueBookingError, cancelVenueBooking, createVenueBooking, fetchVenueBookings, updateVenueBooking } from './venueBookings'
import { VenueBookingsPanel } from './VenueBookingsPanel'

vi.mock('./venues', () => ({ fetchVenues: vi.fn() }))
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
  vi.mocked(fetchVenueBookings).mockResolvedValue(bookings)
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
