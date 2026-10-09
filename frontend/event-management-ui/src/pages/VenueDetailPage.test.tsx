import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { VenueDetailPage } from './VenueDetailPage'
import { fetchVenue } from '../features/venue/venues'
import { fetchActiveVenueHolds, placeVenueHold } from '../features/venue/venueHolds'

vi.mock('../features/venue/venues', () => ({ fetchVenue: vi.fn() }))
vi.mock('../features/venue/venueHolds', () => ({
  fetchActiveVenueHolds: vi.fn(),
  placeVenueHold: vi.fn(),
  showVenueHoldStatus: (venues: { id: string; status: string }[], holds: { venueId: string }[]) =>
    venues.map((venue) => holds.some((hold) => hold.venueId === venue.id) ? { ...venue, status: 'On Hold' } : venue),
}))

const venue = {
  id: 'venue-1', name: 'Rooftop Garden', location: 'Level 12', capacity: 150,
  facilities: [], accessibility: '', supportedLayouts: [], status: 'Available',
}

beforeEach(() => {
  vi.mocked(fetchVenue).mockResolvedValue(venue)
  vi.mocked(fetchActiveVenueHolds).mockResolvedValue([])
  vi.mocked(placeVenueHold).mockResolvedValue({
    id: 'hold-1', venueId: venue.id, createdAt: '2026-10-08T09:00:00',
    expiresAt: '2026-10-09T12:00:00', heldBy: 'staff-1',
  })
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
    { id: 'staff-1', role: 'Venue Staff' },
  ))
  expect(await screen.findAllByText('On Hold')).toHaveLength(2)
})