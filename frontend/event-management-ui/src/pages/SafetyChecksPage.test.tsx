import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { fetchSafetyQueue } from '../features/safety/safetyCheck'
import type { SafetyQueueItem } from '../features/safety/safetyCheck'
import { SafetyChecksPage } from './SafetyChecksPage'

// SCRUM-162: the Safety Officer's queue of events awaiting a safety check.

vi.mock('../features/safety/safetyCheck', () => ({ fetchSafetyQueue: vi.fn() }))

const safetyOfficerId = '33333333-3333-4333-8333-333333333333'
const queued: SafetyQueueItem = {
  eventId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  eventName: 'Community Workshop',
  preferredStartDate: '2026-11-12T09:00:00+08:00',
  preferredEndDate: '2026-11-12T17:00:00+08:00',
  expectedAttendance: '120',
  venues: [{ id: 'v1', name: 'Main Hall' }],
  safetyCheckId: 'record-1',
  submittedAt: '2026-11-01T02:30:00+00:00',
  roundNumber: 1,
  resubmission: false,
}

const renderPage = (onViewDetails = vi.fn()) =>
  render(<SafetyChecksPage role="Safety Officer" safetyOfficerId={safetyOfficerId} onViewDetails={onViewDetails} />)

beforeEach(() => {
  vi.resetAllMocks()
})

test('AC2: each entry shows name, date/time, venue, attendance and submission date', async () => {
  vi.mocked(fetchSafetyQueue).mockResolvedValue([queued])

  renderPage()

  expect(await screen.findByText('Community Workshop')).toBeInTheDocument()
  expect(screen.getByText('Thu, 12 Nov · 9:00 am – 5:00 pm')).toBeInTheDocument()
  expect(screen.getByText('Main Hall · 120 attendees')).toBeInTheDocument()
  expect(screen.getByText('Submitted 1 Nov 2026, 10:30 am')).toBeInTheDocument()
  expect(fetchSafetyQueue).toHaveBeenCalledWith(safetyOfficerId)
})

test('AC2: every venue is listed', async () => {
  vi.mocked(fetchSafetyQueue).mockResolvedValue([
    { ...queued, venues: [{ id: 'v1', name: 'Main Hall' }, { id: 'v2', name: 'Seminar Room 2' }] },
  ])

  renderPage()

  expect(await screen.findByText('Main Hall, Seminar Room 2 · 120 attendees')).toBeInTheDocument()
})

test('an event with no venue and no attendance still renders', async () => {
  vi.mocked(fetchSafetyQueue).mockResolvedValue([{ ...queued, venues: [], expectedAttendance: '', submittedAt: null }])

  renderPage()

  expect(await screen.findByText('No venue booked · 0 attendees')).toBeInTheDocument()
  expect(screen.getByText('Submission date unknown')).toBeInTheDocument()
})

test('AC2: entries keep the order the service returns, nearest event first', async () => {
  vi.mocked(fetchSafetyQueue).mockResolvedValue([
    { ...queued, eventId: 'a', eventName: 'November' },
    { ...queued, eventId: 'b', eventName: 'December', preferredStartDate: '2026-12-01T09:00:00+08:00' },
  ])

  renderPage()

  await screen.findByText('November')
  const names = screen.getAllByRole('button').map((button) => button.querySelector('strong')?.textContent)
  expect(names).toEqual(['November', 'December'])
})

test('AC3: a resubmitted event is labelled as a resubmission', async () => {
  vi.mocked(fetchSafetyQueue).mockResolvedValue([
    queued,
    { ...queued, eventId: 'b', eventName: 'Second Try', roundNumber: 2, resubmission: true },
  ])

  renderPage()

  const second = (await screen.findByText('Second Try')).closest('button')!
  expect(second).toHaveTextContent('Resubmission')
  expect(screen.getByText('Community Workshop').closest('button')).not.toHaveTextContent('Resubmission')
})

test('empty state when nothing is waiting', async () => {
  vi.mocked(fetchSafetyQueue).mockResolvedValue([])

  renderPage()

  expect(await screen.findByText('No events are waiting for a safety check.')).toBeInTheDocument()
})

test('clicking an event opens its record', async () => {
  vi.mocked(fetchSafetyQueue).mockResolvedValue([queued])
  const onViewDetails = vi.fn()

  renderPage(onViewDetails)
  fireEvent.click(await screen.findByText('Community Workshop'))

  expect(onViewDetails).toHaveBeenCalledWith(queued.eventId)
})

test('a read failure is shown as an alert', async () => {
  vi.mocked(fetchSafetyQueue).mockRejectedValue(new Error('Unable to load the safety check queue right now.'))

  renderPage()

  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load the safety check queue right now.')
})

test.each(['Attendee', 'Event Organiser', 'Event Coordinator', 'Venue Staff', 'Technical Support'] as const)(
  'a %s opening the route directly sees the notice and reads nothing',
  (role) => {
    vi.mocked(fetchSafetyQueue).mockResolvedValue([queued])

    render(<SafetyChecksPage role={role} safetyOfficerId={safetyOfficerId} onViewDetails={vi.fn()} />)

    expect(screen.getByText('The safety check queue is visible to Safety Officers.')).toBeInTheDocument()
    expect(screen.queryByText('Community Workshop')).not.toBeInTheDocument()
    expect(fetchSafetyQueue).not.toHaveBeenCalled()
  },
)
