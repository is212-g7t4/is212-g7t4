import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { loadAttendeeEvents } from '../features/event/attendeeEvents'
import type { AttendeeEvent } from '../features/event/attendeeEvents'
import { AttendeeEventsPage } from './AttendeeEventsPage'
import { EventRegistrationError, registerForEvent } from '../features/registration/eventRegistration'
import { fetchUser } from '../features/user/users'

vi.mock('../features/event/attendeeEvents', () => ({ loadAttendeeEvents: vi.fn() }))
vi.mock('../features/user/users', () => ({ fetchUser: vi.fn() }))
vi.mock('../features/registration/eventRegistration', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../features/registration/eventRegistration')>()
  return { ...actual, registerForEvent: vi.fn() }
})

const event: AttendeeEvent = {
  id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', eventName: 'Community Workshop',
  description: 'A full practical workshop description.', purpose: 'Community learning',
  preferredStartDate: '2026-10-10T09:00:00+08:00', preferredEndDate: '2026-10-10T12:00:00+08:00',
  expectedAttendance: '30', venueRequirements: '', accessibilityNeeds: '', equipmentRequirements: '', registrationNeeds: 'Bring photo ID.',
  status: 'Confirmed', submittedAt: null, coordinatorId: null,
  organiserId: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', decision: null, decisionHistory: [],
  actionDetails: '', actionHistory: [], registrationStatus: 'Open', confirmedRegistrations: 12,
  venue: {
    id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', name: 'Grand Hall', location: 'Level 1', capacity: 100,
    facilities: ['Projector', 'Wi-Fi'], accessibility: 'Wheelchair access', supportedLayouts: [], status: 'Available',
  },
  organiser: {
    id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', username: 'Olivia Tan', email: 'olivia@example.com',
    role: 'Event Organiser', organization: 'ConnectSphere', contactDetails: '+65 8111 1111',
  },
}

const ATTENDEE_ID = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
const attendee = {
  id: ATTENDEE_ID, username: 'Adam Yeo', email: 'adam@example.com', role: 'Attendee' as const,
  organization: 'External', contactDetails: '',
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(loadAttendeeEvents).mockResolvedValue([event])
  vi.mocked(registerForEvent).mockResolvedValue({ message: 'Registration confirmed for Community Workshop.' })
  vi.mocked(fetchUser).mockResolvedValue(attendee)
})

test('attendee sees confirmed event summary and opens full details', async () => {
  render(<AttendeeEventsPage role="Attendee" />)

  expect(await screen.findByText('Community Workshop')).toBeInTheDocument()
  expect(screen.getByText('Open', { selector: '.status-badge' })).toBeInTheDocument()
  expect(screen.getByText(/Grand Hall · Level 1/)).toBeInTheDocument()
  expect(screen.getByText('A full practical workshop description.')).toBeInTheDocument()
  expect(screen.getByText('Community learning')).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: /Community Workshop/ }))

  expect(screen.getByRole('heading', { name: 'Community Workshop' })).toBeInTheDocument()
  expect(screen.getByText('Projector, Wi-Fi')).toBeInTheDocument()
  expect(screen.getByText('Wheelchair access')).toBeInTheDocument()
  expect(screen.getByText('Bring photo ID.')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'olivia@example.com' })).toHaveAttribute('href', 'mailto:olivia@example.com')
  expect(screen.getByText('+65 8111 1111')).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Programme and agenda' })).not.toBeInTheDocument()
  expect(screen.queryByText('Deadline')).not.toBeInTheDocument()
  expect(screen.queryByText('Not provided')).not.toBeInTheDocument()
})

test('attendee sees an empty-state message when no confirmed events are available', async () => {
  vi.mocked(loadAttendeeEvents).mockResolvedValue([])
  render(<AttendeeEventsPage role="Attendee" />)
  expect(await screen.findByText('There are no upcoming confirmed events available for registration.')).toBeInTheDocument()
})

test('non-attendee cannot load the attendee event catalogue', () => {
  render(<AttendeeEventsPage role="Event Coordinator" />)
  expect(screen.getByText('Confirmed events open for registration are visible to Attendees.')).toBeInTheDocument()
  expect(loadAttendeeEvents).not.toHaveBeenCalled()
})

test('attendee registers with their account details shown read-only', async () => {
  render(<AttendeeEventsPage role="Attendee" attendeeId={ATTENDEE_ID} />)
  fireEvent.click(await screen.findByRole('button', { name: /Community Workshop/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Register' }))

  expect(await screen.findByText('Adam Yeo')).toBeInTheDocument()
  expect(screen.getByText('adam@example.com')).toBeInTheDocument()
  expect(screen.getByText('External')).toBeInTheDocument()
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  expect(fetchUser).toHaveBeenCalledWith(ATTENDEE_ID)

  fireEvent.click(screen.getByRole('button', { name: 'Submit registration' }))

  await waitFor(() => expect(registerForEvent).toHaveBeenCalledWith({
    eventId: event.id,
    attendeeId: ATTENDEE_ID,
  }))
  expect(await screen.findByText('Registration confirmed for Community Workshop.')).toBeInTheDocument()
})

test('attendee sees an error when their account details cannot load', async () => {
  vi.mocked(fetchUser).mockRejectedValue(new Error('down'))
  render(<AttendeeEventsPage role="Attendee" attendeeId={ATTENDEE_ID} />)
  fireEvent.click(await screen.findByRole('button', { name: /Community Workshop/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Register' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load your account details.')
})

test('attendee sees duplicate-registration error from the server', async () => {
  vi.mocked(registerForEvent).mockRejectedValue(
    new EventRegistrationError('You are already registered for this event.', 'DUPLICATE_REGISTRATION'),
  )
  render(<AttendeeEventsPage role="Attendee" attendeeId={ATTENDEE_ID} />)
  fireEvent.click(await screen.findByRole('button', { name: /Community Workshop/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Register' }))
  await screen.findByText('Adam Yeo')
  fireEvent.click(screen.getByRole('button', { name: 'Submit registration' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('You are already registered for this event.')
})

test.each([
  ['Full', 'This event has reached maximum capacity.'],
  ['Closed', 'Registration has closed for this event.'],
] as const)('registration form is unavailable when registration is %s', async (status, message) => {
  vi.mocked(loadAttendeeEvents).mockResolvedValue([{ ...event, registrationStatus: status }])
  render(<AttendeeEventsPage role="Attendee" attendeeId="dddddddd-dddd-4ddd-8ddd-dddddddddddd" />)
  fireEvent.click(await screen.findByRole('button', { name: /Community Workshop/ }))
  expect(screen.getByRole('alert')).toHaveTextContent(message)
  expect(screen.queryByRole('button', { name: 'Register' })).not.toBeInTheDocument()
})
