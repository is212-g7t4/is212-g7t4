import { beforeEach, expect, test, vi } from 'vitest'
import { fetchRegistrationCounts } from '../registration/registrations'
import { fetchUser } from '../user/users'
import { fetchVenue } from '../venue/venues'
import { eventApi } from './submission'
import type { SubmittedEvent } from './submission'
import { loadAttendeeEvents, registrationAvailability } from './attendeeEvents'

vi.mock('./submission', () => ({ eventApi: vi.fn() }))
vi.mock('../registration/registrations', () => ({ fetchRegistrationCounts: vi.fn() }))
vi.mock('../venue/venues', () => ({ fetchVenue: vi.fn() }))
vi.mock('../user/users', () => ({ fetchUser: vi.fn() }))

const now = new Date('2026-10-07T04:00:00Z')
const base: SubmittedEvent = {
  id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', eventName: 'Community Workshop',
  description: 'A practical workshop', purpose: 'Learning',
  preferredStartDate: '2026-10-10T09:00:00+08:00', preferredEndDate: '2026-10-10T12:00:00+08:00',
  expectedAttendance: '2', venueId: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  venueRequirements: '', accessibilityNeeds: '', equipmentRequirements: '', registrationNeeds: 'Bring photo ID.',
  status: 'Confirmed', submittedAt: null, coordinatorId: null,
  organiserId: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', decision: null, decisionHistory: [],
  actionDetails: '', actionHistory: [],
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(fetchVenue).mockResolvedValue({
    id: base.venueId, name: 'Grand Hall', location: 'Level 1', capacity: 100,
    facilities: ['Projector'], accessibility: 'Wheelchair access', supportedLayouts: [], status: 'Available',
  })
  vi.mocked(fetchUser).mockResolvedValue({
    id: base.organiserId!, username: 'Olivia Tan', email: 'olivia@example.com', role: 'Event Organiser',
    organization: 'ConnectSphere', managerId: null, contactDetails: '+65 8111 1111',
  })
})

test('derives open, full and closed registration states', () => {
  expect(registrationAvailability(base, 1, now)).toBe('Open')
  expect(registrationAvailability(base, 2, now)).toBe('Full')
  expect(registrationAvailability({ ...base, preferredStartDate: '2026-10-07T10:00:00+08:00' }, 0, now)).toBe('Closed')
})

test('loads confirmed events and combines registration, venue and organiser data', async () => {
  const full = { ...base, id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', eventName: 'Full Conference' }
  const ongoing = {
    ...base, id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', eventName: 'Ongoing Event',
    preferredStartDate: '2026-10-07T10:00:00+08:00', preferredEndDate: '2026-10-07T14:00:00+08:00',
  }
  const ended = { ...base, id: 'ffffffff-ffff-4fff-8fff-ffffffffffff', preferredEndDate: '2026-10-06T12:00:00+08:00' }
  vi.mocked(eventApi).mockResolvedValue({ events: [base, full, ongoing, ended, { ...base, status: 'Approved' }] })
  vi.mocked(fetchRegistrationCounts).mockResolvedValue({
    [base.id]: { total: 1, confirmed: 1 },
    [full.id]: { total: 2, confirmed: 2 },
    [ongoing.id]: { total: 0, confirmed: 0 },
  })

  const events = await loadAttendeeEvents(now)

  expect(events.map((event) => [event.eventName, event.registrationStatus])).toEqual([
    ['Community Workshop', 'Open'], ['Full Conference', 'Full'], ['Ongoing Event', 'Closed'],
  ])
  expect(events[0].venue?.name).toBe('Grand Hall')
  expect(events[0].organiser?.contactDetails).toBe('+65 8111 1111')
  expect(fetchRegistrationCounts).toHaveBeenCalledWith([base.id, full.id, ongoing.id])
})

test('returns an empty list without calling other services when no confirmed events remain', async () => {
  vi.mocked(eventApi).mockResolvedValue({ events: [] })
  expect(await loadAttendeeEvents(now)).toEqual([])
  expect(fetchRegistrationCounts).not.toHaveBeenCalled()
  expect(fetchVenue).not.toHaveBeenCalled()
  expect(fetchUser).not.toHaveBeenCalled()
})
