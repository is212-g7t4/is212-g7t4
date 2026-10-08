import { beforeEach, expect, test, vi } from 'vitest'
import { fetchVenue } from '../venue/venues'
import { loadAttendeeRegistrations } from './attendeeRegistrations'

vi.mock('../venue/venues', () => ({ fetchVenue: vi.fn() }))

const attendeeId = '56b34ab1-92cd-4b35-83c7-f04e176e2bd0'
const event = {
  id: '25c9fe40-c44d-4d79-8d5d-de66d40c1678', eventName: 'Community Workshop',
  description: 'Practical workshop', purpose: 'Learning', preferredStartDate: '2026-11-10T09:00:00+08:00',
  preferredEndDate: '2026-11-10T12:00:00+08:00', expectedAttendance: '30',
  venueId: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', venueRequirements: '', accessibilityNeeds: '',
  equipmentRequirements: '', registrationNeeds: '', status: 'Confirmed', submittedAt: null,
  coordinatorId: null, organiserId: null, decision: null, decisionHistory: [], actionDetails: '', actionHistory: [],
}
const apiRegistration = {
  registration_id: 'registration-1', event_id: event.id, attendee_id: attendeeId,
  registration_date: '2026-10-08T10:00:00+08:00', status: 'Confirmed',
  attendee_name: 'Adam Yeo', attendee_email: 'adam@example.com', attendee_organization: 'External',
}
const venue = {
  id: event.venueId, name: 'Grand Hall', location: 'Level 1', capacity: 100,
  facilities: ['Projector'], accessibility: 'Step-free access', supportedLayouts: [], status: 'Available',
}
const fetcher = vi.fn()

beforeEach(() => {
  vi.resetAllMocks()
  fetcher.mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ registrations: [{ registration: apiRegistration, event }] }),
  })
  vi.stubGlobal('fetch', fetcher)
  vi.mocked(fetchVenue).mockResolvedValue(venue)
})

test('loads attendee-scoped registrations with event and venue details', async () => {
  const result = await loadAttendeeRegistrations(attendeeId)
  expect(fetcher).toHaveBeenCalledWith(`http://localhost:5009/registrations?attendeeId=${attendeeId}`)
  expect(fetchVenue).toHaveBeenCalledWith(event.venueId)
  expect(result[0]).toMatchObject({
    id: 'registration-1', attendeeId, status: 'Confirmed',
    attendeeName: 'Adam Yeo', event, venue,
  })
})

test('returns an empty list without loading venues', async () => {
  fetcher.mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ registrations: [] }),
  } as Response)
  expect(await loadAttendeeRegistrations(attendeeId)).toEqual([])
  expect(fetchVenue).not.toHaveBeenCalled()
})

test('reports composite service errors', async () => {
  fetcher.mockResolvedValue({
    ok: false,
    json: () => Promise.resolve({ message: 'Unable to load your registrations right now.' }),
  } as Response)
  await expect(loadAttendeeRegistrations(attendeeId)).rejects.toThrow('Unable to load your registrations right now.')
})
