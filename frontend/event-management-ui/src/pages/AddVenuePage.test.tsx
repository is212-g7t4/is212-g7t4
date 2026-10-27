import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { AddVenuePage, EditVenuePage } from './AddVenuePage'
import { fetchVenue } from '../features/venue/venues'
import { updateVenue, updateVenueSafetyInfo, VenueSubmissionError } from '../features/venue/venueForm'

vi.mock('../features/venue/venues', () => ({ fetchVenue: vi.fn() }))
vi.mock('../features/venue/venueForm', async (importOriginal) => ({
  ...await importOriginal<typeof import('../features/venue/venueForm')>(),
  updateVenue: vi.fn(),
  updateVenueSafetyInfo: vi.fn(),
}))

beforeEach(() => {
  vi.mocked(fetchVenue).mockResolvedValue({
    id: 'venue-1', name: 'Grand Ballroom', location: 'Level 3', capacity: 500,
    facilities: ['wifi'], accessibility: '', supportedLayouts: ['theatre'], status: 'Available',
    setupTimeMinutes: 30, turnaroundTimeMinutes: 45,
    emergencyAccessDetails: 'North and south exits', knownRestrictions: null,
  })
  vi.mocked(updateVenue).mockReset().mockResolvedValue({
    id: 'venue-1', name: 'Grand Ballroom', location: 'Level 3', capacity: 500,
    facilities: ['wifi'], accessibility: '', supportedLayouts: ['theatre'], status: 'Available',
  })
  vi.mocked(updateVenueSafetyInfo).mockReset().mockResolvedValue({
    id: 'venue-1', name: 'Grand Ballroom', location: 'Level 3', capacity: 500,
    facilities: ['wifi'], accessibility: '', supportedLayouts: ['theatre'], status: 'Available',
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

// SCRUM-167 Record Venue Safety Information ------------------------------------

const staff = { id: 'staff-1', role: 'Venue Staff' as const }

function renderEdit(onSaved = vi.fn()) {
  render(<EditVenuePage role="Venue Staff" venueId="venue-1" user={staff} onSaved={onSaved} onCancel={vi.fn()} />)
}

test('SCRUM-167 AC1: the Edit page shows the Safety Information section pre-filled', async () => {
  renderEdit()

  expect(await screen.findByRole('heading', { name: 'Safety Information' })).toBeInTheDocument()
  expect(screen.getByLabelText('Emergency Access Details')).toHaveValue('North and south exits')
  expect(screen.getByLabelText('Known Restrictions')).toHaveValue('')
  expect(screen.getByLabelText('Known Restrictions')).toBeEnabled()
})

test('SCRUM-167: the Add page has no Safety Information section', () => {
  render(<AddVenuePage role="Venue Staff" onSaved={vi.fn()} />)

  expect(screen.queryByRole('heading', { name: 'Safety Information' })).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Emergency Access Details')).not.toBeInTheDocument()
})

test('SCRUM-167 AC1: changed safety values are saved after the profile', async () => {
  const onSaved = vi.fn()
  renderEdit(onSaved)
  fireEvent.change(await screen.findByLabelText('Known Restrictions'), { target: { value: 'Noise curfew 10pm' } })

  fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }))

  await waitFor(() => expect(onSaved).toHaveBeenCalledWith('venue-1'))
  expect(updateVenue).toHaveBeenCalledTimes(1)
  expect(updateVenueSafetyInfo).toHaveBeenCalledWith(
    'venue-1',
    { emergencyAccessDetails: 'North and south exits', knownRestrictions: 'Noise curfew 10pm' },
    staff,
  )
  expect(vi.mocked(updateVenue).mock.invocationCallOrder[0])
    .toBeLessThan(vi.mocked(updateVenueSafetyInfo).mock.invocationCallOrder[0])
})

test('SCRUM-167 AC3: unchanged safety values make no safety save, so nothing is restamped', async () => {
  const onSaved = vi.fn()
  renderEdit(onSaved)
  await screen.findByLabelText('Known Restrictions')

  fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }))

  await waitFor(() => expect(onSaved).toHaveBeenCalledWith('venue-1'))
  expect(updateVenue).toHaveBeenCalledTimes(1)
  expect(updateVenueSafetyInfo).not.toHaveBeenCalled()
})

test('SCRUM-167 AC1: a failed safety save keeps the user on the form with what was typed', async () => {
  vi.mocked(updateVenueSafetyInfo).mockRejectedValue(
    new VenueSubmissionError('Please correct the safety information.', [], ['Known Restrictions must be at most 2000 characters.']),
  )
  const onSaved = vi.fn()
  renderEdit(onSaved)
  fireEvent.change(await screen.findByLabelText('Known Restrictions'), { target: { value: 'Noise curfew 10pm' } })

  fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }))

  expect(await screen.findByText(
    'Venue details were saved, but the safety information was not: Known Restrictions must be at most 2000 characters.',
  )).toBeInTheDocument()
  expect(onSaved).not.toHaveBeenCalled()
  expect(screen.getByLabelText('Known Restrictions')).toHaveValue('Noise curfew 10pm')
})

test('SCRUM-167 AC1: an unreachable Venue Service on the safety save is reported the same way', async () => {
  vi.mocked(updateVenueSafetyInfo).mockRejectedValue(new TypeError('Failed to fetch'))
  renderEdit()
  fireEvent.change(await screen.findByLabelText('Emergency Access Details'), { target: { value: '' } })

  fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }))

  expect(await screen.findByText(
    'Venue details were saved, but the safety information was not: Unable to reach the Venue Service.',
  )).toBeInTheDocument()
})

test('SCRUM-167 AC4: without a Venue Staff user the safety fields are read-only and never saved', async () => {
  const onSaved = vi.fn()
  render(<EditVenuePage role="Venue Staff" venueId="venue-1" onSaved={onSaved} onCancel={vi.fn()} />)

  expect(await screen.findByLabelText('Emergency Access Details')).toBeDisabled()
  expect(screen.getByText('Only Venue Staff can edit safety information.')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }))

  await waitFor(() => expect(onSaved).toHaveBeenCalled())
  expect(updateVenueSafetyInfo).not.toHaveBeenCalled()
})
