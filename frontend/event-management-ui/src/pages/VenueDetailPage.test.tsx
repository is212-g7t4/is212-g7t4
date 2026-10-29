import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { VenueDetailPage } from './VenueDetailPage'
import { fetchVenue } from '../features/venue/venues'
import { fetchActiveVenueHolds, placeVenueHold } from '../features/venue/venueHolds'
import { fetchLegacyConflicts } from '../features/venue/legacyConflicts'

vi.mock('../features/venue/venues', () => ({ fetchVenue: vi.fn() }))
vi.mock('../features/venue/venueHolds', () => ({
  fetchActiveVenueHolds: vi.fn(),
  placeVenueHold: vi.fn(),
  showVenueHoldStatus: (venues: { id: string; status: string }[], holds: { venueId: string }[]) =>
    venues.map((venue) => holds.some((hold) => hold.venueId === venue.id) ? { ...venue, status: 'On Hold' } : venue),
}))
vi.mock('../features/venue/legacyConflicts', () => ({ fetchLegacyConflicts: vi.fn() }))

const venue = {
  id: 'venue-1', name: 'Rooftop Garden', location: 'Level 12', capacity: 150,
  facilities: [], accessibility: '', supportedLayouts: [], status: 'Available',
  setupTimeMinutes: 30, turnaroundTimeMinutes: 45,
}

beforeEach(() => {
  vi.mocked(fetchVenue).mockResolvedValue(venue)
  vi.mocked(fetchActiveVenueHolds).mockResolvedValue([])
  vi.mocked(fetchLegacyConflicts).mockResolvedValue({ venueId: venue.id, conflictCount: 0, conflicts: [] })
  vi.mocked(placeVenueHold).mockResolvedValue({
    id: 'hold-1', venueId: venue.id, createdAt: '2026-10-08T09:00:00',
    expiresAt: '2026-10-09T12:00:00', heldBy: 'staff-1',
  })
})

test('shows the venue-specific setup and turnaround times', async () => {
  render(<VenueDetailPage venueId={venue.id} role="Event Coordinator" onBack={vi.fn()} onEdit={vi.fn()} />)

  expect(await screen.findByText('Setup time')).toBeInTheDocument()
  expect(screen.getByText('30 minutes')).toBeInTheDocument()
  expect(screen.getByText('45 minutes')).toBeInTheDocument()
})

test('Event Coordinator sees the expiry of a venue on hold', async () => {
  vi.mocked(fetchActiveVenueHolds).mockResolvedValue([
    { id: 'hold-1', venueId: venue.id, createdAt: '2026-10-08T09:00:00', expiresAt: '2026-10-09T12:00:00', heldBy: 'staff-1' },
  ])
  render(<VenueDetailPage venueId={venue.id} role="Event Coordinator" onBack={vi.fn()} onEdit={vi.fn()} />)

  expect(await screen.findByText('Hold expires')).toBeInTheDocument()
  expect(screen.getByText(/9 Oct 2026/)).toHaveTextContent(/12:00\s?pm/i)
})

test('Venue Staff can submit a timed hold from venue details', async () => {
  render(<VenueDetailPage
    venueId={venue.id}
    role="Venue Staff"
    user={{ id: 'staff-1', role: 'Venue Staff' }}
    onBack={vi.fn()}
    onEdit={vi.fn()}
  />)

  expect(await screen.findByRole('button', { name: 'Hold' })).toBeEnabled()
  expect(screen.getByRole('button', { name: /Edit Venue/ })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Hold' }))

  const expiry = screen.getByLabelText('Hold expiry date and time')
  expect(expiry).toBeRequired()
  fireEvent.change(expiry, { target: { value: '2026-10-09T12:00' } })
  fireEvent.click(screen.getByRole('button', { name: 'Confirm hold' }))

  await waitFor(() => expect(placeVenueHold).toHaveBeenCalledWith(
    venue.id,
    '2026-10-09T12:00',
    undefined,
    venue,
  ))
  expect(await screen.findAllByText('On Hold')).toHaveLength(2)
})

test('Venue Staff can assign a coordinator reminder without losing venue buffers', async () => {
  render(<VenueDetailPage
    venueId={venue.id}
    role="Venue Staff"
    user={{ id: 'staff-1', role: 'Venue Staff' }}
    coordinators={[{ id: 'coordinator-1', username: 'Alice Tan' }]}
    onBack={vi.fn()}
    onEdit={vi.fn()}
  />)

  fireEvent.click(await screen.findByRole('button', { name: 'Hold' }))
  fireEvent.change(screen.getByLabelText('Hold expiry date and time'), {
    target: { value: '2026-10-09T12:00' },
  })
  fireEvent.change(screen.getByLabelText('Event Coordinator to remind (optional)'), {
    target: { value: 'coordinator-1' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Confirm hold' }))

  await waitFor(() => expect(placeVenueHold).toHaveBeenCalledWith(
    venue.id,
    '2026-10-09T12:00',
    'coordinator-1',
    venue,
  ))
})

test('Venue Staff sees legacy buffer conflicts without any automatic cancellation', async () => {
  vi.mocked(fetchLegacyConflicts).mockResolvedValue({
    venueId: venue.id,
    conflictCount: 1,
    conflicts: [{
      reason: 'BUFFER_OVERLAP',
      firstBooking: {
        id: 'booking-1', eventId: 'event-1', eventName: 'Sustainable Operations Workshop', status: 'Approved',
        requestedStartTime: '2026-10-10T10:00:00', requestedEndTime: '2026-10-10T12:00:00',
        effectiveStartTime: '2026-10-10T09:30:00', effectiveEndTime: '2026-10-10T12:45:00',
        conflictReason: 'BUFFER_OVERLAP',
      },
      secondBooking: {
        id: 'booking-2', eventId: 'event-2', eventName: 'Asia-Pacific Product Leadership Summit', status: 'Approved',
        requestedStartTime: '2026-10-10T12:30:00', requestedEndTime: '2026-10-10T14:00:00',
        effectiveStartTime: '2026-10-10T12:00:00', effectiveEndTime: '2026-10-10T14:45:00',
        conflictReason: 'BUFFER_OVERLAP',
      },
    }],
  })

  render(<VenueDetailPage venueId={venue.id} role="Venue Staff" user={{ id: 'staff-1', role: 'Venue Staff' }} onBack={vi.fn()} onEdit={vi.fn()} />)

  expect(await screen.findByText(/1 buffer conflict requires manual review/)).toBeInTheDocument()
  expect(screen.getByText(/No booking has been cancelled or changed/)).toBeInTheDocument()
  expect(screen.getAllByText('Event time')).toHaveLength(2)
  expect(screen.getAllByText('Venue occupied')).toHaveLength(2)
  expect(screen.getByText('2026-10-10 10:00–2026-10-10 12:00 SGT')).toBeInTheDocument()
  expect(screen.getByText('2026-10-10 09:30–2026-10-10 12:45 SGT')).toBeInTheDocument()
  expect(screen.getByText('Venue occupancy overlaps by 45 minutes, from 2026-10-10 12:00 to 2026-10-10 12:45 SGT.')).toBeInTheDocument()
  expect(screen.getByText('Sustainable Operations Workshop')).toHaveAttribute('title', 'Event ID: event-1')
  expect(screen.getByText('Asia-Pacific Product Leadership Summit')).toHaveAttribute('title', 'Event ID: event-2')
})

// SCRUM-167 Record Venue Safety Information ------------------------------------

const staffUsers = [{ id: 'staff-1', username: 'Priya Venue' }]

function safetyBlock() {
  return within(screen.getByRole('region', { name: 'Safety information' }))
}

test('SCRUM-167 AC1: recorded safety information is shown with its line breaks', async () => {
  vi.mocked(fetchVenue).mockResolvedValue({
    ...venue,
    emergencyAccessDetails: 'North exit\nAssembly at the lawn',
    knownRestrictions: 'No open flames',
  })
  render(<VenueDetailPage venueId={venue.id} role="Event Coordinator" onBack={vi.fn()} onEdit={vi.fn()} />)

  await screen.findByRole('region', { name: 'Safety information' })
  const emergency = safetyBlock().getByText(/North exit/)
  // The newline reaches the DOM; venueDetail.css renders it with white-space: pre-line.
  expect(emergency.textContent).toBe('North exit\nAssembly at the lawn')
  expect(safetyBlock().getByText('No open flames')).toBeInTheDocument()
})

test.each([
  ['null', null],
  ['blank', '  '],
  ['absent', undefined],
])('SCRUM-167 AC2: %s safety information reads "Not provided"', async (_label, value) => {
  vi.mocked(fetchVenue).mockResolvedValue({ ...venue, emergencyAccessDetails: value, knownRestrictions: value })
  render(<VenueDetailPage venueId={venue.id} role="Event Coordinator" onBack={vi.fn()} onEdit={vi.fn()} />)

  await screen.findByRole('region', { name: 'Safety information' })
  expect(safetyBlock().getAllByText('Not provided')).toHaveLength(2)
  expect(safetyBlock().queryByText(/Last updated/)).not.toBeInTheDocument()
})

test('SCRUM-167 AC3: the last editor and time are shown when stamped', async () => {
  vi.mocked(fetchVenue).mockResolvedValue({
    ...venue, emergencyAccessDetails: 'North exit', knownRestrictions: null,
    safetyInfoUpdatedBy: 'staff-1', safetyInfoUpdatedAt: '2030-01-15T10:30:00+08:00',
  })
  render(<VenueDetailPage venueId={venue.id} role="Event Coordinator" users={staffUsers} onBack={vi.fn()} onEdit={vi.fn()} />)

  expect(await screen.findByText(/Last updated .*15 Jan 2030.* by Priya Venue/)).toBeInTheDocument()
})

test('SCRUM-167 AC3: an editor missing from the user list is named generically', async () => {
  vi.mocked(fetchVenue).mockResolvedValue({
    ...venue, safetyInfoUpdatedBy: 'someone-else', safetyInfoUpdatedAt: '2030-01-15T10:30:00+08:00',
  })
  render(<VenueDetailPage venueId={venue.id} role="Event Coordinator" users={staffUsers} onBack={vi.fn()} onEdit={vi.fn()} />)

  expect(await screen.findByText(/Last updated .* by a Venue Staff member/)).toBeInTheDocument()
})

test('SCRUM-167 AC4: an Event Coordinator sees the safety information but cannot edit the venue', async () => {
  vi.mocked(fetchVenue).mockResolvedValue({ ...venue, emergencyAccessDetails: 'North exit', knownRestrictions: 'No open flames' })
  render(<VenueDetailPage venueId={venue.id} role="Event Coordinator" onBack={vi.fn()} onEdit={vi.fn()} />)

  await screen.findByRole('region', { name: 'Safety information' })
  expect(safetyBlock().getByText('North exit')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Edit Venue/ })).not.toBeInTheDocument()
})
