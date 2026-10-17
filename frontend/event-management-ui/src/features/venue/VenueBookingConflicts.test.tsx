import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { VenueBookingsPanel } from './VenueBookingsPanel'

function setup(body: unknown, status = 409) {
  const fetcher = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    if (init?.method) return new Response(JSON.stringify(body), { status })
    if (url.includes('/venue-holds')) return new Response(JSON.stringify({ holds: [] }))
    return new Response(JSON.stringify(url.includes('/venues') ? { venues: [{ id: 'v', name: 'Hall', status: 'Available', capacity: 100 }] } : { bookings: [] }))
  })
  vi.stubGlobal('fetch', fetcher)
  render(<VenueBookingsPanel eventId="event" coordinatorId="coordinator" eventStart="2026-12-01T09:00" eventEnd="2026-12-01T10:00" eventExpectedAttendance="10" eventVenueRequirements="Stage" />)
  return fetcher
}
async function submit() {
  await screen.findByText('No venue booking requests yet.')
  fireEvent.change(screen.getByLabelText(/Venue \*/), { target: { value: 'v' } })
  fireEvent.click(screen.getByRole('button', { name: 'Submit venue booking' }))
}
afterEach(() => vi.unstubAllGlobals())
test('SCRUM-30 a delayed conflict cannot describe a newly edited time', async () => {
  const fetcher = setup({})
  await screen.findByText('No venue booking requests yet.')
  let finish!: (value: Response) => void
  fetcher.mockImplementationOnce(() => new Promise<Response>((resolve) => { finish = resolve }))
  await submit()
  fireEvent.change(screen.getByLabelText('Booking start *'), { target: { value: '2026-12-01T08:00' } })
  await act(async () => finish(new Response(JSON.stringify({ code: 'VENUE_UNAVAILABLE', conflictTypes: ['APPROVED_BOOKING'] }), { status: 409 })))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Booking start *')).toHaveValue('2026-12-01T08:00')
  expect(screen.getByRole('button', { name: 'Submit venue booking' })).toBeEnabled()
})
test.each([
  [409, { message: 'Legacy booking conflict' }, 'Legacy booking conflict'],
  [403, { message: 'Not assigned' }, 'Not assigned'],
  [422, { message: 'Capacity exceeded' }, 'Capacity exceeded'],
  [503, { code: 'VENUE_UNAVAILABLE', conflictTypes: ['VENUE_CLOSURE'], message: 'Service unavailable' }, 'Service unavailable'],
  [500, null, 'Unable to complete the venue booking request.'],
])('SCRUM-30 non-contract failure %s is not a false availability result', async (status, body, message) => {
  setup(body, status)
  await submit()
  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent(message)
  expect(alert).not.toHaveTextContent('Request not submitted')
  expect(alert).not.toHaveTextContent('Choose another venue')
})
test('SCRUM-30 pending submission disables duplicate clicks and rejects repeated form submission', async () => {
  const fetcher = setup({})
  await screen.findByText('No venue booking requests yet.')
  let finish!: (value: Response) => void
  fetcher.mockImplementationOnce(() => new Promise<Response>((resolve) => { finish = resolve }))
  await submit()
  const button = screen.getByRole('button', { name: 'Saving…' })
  expect(button).toBeDisabled()
  fireEvent.click(button)
  fireEvent.submit(button.closest('form')!)
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  await act(async () => finish(new Response(JSON.stringify({ code: 'VENUE_UNAVAILABLE', conflictTypes: ['APPROVED_BOOKING'] }), { status: 409 })))
  expect(await screen.findByRole('alert')).toHaveTextContent('Request not submitted')
  expect(screen.getByRole('button', { name: 'Submit venue booking' })).toBeEnabled()
})
test('SCRUM-30 choosing another venue clears stale conflict', async () => {
  setup({ code: 'VENUE_UNAVAILABLE', conflictTypes: ['APPROVED_BOOKING'] })
  await submit()
  await screen.findByRole('alert')
  fireEvent.change(screen.getByLabelText(/Venue \*/), { target: { value: '' } })
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})
test('SCRUM-30 lost response does not assert rejection or availability and advises checking before retry', async () => {
  const fetcher = setup({})
  await screen.findByText('No venue booking requests yet.')
  fetcher.mockRejectedValueOnce(new TypeError('Failed to fetch'))
  await submit()
  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent('Unable to confirm whether the booking request was saved. Check existing bookings before trying again.')
  expect(alert).not.toHaveTextContent('Request not submitted')
})
test('SCRUM-30 successful submission explicitly remains Pending Review, not approval', async () => {
  setup({ id: 'new', venueId: 'v', requestedStartTime: '2026-12-01T09:00', requestedEndTime: '2026-12-01T10:00', requiredCapacity: 10, venueRequirements: 'Stage', status: 'Pending Review' }, 201)
  await submit()
  expect(await screen.findByRole('status')).toHaveTextContent('booking request submitted. Status: Pending Review.')
})
test.each([
  ['Booking start *', '2026-12-01T08:00'],
  ['Booking end *', '2026-12-01T11:00'],
  ['Expected attendance / required capacity *', '11'],
  ['Venue requirements', 'New stage'],
])('SCRUM-30 clears stale conflict on editing %s', async (label, value) => {
  setup({ code: 'VENUE_UNAVAILABLE', conflictTypes: ['VENUE_CLOSURE'] })
  await submit()
  await screen.findByRole('alert')
  fireEvent.change(screen.getByLabelText(label), { target: { value } })
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})
test.each([
  [['TENTATIVE_HOLD'], ['An active tentative hold overlaps this time.']],
  [['VENUE_CLOSURE'], ['The venue is closed during this time.']],
  [['APPROVED_BOOKING', 'TENTATIVE_HOLD', 'VENUE_CLOSURE'], ['An approved booking overlaps this time.', 'An active tentative hold overlaps this time.', 'The venue is closed during this time.']],
  [['FUTURE_TYPE'], ['The venue is unavailable for this time.']],
])('SCRUM-30 explains every conflict type %j', async (conflictTypes, messages) => {
  setup({ code: 'VENUE_UNAVAILABLE', conflictTypes })
  await submit()
  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent('Request not submitted.')
  for (const message of messages) expect(alert).toHaveTextContent(message)
})
test('SCRUM-30 approved conflict is accessible, explicit and preserves the draft without adding a booking', async () => {
  setup({ code: 'VENUE_UNAVAILABLE', conflictTypes: ['APPROVED_BOOKING'], message: 'Unavailable' })
  await submit()
  expect(await screen.findByRole('alert')).toHaveTextContent('Request not submitted. An approved booking overlaps this time.')
  expect(screen.getByLabelText(/Venue \*/)).toHaveValue('v')
  expect(screen.getByLabelText('Venue requirements')).toHaveValue('Stage')
  expect(screen.getByText('No venue booking requests yet.')).toBeInTheDocument()
})
