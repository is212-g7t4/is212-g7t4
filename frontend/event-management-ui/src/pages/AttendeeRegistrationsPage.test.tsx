import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import type { AttendeeRegistration } from '../features/registration/attendeeRegistrations'
import { loadAttendeeRegistrations } from '../features/registration/attendeeRegistrations'
import { AttendeeRegistrationsPage } from './AttendeeRegistrationsPage'

vi.mock('../features/registration/attendeeRegistrations', () => ({ loadAttendeeRegistrations: vi.fn() }))

const attendeeId = '56b34ab1-92cd-4b35-83c7-f04e176e2bd0'
const registration: AttendeeRegistration = {
  id: 'registration-1', attendeeId, registrationDate: '2026-10-08T10:00:00+08:00', status: 'Confirmed',
  attendeeName: 'Adam Yeo', attendeeEmail: 'adam@example.com', attendeeOrganization: 'External',
  event: {
    id: '25c9fe40-c44d-4d79-8d5d-de66d40c1678', eventName: 'Community Workshop',
    description: 'A full practical workshop description.', purpose: 'Community learning',
    preferredStartDate: '2026-11-10T09:00:00+08:00', preferredEndDate: '2026-11-10T12:00:00+08:00',
    expectedAttendance: '30', venueId: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', venueRequirements: '',
    accessibilityNeeds: '', equipmentRequirements: '', registrationNeeds: '', status: 'Confirmed',
    submittedAt: null, coordinatorId: null, organiserId: null, decision: null, decisionHistory: [],
    actionDetails: '', actionHistory: [],
  },
  venue: {
    id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', name: 'Grand Hall', location: 'Level 1', capacity: 100,
    facilities: ['Projector'], accessibility: 'Step-free access', supportedLayouts: [], status: 'Available',
  },
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(loadAttendeeRegistrations).mockResolvedValue([registration])
})

test('attendee views registration summary and full details', async () => {
  render(<AttendeeRegistrationsPage role="Attendee" attendeeId={attendeeId} />)
  expect(await screen.findByText('Community Workshop')).toBeInTheDocument()
  expect(loadAttendeeRegistrations).toHaveBeenCalledWith(attendeeId)
  expect(screen.getByText('Confirmed', { selector: '.status-badge' })).toBeInTheDocument()
  expect(screen.getByText(/Grand Hall · Level 1/)).toBeInTheDocument()
  expect(screen.getByText(/Registered:/)).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: /Community Workshop/ }))
  expect(screen.getByRole('heading', { name: 'Registration details' })).toBeInTheDocument()
  expect(screen.getByText('Adam Yeo')).toBeInTheDocument()
  expect(screen.getByText('adam@example.com')).toBeInTheDocument()
  expect(screen.getByText('External')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Event details' })).toBeInTheDocument()
  expect(screen.getByText('Grand Hall')).toBeInTheDocument()
  expect(screen.getByText('A full practical workshop description.')).toBeInTheDocument()
})

test('attendee with no registrations sees the required empty state', async () => {
  vi.mocked(loadAttendeeRegistrations).mockResolvedValue([])
  render(<AttendeeRegistrationsPage role="Attendee" attendeeId={attendeeId} />)
  expect(await screen.findByText('You have not registered for any events.')).toBeInTheDocument()
})

test('non-attendee cannot load registration status', () => {
  render(<AttendeeRegistrationsPage role="Event Coordinator" attendeeId={attendeeId} />)
  expect(screen.getByText('Registration status is visible only to Attendees.')).toBeInTheDocument()
  expect(loadAttendeeRegistrations).not.toHaveBeenCalled()
})
