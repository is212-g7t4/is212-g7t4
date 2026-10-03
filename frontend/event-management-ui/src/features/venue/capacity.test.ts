import { describe, expect, test } from 'vitest'
import type { Venue } from './venues'
import { venueCapacityMessage } from './capacity'

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

describe('venue capacity feedback', () => {
  test('reports that a venue is suitable at its capacity boundary', () => {
    expect(venueCapacityMessage(venue, 100)).toContain('Grand Hall is suitable')
  })

  test('warns with the maximum and expected attendance when capacity is exceeded', () => {
    expect(venueCapacityMessage(venue, 101)).toBe(
      "Capacity warning: Grand Hall's maximum capacity is 100, but the expected attendance is 101.",
    )
  })

  test('reports when the selected venue has no registered capacity', () => {
    expect(venueCapacityMessage({ ...venue, capacity: null }, 50)).toBe(
      'Capacity could not be determined for Grand Hall because it has no registered capacity.',
    )
  })
})
