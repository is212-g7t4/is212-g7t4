import { afterEach, describe, expect, test, vi } from 'vitest'
import {
  ACCESSIBILITY_OPTIONS,
  EMPTY_CRITERIA,
  missingRequiredFields,
  searchVenues,
  toQuery,
} from './venueSearch'
import type { VenueSearchCriteria } from './venueSearch'

const FILLED: VenueSearchCriteria = {
  ...EMPTY_CRITERIA,
  date: '2026-11-10',
  startTime: '09:00',
  endTime: '12:00',
  expectedAttendance: '120',
}

afterEach(() => vi.unstubAllGlobals())

describe('missingRequiredFields (AC2)', () => {
  test('an empty form names all four required criteria, in form order', () => {
    expect(missingRequiredFields(EMPTY_CRITERIA)).toEqual([
      'Date', 'Start time', 'End time', 'Expected attendance',
    ])
  })

  test('a complete form has nothing missing', () => {
    expect(missingRequiredFields(FILLED)).toEqual([])
  })

  test('only the fields still empty are named', () => {
    expect(missingRequiredFields({ ...EMPTY_CRITERIA, date: '2026-11-10' })).toEqual([
      'Start time', 'End time', 'Expected attendance',
    ])
  })

  test('whitespace is not a filled-in value', () => {
    expect(missingRequiredFields({ ...FILLED, expectedAttendance: '   ' }))
      .toEqual(['Expected attendance'])
  })

  test('optional criteria are never required', () => {
    const optional = { ...EMPTY_CRITERIA, location: 'Main Tower', layout: 'banquet' }
    expect(missingRequiredFields(optional)).toHaveLength(4)
  })
})

describe('toQuery', () => {
  test('date and times become one naive local window, with no offset', () => {
    const q = toQuery(FILLED)
    // VenueBooking stores `timestamp without time zone`, so an offset here
    // would be compared against a naive column.
    expect(q.get('start')).toBe('2026-11-10T09:00:00')
    expect(q.get('end')).toBe('2026-11-10T12:00:00')
    expect(q.toString()).not.toContain('%2B')
    expect(q.toString()).not.toContain('Z')
  })

  test('seconds already present are not doubled', () => {
    const q = toQuery({ ...FILLED, startTime: '09:00:30' })
    expect(q.get('start')).toBe('2026-11-10T09:00:30')
  })

  test('untouched optional fields are left out entirely', () => {
    expect([...toQuery(FILLED).keys()]).toEqual(['start', 'end', 'expectedAttendance'])
  })

  test('blank and whitespace-only optional fields are left out', () => {
    const q = toQuery({ ...FILLED, location: '  ', minCapacity: '', layout: '' })
    expect(q.has('location')).toBe(false)
    expect(q.has('minCapacity')).toBe(false)
    expect(q.has('layout')).toBe(false)
  })

  test('facilities and accessibility repeat the key, so every one is required', () => {
    const q = toQuery({ ...FILLED, facilities: ['wifi', 'stage'], accessibility: ['lift'] })
    expect(q.getAll('facility')).toEqual(['wifi', 'stage'])
    expect(q.getAll('accessibility')).toEqual(['lift'])
  })

  test('optional values are trimmed', () => {
    const q = toQuery({ ...FILLED, location: '  Main Tower  ', minCapacity: ' 200 ' })
    expect(q.get('location')).toBe('Main Tower')
    expect(q.get('minCapacity')).toBe('200')
  })

  test('every chosen optional criterion is sent', () => {
    const q = toQuery({
      ...FILLED, minCapacity: '200', location: 'Main Tower', layout: 'banquet',
      facilities: ['wifi'], accessibility: ['lift'],
    })
    expect(Object.fromEntries(q)).toEqual({
      start: '2026-11-10T09:00:00', end: '2026-11-10T12:00:00',
      expectedAttendance: '120', minCapacity: '200', location: 'Main Tower',
      layout: 'banquet', facility: 'wifi', accessibility: 'lift',
    })
  })
})

describe('searchVenues', () => {
  test('calls the composite, not either atomic directly', async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ venues: [], count: 0 })))
    vi.stubGlobal('fetch', fetcher)

    await searchVenues(FILLED)

    const url: string = fetcher.mock.calls[0][0]
    expect(url).toContain('/venue-search?')
    expect(url).toContain(':5007')
  })

  test('returns the venues the composite shortlisted', async () => {
    const venue = { id: 'v1', name: 'Rooftop Garden', availability: 'Available' }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ venues: [venue], count: 1 }))))

    await expect(searchVenues(FILLED)).resolves.toEqual([venue])
  })

  test('no matches is an empty list, not an error (AC5)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ venues: [], count: 0 }))))

    await expect(searchVenues(FILLED)).resolves.toEqual([])
  })

  test("a 400 surfaces the server's own message", async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ message: 'Choose a date and time in the future.', missing: [] }),
      { status: 400 })))

    await expect(searchVenues(FILLED)).rejects.toThrow('Choose a date and time in the future.')
  })

  test('a non-JSON failure still gives a readable message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response('<html>502</html>', { status: 502 })))

    await expect(searchVenues(FILLED)).rejects.toThrow('Unable to search venues right now.')
  })
})

test('the accessibility keys match the ones Venue Service can map', () => {
  // Venue Service 400s on an unknown key, so a typo here is a broken filter.
  expect(ACCESSIBILITY_OPTIONS.map((option) => option.key)).toEqual([
    'wheelchair', 'lift', 'step_free', 'hearing_loop', 'accessible_washroom',
  ])
})
