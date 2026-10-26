/**
 * SCRUM-29 Venue Booking Review and Decision: the Venue Staff review dialog.
 * AC1 open the request and see the event timing and requirements; AC2/AC3
 * approve or reject; AC4 a reason is needed to reject; AC5 a decided request
 * opens read-only. All API calls are mocked.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { VenueRequestReviewDialog } from './VenueRequestReviewDialog'
import { VenueBookingError, fetchVenueRequestDetail, reviewVenueRequest } from './venueBookings'
import type { VenueRequestDetail } from './venueBookings'

vi.mock('./venueBookings', async (original) => ({
  ...await original<typeof import('./venueBookings')>(),
  fetchVenueRequestDetail: vi.fn(), reviewVenueRequest: vi.fn(),
}))

const user = { id: 'staff', role: 'Venue Staff' as const }
const detail = (overrides: Partial<VenueRequestDetail> = {}, booking: Partial<VenueRequestDetail['booking']> = {}): VenueRequestDetail => ({
  booking: { id: 'b1', eventId: 'e1', venueId: 'v1', venueName: 'Grand Hall', requestedStartTime: '2030-03-01T10:00:00',
    requestedEndTime: '2030-03-01T12:00:00', requiredCapacity: 120, venueRequirements: 'Two microphones', status: 'Pending Review',
    requestedBy: 'coord', reviewedBy: null, requestedAt: '2030-02-01T02:00:00+00:00', reviewedAt: null, rejectionReason: null,
    awaitingReview: true, occupiedFrom: '2030-03-01T09:30:00', occupiedTo: '2030-03-01T12:45:00', ...booking },
  event: { id: 'e1', eventName: 'Spring Fair', status: 'Under Review', coordinatorId: 'coord',
    preferredStartDate: '2030-03-01T09:00:00', preferredEndDate: '2030-03-01T17:00:00', expectedAttendance: '120',
    venueRequirements: 'Stage', accessibilityNeeds: 'Wheelchair ramp' },
  venue: { id: 'v1', name: 'Grand Hall', capacity: 150, status: 'Available', setupTimeMinutes: 30, turnaroundTimeMinutes: 45 },
  canDecide: true, decisionBlockedReason: null, ...overrides,
})

const onClose = vi.fn()
const onDecided = vi.fn()
const onStale = vi.fn()
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(fetchVenueRequestDetail).mockResolvedValue(detail())
})
const show = async () => {
  render(<VenueRequestReviewDialog bookingId="b1" user={user} onClose={onClose} onDecided={onDecided} onStale={onStale} />)
  return within(await screen.findByRole('dialog', { name: 'Grand Hall for Spring Fair' }))
}

test('AC1: opening a request shows the event timing, attendance and requirements beside the booking', async () => {
  const dialog = await show()
  expect(fetchVenueRequestDetail).toHaveBeenCalledWith('b1', user)
  expect(dialog.getByText('Fri, 1 Mar · 9:00 am – 5:00 pm')).toBeInTheDocument()
  expect(dialog.getByText('Stage')).toBeInTheDocument()
  expect(dialog.getByText('Wheelchair ramp')).toBeInTheDocument()
  expect(dialog.getByText('Fri, 1 Mar · 10:00 am – 12:00 pm')).toBeInTheDocument()
  expect(dialog.getByText('Fri, 1 Mar · 9:30 am – 12:45 pm')).toBeInTheDocument()
  expect(dialog.getByText(/includes 30 min setup, 45 min turnaround/)).toBeInTheDocument()
  expect(dialog.getByText('120 of 150')).toBeInTheDocument()
  expect(dialog.getByText('Two microphones')).toBeInTheDocument()
  expect(dialog.getByText('1 Feb 2030, 10:00 am')).toBeInTheDocument()
  expect(dialog.getByText('Awaiting review', { selector: '.status-badge' })).toBeInTheDocument()
})

test('AC1: unset event details read as not specified', async () => {
  vi.mocked(fetchVenueRequestDetail).mockResolvedValue({ ...detail(), event: { ...detail().event,
    preferredStartDate: null, expectedAttendance: null, venueRequirements: null, accessibilityNeeds: null, status: null },
  venue: { ...detail().venue, capacity: null } })
  const dialog = await show()
  expect(dialog.getByText('Event dates not set')).toBeInTheDocument()
  expect(dialog.getByText('Not specified')).toBeInTheDocument()
  expect(dialog.getAllByText('None specified')).toHaveLength(2)
  expect(dialog.getByText('120 of unknown')).toBeInTheDocument()
})

test('AC1: a load failure is shown and the dialog can be closed', async () => {
  vi.mocked(fetchVenueRequestDetail).mockRejectedValue(new Error('Unable to load venue bookings.'))
  render(<VenueRequestReviewDialog bookingId="b1" user={user} onClose={onClose} onDecided={onDecided} onStale={onStale} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load venue bookings.')
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  expect(onClose).toHaveBeenCalled()
})

test('AC1: a non-Error load failure still explains itself', async () => {
  vi.mocked(fetchVenueRequestDetail).mockRejectedValue('offline')
  render(<VenueRequestReviewDialog bookingId="b1" user={user} onClose={onClose} onDecided={onDecided} onStale={onStale} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load this venue request.')
})

test('AC2: Approve records the decision and hands the booking back', async () => {
  vi.mocked(reviewVenueRequest).mockResolvedValue({ ...detail().booking, status: 'Approved' })
  const dialog = await show()
  fireEvent.click(dialog.getByRole('button', { name: 'Approve' }))
  await waitFor(() => expect(onDecided).toHaveBeenCalledWith(expect.objectContaining({ status: 'Approved' }), 'Venue request approved.'))
  expect(reviewVenueRequest).toHaveBeenCalledWith('b1', 'Approved', user, undefined)
})

test('AC3/AC4: Reject asks for a reason, keeps Confirm disabled while blank, and sends it trimmed', async () => {
  vi.mocked(reviewVenueRequest).mockResolvedValue({ ...detail().booking, status: 'Rejected' })
  const dialog = await show()
  fireEvent.click(dialog.getByRole('button', { name: 'Reject' }))
  const reject = within(await screen.findByRole('dialog', { name: 'Reject venue request?' }))
  expect(reject.getByText('Grand Hall for Spring Fair')).toBeInTheDocument()
  const confirm = reject.getByRole('button', { name: 'Confirm rejection' })
  expect(confirm).toBeDisabled()
  fireEvent.change(reject.getByLabelText(/Reason for rejection/), { target: { value: '   ' } })
  expect(confirm).toBeDisabled()
  expect(reject.getByLabelText(/Reason for rejection/)).toHaveAttribute('maxLength', '500')
  fireEvent.change(reject.getByLabelText(/Reason for rejection/), { target: { value: '  Hall is too small.  ' } })
  fireEvent.click(confirm)
  await waitFor(() => expect(reviewVenueRequest).toHaveBeenCalledWith('b1', 'Rejected', user, 'Hall is too small.'))
  expect(onDecided).toHaveBeenCalledWith(expect.objectContaining({ status: 'Rejected' }), 'Venue request rejected.')
})

test('AC4: cancelling the reason returns to the review without deciding', async () => {
  const dialog = await show()
  fireEvent.click(dialog.getByRole('button', { name: 'Reject' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
  expect(await screen.findByRole('dialog', { name: 'Grand Hall for Spring Fair' })).toBeInTheDocument()
  expect(reviewVenueRequest).not.toHaveBeenCalled()
})

test('AC4: a failed rejection returns to the review with the error and keeps the reason', async () => {
  vi.mocked(reviewVenueRequest).mockRejectedValue(new VenueBookingError(400, { message: 'A reason is required to reject a venue request.', code: 'REJECTION_REASON_REQUIRED' }))
  const dialog = await show()
  fireEvent.click(dialog.getByRole('button', { name: 'Reject' }))
  fireEvent.change(await screen.findByLabelText(/Reason for rejection/), { target: { value: 'Too small' } })
  fireEvent.click(screen.getByRole('button', { name: 'Confirm rejection' }))
  const review = within(await screen.findByRole('dialog', { name: 'Grand Hall for Spring Fair' }))
  expect(review.getByRole('alert')).toHaveTextContent('A reason is required to reject a venue request.')
  fireEvent.click(review.getByRole('button', { name: 'Reject' }))
  expect(await screen.findByLabelText(/Reason for rejection/)).toHaveValue('Too small')
})

test('AC2: an approval conflict explains what overlaps, using the shared conflict wording', async () => {
  vi.mocked(reviewVenueRequest).mockRejectedValue(new VenueBookingError(409, { code: 'VENUE_UNAVAILABLE', conflictTypes: ['TENTATIVE_HOLD', 'VENUE_CLOSURE'] }))
  const dialog = await show()
  fireEvent.click(dialog.getByRole('button', { name: 'Approve' }))
  expect(await dialog.findByRole('alert')).toHaveTextContent(
    'Not approved. An active tentative hold overlaps this time. The venue is closed during this time.')
  expect(onDecided).not.toHaveBeenCalled()
})

test('AC2: an untyped conflict falls back to a generic explanation', async () => {
  vi.mocked(reviewVenueRequest).mockRejectedValue(new VenueBookingError(409, { code: 'VENUE_UNAVAILABLE' }))
  const dialog = await show()
  fireEvent.click(dialog.getByRole('button', { name: 'Approve' }))
  expect(await dialog.findByRole('alert')).toHaveTextContent('Not approved. The venue is unavailable for this time.')
})

test.each(['BOOKING_ALREADY_DECIDED', 'EVENT_NOT_REVIEWABLE'])('AC5: a %s refusal asks the page to reload', async (code) => {
  vi.mocked(reviewVenueRequest).mockRejectedValue(new VenueBookingError(409, { code, message: 'This venue request is not awaiting staff review.' }))
  const dialog = await show()
  fireEvent.click(dialog.getByRole('button', { name: 'Approve' }))
  await waitFor(() => expect(onStale).toHaveBeenCalledWith('This venue request is not awaiting staff review.'))
})

test.each([[new Error('Network down.'), 'Network down.'], ['boom', 'Unable to record this decision.']])(
  'a failed decision shows its message (%s)', async (failure, text) => {
    vi.mocked(reviewVenueRequest).mockRejectedValue(failure)
    const dialog = await show()
    fireEvent.click(dialog.getByRole('button', { name: 'Approve' }))
    expect(await dialog.findByRole('alert')).toHaveTextContent(text)
  })

test('AC5: a decided request opens read-only with its outcome and reason', async () => {
  vi.mocked(fetchVenueRequestDetail).mockResolvedValue(detail(
    { canDecide: false, decisionBlockedReason: 'Already decided' },
    { status: 'Rejected', awaitingReview: false, reviewedAt: '2030-02-02T01:00:00+00:00', rejectionReason: 'Hall is too small.', requestedAt: null },
  ))
  const dialog = await show()
  expect(dialog.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
  expect(dialog.queryByRole('button', { name: 'Reject' })).not.toBeInTheDocument()
  expect(dialog.getByText('Already decided')).toBeInTheDocument()
  expect(dialog.getByText('Rejected on 2 Feb 2030, 9:00 am')).toBeInTheDocument()
  expect(dialog.getByText('Hall is too small.')).toBeInTheDocument()
  expect(dialog.queryByText('Submitted')).not.toBeInTheDocument()
})

test('AC5: an approved request shows when it was approved', async () => {
  vi.mocked(fetchVenueRequestDetail).mockResolvedValue(detail(
    { canDecide: false, decisionBlockedReason: 'Already decided' },
    { status: 'Approved', awaitingReview: false, reviewedAt: '2030-02-02T01:00:00+00:00', occupiedFrom: null },
  ))
  const dialog = await show()
  expect(dialog.getByText('Approved on 2 Feb 2030, 9:00 am')).toBeInTheDocument()
  expect(dialog.getByText('Unknown')).toBeInTheDocument()
})

test('Escape closes the review unless a decision is being saved', async () => {
  let finish: (value: never) => void = () => {}
  vi.mocked(reviewVenueRequest).mockReturnValue(new Promise((resolve) => { finish = resolve }))
  await show()
  const element = screen.getByRole('dialog')
  fireEvent(element, new Event('cancel', { cancelable: true }))
  expect(onClose).toHaveBeenCalledTimes(1)
  fireEvent.click(within(element).getByRole('button', { name: 'Approve' }))
  expect(await within(element).findByRole('button', { name: 'Approving...' })).toBeDisabled()
  fireEvent(element, new Event('cancel', { cancelable: true }))
  expect(onClose).toHaveBeenCalledTimes(1)
  finish(detail().booking as never)
})

test('an unparseable timestamp is shown as sent', async () => {
  vi.mocked(fetchVenueRequestDetail).mockResolvedValue(detail({}, { requestedAt: 'yesterday' }))
  const dialog = await show()
  expect(dialog.getByText('yesterday')).toBeInTheDocument()
})
