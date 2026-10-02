import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { eventApi, validateEvent } from '../features/event/submission'
import { fetchVenues } from '../features/venue/venues'
import type { Venue } from '../features/venue/venues'
import { SubmissionPage } from './SubmissionPage'

vi.mock('../features/event/submission', async () => {
  const actual = await vi.importActual<typeof import('../features/event/submission')>('../features/event/submission')
  return { ...actual, eventApi: vi.fn() }
})
vi.mock('../features/venue/venues', () => ({ fetchVenues: vi.fn() }))
vi.mock('../components/SubmissionPopup', () => ({
  SubmissionPopup: ({ title, messages }: { title: string; messages: string[] }) => (
    <section aria-label={title}>{messages.map((message) => <p key={message}>{message}</p>)}</section>
  ),
}))

const venue: Venue = {
  id: '11111111-1111-4111-8111-111111111111',
  name: 'Grand Hall',
  location: 'Level 1',
  capacity: 100,
  facilities: [],
  accessibility: '',
  supportedLayouts: [],
  status: 'Available',
}

async function completeForm(expectedAttendance: string, selectedVenue: Venue = venue) {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText(/Event Name/), 'Community Workshop')
  await user.type(screen.getByLabelText(/Description/), 'A practical workshop')
  await user.type(screen.getByLabelText(/Purpose/), 'Learning')
  fireEvent.change(screen.getByLabelText(/Preferred Start Date/), { target: { value: '2026-11-10T09:00' } })
  fireEvent.change(screen.getByLabelText(/Preferred End Date/), { target: { value: '2026-11-10T12:00' } })
  fireEvent.change(screen.getByLabelText(/Expected Attendance/), { target: { value: expectedAttendance } })
  await screen.findByRole('option', { name: selectedVenue.name })
  await user.selectOptions(screen.getByLabelText('Venue'), selectedVenue.id)
  return user
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(fetchVenues).mockResolvedValue([venue])
  vi.mocked(eventApi).mockResolvedValue({
    eventName: 'Community Workshop',
    submittedAt: '2026-10-03T01:30:00+00:00',
  })
})

describe('event request venue capacity check', () => {
  test('allows an Event Organiser to open the request form', async () => {
    render(<SubmissionPage role="Event Organiser" />)

    expect(screen.getByRole('heading', { name: 'Create Event Request' })).toBeVisible()
    expect(await screen.findByRole('option', { name: venue.name })).toBeInTheDocument()
  })

  test.each(['Event Coordinator', 'Venue Staff'] as const)('does not let %s submit event requests', (role) => {
    render(<SubmissionPage role={role} />)

    expect(screen.getByText('Only Event Organisers can submit event requests.')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Create Event Request' })).not.toBeInTheDocument()
  })

  test.each([
    [100, venue, 'Grand Hall is suitable: its maximum capacity is 100 and the expected attendance is 100.'],
    [101, venue, "Capacity warning: Grand Hall's maximum capacity is 100, but the expected attendance is 101."],
    [50, { ...venue, capacity: null }, 'Capacity could not be determined for Grand Hall because it has no registered capacity.'],
  ])('displays capacity feedback after a successful submission', async (attendance, selectedVenue, expectedMessage) => {
    vi.mocked(fetchVenues).mockResolvedValue([selectedVenue])
    render(<SubmissionPage role="Event Organiser" />)
    const user = await completeForm(String(attendance), selectedVenue)

    await user.click(screen.getByRole('button', { name: 'Submit Request' }))

    expect(await screen.findByText(expectedMessage)).toBeInTheDocument()
    expect(eventApi).toHaveBeenCalledOnce()
  })

  test.each(['', '-1'])('blocks blank or negative attendance with a field error', async (attendance) => {
    render(<SubmissionPage role="Event Organiser" />)
    const user = await completeForm(attendance)

    await user.click(screen.getByRole('button', { name: 'Submit Request' }))

    await waitFor(() => expect(screen.getByLabelText(/Expected Attendance/).closest('label')).toHaveTextContent(
      attendance ? 'Expected Attendance must be a positive whole number' : 'Expected Attendance is required.',
    ))
    expect(eventApi).not.toHaveBeenCalled()
  })

  test('rejects non-numeric attendance before submission', () => {
    const result = validateEvent({
      eventName: 'Community Workshop', description: 'Workshop', purpose: 'Learning',
      preferredStartDate: '2026-11-10T09:00', preferredEndDate: '2026-11-10T12:00',
      expectedAttendance: 'abc', venueId: venue.id, venueRequirements: '', accessibilityNeeds: '',
      equipmentRequirements: '', registrationNeeds: '',
    })

    expect(result.errors).toContain('Expected Attendance must be a positive whole number (maximum 2147483647).')
  })
})
