import { render, screen } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { AddVenuePage, EditVenuePage } from './AddVenuePage'
import { fetchVenue } from '../features/venue/venues'

vi.mock('../features/venue/venues', () => ({ fetchVenue: vi.fn() }))

beforeEach(() => {
  vi.mocked(fetchVenue).mockResolvedValue({
    id: 'venue-1', name: 'Grand Ballroom', location: 'Level 3', capacity: 500,
    facilities: ['wifi'], accessibility: '', supportedLayouts: ['theatre'], status: 'Available',
    setupTimeMinutes: 30, turnaroundTimeMinutes: 45,
  })
})

test('Venue Staff can configure buffers when adding a venue', () => {
  render(<AddVenuePage role="Venue Staff" onSaved={vi.fn()} />)

  expect(screen.getByLabelText('Setup Time (minutes) *')).toHaveValue(0)
  expect(screen.getByLabelText('Turnaround Time (minutes) *')).toHaveValue(0)
})

test('editing a venue loads its saved buffer times', async () => {
  render(<EditVenuePage role="Venue Staff" venueId="venue-1" onSaved={vi.fn()} onCancel={vi.fn()} />)

  expect(await screen.findByLabelText('Setup Time (minutes) *')).toHaveValue(30)
  expect(screen.getByLabelText('Turnaround Time (minutes) *')).toHaveValue(45)
})
