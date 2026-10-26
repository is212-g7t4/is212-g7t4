import { afterEach, expect, test, vi } from 'vitest'
import { createVenue, emptyVenueForm, updateVenue, updateVenueSafetyInfo, validateVenueForm, VenueSubmissionError } from './venueForm'

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

test('edit uses the composite workflow so legacy conflicts are refreshed automatically', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ venue: { id: 'venue-1' }, legacyConflicts: { conflicts: [] } })))
  vi.stubGlobal('fetch', fetcher)

  await updateVenue('venue-1', completeForm)

  expect(fetcher.mock.calls[0][0]).toBe('http://localhost:5007/venues/venue-1')
  expect(fetcher.mock.calls[0][1]).toMatchObject({ method: 'PUT' })
})

// SCRUM-167 Record Venue Safety Information ------------------------------------

const staff = { id: 'staff-1', role: 'Venue Staff' as const }

test('SCRUM-167 AC1: safety texts of 2000 characters pass and 2001 are refused', () => {
  expect(validateVenueForm({ ...completeForm, emergencyAccessDetails: 'x'.repeat(2000), knownRestrictions: 'y'.repeat(2000) }).errors).toEqual([])
  expect(validateVenueForm({ ...completeForm, emergencyAccessDetails: 'x'.repeat(2001) }).errors).toEqual([
    'Emergency Access Details must be at most 2000 characters.',
  ])
  expect(validateVenueForm({ ...completeForm, knownRestrictions: 'y'.repeat(2001) }).errors).toEqual([
    'Known Restrictions must be at most 2000 characters.',
  ])
})

test('SCRUM-167 AC1/AC4: safety info goes straight to Venue Service with the Venue Staff identity', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ venue: { id: 'venue-1' } })))
  vi.stubGlobal('fetch', fetcher)

  await updateVenueSafetyInfo('venue-1', { emergencyAccessDetails: '  North exits  ', knownRestrictions: '   ' }, staff)

  expect(fetcher.mock.calls[0][0]).toBe('http://localhost:5006/venues/venue-1/safety-info')
  const request = fetcher.mock.calls[0][1] as RequestInit
  expect(request.method).toBe('PUT')
  expect(request.headers).toEqual({ 'Content-Type': 'application/json', 'X-Dev-User-Id': 'staff-1', 'X-Dev-Role': 'Venue Staff' })
  // AC2: a cleared field is sent as null so the venue reads "Not provided".
  expect(JSON.parse(request.body as string)).toEqual({ emergencyAccessDetails: 'North exits', knownRestrictions: null })
})

test('SCRUM-167 AC4: a refused safety save surfaces the server message and errors', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
    code: 'VENUE_STAFF_ONLY', message: 'Only Venue Staff can edit venue safety information.',
  }), { status: 403 })))

  const failure = updateVenueSafetyInfo('venue-1', { emergencyAccessDetails: 'a', knownRestrictions: 'b' }, staff)

  await expect(failure).rejects.toBeInstanceOf(VenueSubmissionError)
  await expect(failure).rejects.toMatchObject({ message: 'Only Venue Staff can edit venue safety information.', errors: [] })
})

test('SCRUM-167 AC4: an unreadable error body falls back to a generic message', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('not json', { status: 503 })))

  await expect(updateVenueSafetyInfo('venue-1', { emergencyAccessDetails: '', knownRestrictions: '' }, staff))
    .rejects.toMatchObject({ message: 'Unable to save the safety information.' })
})

test('SCRUM-167 AC4: the profile save never carries the safety fields', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ venue: { id: 'venue-1' } })))
  vi.stubGlobal('fetch', fetcher)

  await updateVenue('venue-1', { ...completeForm, emergencyAccessDetails: 'North exits', knownRestrictions: 'No flames' })

  const body = JSON.parse((fetcher.mock.calls[0][1] as RequestInit).body as string)
  expect(body).not.toHaveProperty('emergencyAccessDetails')
  expect(body).not.toHaveProperty('knownRestrictions')
})
