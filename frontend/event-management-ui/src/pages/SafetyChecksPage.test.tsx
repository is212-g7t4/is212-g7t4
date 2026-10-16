import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { eventApi } from '../features/event/submission'
import type { SubmittedEvent } from '../features/event/submission'
import { SafetyChecksPage } from './SafetyChecksPage'

vi.mock('../features/event/submission', () => ({ eventApi: vi.fn() }))

const safetyOfficerId = '33333333-3333-4333-8333-333333333333'
const pendingEvent: SubmittedEvent = {
  id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  eventName: 'Community Workshop',
  description: 'A practical workshop',
  purpose: 'Learning',
  preferredStartDate: '2026-11-12T09:00:00+08:00',
  preferredEndDate: '2026-11-12T17:00:00+08:00',
  expectedAttendance: '120',
  venueRequirements: 'Auditorium',
  accessibilityNeeds: '',
  equipmentRequirements: '',
  registrationNeeds: '',
  status: 'Pending Safety Check',
  submittedAt: '2026-10-01T08:00:00+08:00',
  coordinatorId: '11111111-1111-4111-8111-111111111111',
  decision: null,
  decisionHistory: [],
  actionDetails: '',
  actionHistory: [],
}

beforeEach(() => {
  vi.resetAllMocks()
})

test('lists events awaiting a safety check, with name, schedule and attendance', async () => {
  vi.mocked(eventApi).mockResolvedValue({ events: [pendingEvent] })

  render(<SafetyChecksPage role="Safety Officer" safetyOfficerId={safetyOfficerId} onViewDetails={vi.fn()} />)

  expect(await screen.findByText('Community Workshop')).toBeInTheDocument()
  expect(screen.getByText('120 attendees')).toBeInTheDocument()
  expect(eventApi).toHaveBeenCalledWith(
    `/events?coordinatorId=${safetyOfficerId}&viewerRole=Safety+Officer&status=Pending+Safety+Check`,
  )
})

test('empty state when nothing is waiting', async () => {
  vi.mocked(eventApi).mockResolvedValue({ events: [] })

  render(<SafetyChecksPage role="Safety Officer" safetyOfficerId={safetyOfficerId} onViewDetails={vi.fn()} />)

  expect(await screen.findByText('No events are waiting for a safety check.')).toBeInTheDocument()
})

test('clicking an event opens its record', async () => {
  vi.mocked(eventApi).mockResolvedValue({ events: [pendingEvent] })
  const onViewDetails = vi.fn()

  render(<SafetyChecksPage role="Safety Officer" safetyOfficerId={safetyOfficerId} onViewDetails={onViewDetails} />)
  fireEvent.click(await screen.findByText('Community Workshop'))

  expect(onViewDetails).toHaveBeenCalledWith(pendingEvent.id)
})

test('a read failure is shown as an alert', async () => {
  vi.mocked(eventApi).mockRejectedValue(new Error('Unable to load events.'))

  render(<SafetyChecksPage role="Safety Officer" safetyOfficerId={safetyOfficerId} onViewDetails={vi.fn()} />)

  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load events.')
})

test.each(['Attendee', 'Event Organiser', 'Event Coordinator', 'Venue Staff', 'Technical Support'] as const)(
  'a %s opening the route directly sees the notice and reads nothing',
  (role) => {
    vi.mocked(eventApi).mockResolvedValue({ events: [pendingEvent] })

    render(<SafetyChecksPage role={role} safetyOfficerId={safetyOfficerId} onViewDetails={vi.fn()} />)

    expect(screen.getByText('The safety check queue is visible to Safety Officers.')).toBeInTheDocument()
    expect(screen.queryByText('Community Workshop')).not.toBeInTheDocument()
    // The request would otherwise claim viewerRole=Safety Officer for them.
    expect(eventApi).not.toHaveBeenCalled()
  },
)
