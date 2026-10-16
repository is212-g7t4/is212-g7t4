import { afterEach, expect, test, vi } from 'vitest'
import { createVenue, emptyVenueForm, validateVenueForm } from './venueForm'

afterEach(() => vi.unstubAllGlobals())

const completeForm = {
  ...emptyVenueForm,
  name: 'Grand Ballroom',
  location: 'Level 3',
  capacity: '500',
  facilities: 'wifi, stage',
  supportedLayouts: 'theatre, banquet',
  setupTimeMinutes: '30',
  turnaroundTimeMinutes: '45',
}

test('buffer times are validated as non-negative whole minutes', () => {
  expect(validateVenueForm(completeForm)).toEqual({ missingFields: [], errors: [] })
  expect(validateVenueForm({ ...completeForm, setupTimeMinutes: '-1' }).errors).toContain(
    'Setup Time must be a non-negative whole number of minutes (maximum 2147483647).',
  )
  expect(validateVenueForm({ ...completeForm, turnaroundTimeMinutes: '1.5' }).errors).toContain(
    'Turnaround Time must be a non-negative whole number of minutes (maximum 2147483647).',
  )
})

test('create sends each venue buffer with the catalogue profile', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ venue: { id: 'venue-1' } }), { status: 201 }))
  vi.stubGlobal('fetch', fetcher)

  await createVenue(completeForm)

  const request = fetcher.mock.calls[0][1] as RequestInit
  expect(JSON.parse(request.body as string)).toMatchObject({
    setupTimeMinutes: '30',
    turnaroundTimeMinutes: '45',
  })
})
