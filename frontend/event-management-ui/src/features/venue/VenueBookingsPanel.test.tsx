import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { fetchVenues } from './venues'
import { cancelVenueBooking, createVenueBooking, fetchVenueBookings, updateVenueBooking } from './venueBookings'
import { VenueBookingsPanel } from './VenueBookingsPanel'

vi.mock('./venues', () => ({ fetchVenues: vi.fn() }))
vi.mock('./venueBookings', () => ({
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
  expect(await screen.findByText('Breakout Room B booking request submitted independently.')).toBeInTheDocument()
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
  expect(await screen.findByText('Breakout Room B booking request submitted independently.')).toBeInTheDocument()
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

test('declining cancellation leaves the selected booking unchanged', async () => {
  vi.mocked(window.confirm).mockReturnValue(false)
  renderPanel()
  await screen.findByText('Auditorium A', { selector: 'strong' })

  fireEvent.click(screen.getAllByRole('button', { name: 'Cancel booking' })[0])

  expect(cancelVenueBooking).not.toHaveBeenCalled()
  expect(screen.getByText('Approved')).toBeInTheDocument()
})
