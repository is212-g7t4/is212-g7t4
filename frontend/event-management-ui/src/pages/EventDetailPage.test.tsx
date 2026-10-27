/**
 * # SCRUM-173 — Receive Venue Disruption Notifications
 *
 * As an Event Coordinator, I want to receive an in-app notification when a venue booking for an event assigned to me is affected, so that I know that alternative arrangements are required.
 * AC1: Given a rejection is ready for notification, then the notification is addressed to the coordinator assigned to that event when the notification is created.
 * AC2: The notification contains the event name, affected venue, closure start/end, rejection reason, and a link to the venue rejection.
 * AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.
 *
 * ## AC groups and layer
 * Cross-ticket regressions / fixture infrastructure: preserve original story ownership.
 * Only notification-specific additions support SCRUM-173 AC2; existing cases are not reattributed.
 * AC1 recipient selection is backend evidence, not inferred from these mocks.
 * AC2 content/navigation; AC3 supporting UI isolation/recovery.
 * FIRST: synthetic independent fixtures, controlled I/O/clocks, automatic assertions.
 * Historical tests are retrospective; no blanket historical TDD claim.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { assignmentApi, eventApi } from '../features/event/submission'
import type { SubmittedEvent } from '../features/event/submission'
import { fetchRegistrations } from '../features/registration/registrations'
import { EventDetailPage } from './EventDetailPage'
import { fetchSafetyFeedback, fetchSafetyResubmissionReadiness } from '../features/safety/safetyCheck'

vi.mock('../features/safety/safetyCheck', async (importOriginal) => ({
  ...await importOriginal<typeof import('../features/safety/safetyCheck')>(), fetchSafetyFeedback: vi.fn(),
  fetchSafetyResubmissionReadiness: vi.fn(),
}))

vi.mock('../features/event/submission', () => ({ eventApi: vi.fn(), assignmentApi: vi.fn() }))
vi.mock('../features/registration/registrations', () => ({ fetchRegistrations: vi.fn() }))
vi.mock('../features/venue/VenueBookingsPanel', () => ({
  VenueBookingsPanel: () => <section aria-label="Venue bookings" />,
}))
// SCRUM-149: this file covers *who* gets the submit panel (AC5) and where it
// sits; the panel's own behaviour is SafetySubmitPanel.test.tsx.
vi.mock('../features/safety/SafetySubmitPanel', () => ({
  SafetySubmitPanel: () => <h4>Submit for safety check</h4>,
}))
// SCRUM-150: likewise, this file covers *who* gets the Approve panel (AC3,
// UI side); the panel's own behaviour is SafetyDecisionPanel.test.tsx.
vi.mock('../features/safety/SafetyDecisionPanel', () => ({
  SafetyDecisionPanel: () => <h4>Operational Safety Check</h4>,
}))
vi.mock('../features/safety/SafetyReview', () => ({
  SafetyReview: () => <h3>Safety review information</h3>,
}))
// SCRUM-153: and likewise, this file covers *who* gets the Edit details button
// and what the action history renders; the dialog's two-step save is
// EventEditDialog.test.tsx.
vi.mock('../features/event/EventEditDialog', () => ({
  EventEditDialog: ({ onCancel }: { onCancel: () => void }) => <div role="dialog" aria-label="Edit event details">
    <button type="button" onClick={onCancel}>Cancel</button>
  </div>,
}))

const coordinatorId = '11111111-1111-4111-8111-111111111111'
const event: SubmittedEvent = {
  id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  eventName: 'Community Workshop',
  description: 'A practical workshop',
  purpose: 'Learning',
  preferredStartDate: '2026-10-10T09:00:00+08:00',
  preferredEndDate: '2026-10-10T12:00:00+08:00',
  expectedAttendance: '30',
  venueRequirements: 'Seminar room',
  accessibilityNeeds: 'Wheelchair access',
  equipmentRequirements: 'Projector',
  registrationNeeds: 'Online registration',
  status: 'Rejected',
  submittedAt: '2026-10-01T08:00:00+08:00',
  coordinatorId,
  decision: {
    status: 'Rejected',
    coordinatorId,
    decidedAt: '2026-10-02T10:00:00+08:00',
    reason: 'Date unavailable',
  },
  decisionHistory: [],
  actionDetails: 'Venue availability checked.',
  actionHistory: [{
    status: 'Rejected',
    details: 'Venue availability checked.',
    coordinatorId,
    recordedAt: '2026-10-02T10:00:00+08:00',
  }],
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(eventApi).mockResolvedValue(event)
  vi.mocked(fetchRegistrations).mockResolvedValue([])
  vi.mocked(fetchSafetyFeedback).mockResolvedValue([])
  vi.mocked(fetchSafetyResubmissionReadiness).mockResolvedValue({ ready: false, eventStatus: 'Safety Changes Requested', outstanding: [] })
})

test('shows the selected event status and full recorded details', async () => {
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)

  expect(await screen.findByRole('heading', { name: 'Community Workshop' })).toBeInTheDocument()
  expect(screen.getByText('Rejected', { selector: '.status-badge' })).toBeInTheDocument()
  expect(screen.getByText('A practical workshop')).toBeInTheDocument()
  expect(screen.getByText('Learning')).toBeInTheDocument()
  expect(screen.getByText('Seminar room')).toBeInTheDocument()
  expect(screen.getByText('Wheelchair access')).toBeInTheDocument()
  expect(screen.getByText('Projector')).toBeInTheDocument()
  expect(screen.getByText('Online registration')).toBeInTheDocument()
  expect(screen.getByDisplayValue('Venue availability checked.')).toBeInTheDocument()
  expect(screen.getByText('Venue availability checked.', { selector: 'dd' })).toBeInTheDocument()
  expect(screen.getByText(/Assigned to/)).toHaveTextContent('Alicia Tan')
  expect(eventApi).toHaveBeenCalledWith(`/events/${event.id}?coordinatorId=${coordinatorId}`)
  expect(fetchRegistrations).not.toHaveBeenCalled()
})

// Assign coordinator: the detail page records the current coordinator, who
// assigned them and when.
test('shows who assigned the coordinator and when', async () => {
  const leadId = '33333333-3333-4333-8333-333333333333'
  vi.mocked(eventApi).mockResolvedValue({ ...event, assignedBy: leadId, assignedAt: '2026-10-01T09:30:00+00:00' })
  const names: Record<string, string> = { [coordinatorId]: 'Alicia Tan', [leadId]: 'Grace Lee' }
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={(id) => (id ? names[id] ?? null : null)} backLabel="my events" onBack={vi.fn()} />)

  await screen.findByRole('heading', { name: 'Community Workshop' })
  const footnote = screen.getByText(/Assigned to/)
  expect(footnote).toHaveTextContent('Assigned to Alicia Tan by Grace Lee on')
  expect(footnote).toHaveTextContent(new Date('2026-10-01T09:30:00+00:00').toLocaleString('en-SG', { timeZone: 'Asia/Singapore' }) + ' SGT')
})

test('an event without an assignment record shows no assigner', async () => {
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)

  await screen.findByRole('heading', { name: 'Community Workshop' })
  expect(screen.getByText(/Assigned to/)).not.toHaveTextContent(/ by /)
})

// Reassign coordinator: who sees the control, what is recorded, and that the
// previous coordinator loses the ability to manage the event.
const leadId = '33333333-3333-4333-8333-333333333333'
const newCoordinatorId = '22222222-2222-4222-8222-222222222222'
const names: Record<string, string> = { [coordinatorId]: 'Alicia Tan', [leadId]: 'Grace Lee', [newCoordinatorId]: 'Marcus Lim' }
const resolveName = (id: string | null | undefined) => (id ? names[id] ?? null : null)

test.each(['Under Review', 'Approved', 'Pending Safety Check', 'Confirmed', 'Safety Changes Requested'] as const)('the Lead can reassign a %s event', async (status) => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, status, decision: null })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator Lead" currentCoordinatorId={leadId} currentCoordinatorName="Grace Lee" resolveUserName={resolveName} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })
  expect(screen.getByRole('button', { name: 'Reassign Coordinator' })).toBeInTheDocument()
})

test.each(['Rejected', 'Cancelled'] as const)('a %s event offers no reassignment, even to the Lead', async (status) => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, status })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator Lead" currentCoordinatorId={leadId} currentCoordinatorName="Grace Lee" resolveUserName={resolveName} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })
  expect(screen.queryByRole('button', { name: /reassign/i })).not.toBeInTheDocument()
})

test('an Event Coordinator who is not the Lead sees no Reassign option on the detail page', async () => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, status: 'Under Review', decision: null })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={resolveName} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })
  expect(screen.queryByRole('button', { name: /reassign/i })).not.toBeInTheDocument()
})

test('the detail page records the Lead, previous coordinator, new coordinator and time', async () => {
  vi.mocked(eventApi).mockResolvedValue({
    ...event, status: 'Under Review', decision: null, coordinatorId: newCoordinatorId,
    previousCoordinatorId: coordinatorId, assignedBy: leadId, assignedAt: '2026-10-16T13:05:00+00:00',
  })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator Lead" currentCoordinatorId={leadId} currentCoordinatorName="Grace Lee" resolveUserName={resolveName} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  const footnote = screen.getByText(/Reassigned from/)
  expect(footnote).toHaveTextContent('Reassigned from Alicia Tan to Marcus Lim by Grace Lee on')
  expect(footnote).toHaveTextContent(new Date('2026-10-16T13:05:00+00:00').toLocaleString('en-SG', { timeZone: 'Asia/Singapore' }) + ' SGT')
})

test('after a reassignment the Lead sees the new coordinator recorded straight away', async () => {
  const before = { ...event, status: 'Under Review' as const, decision: null }
  vi.mocked(eventApi).mockResolvedValue(before)
  vi.mocked(assignmentApi)
    .mockResolvedValueOnce({ coordinators: [
      { user_id: coordinatorId, username: 'Alicia Tan', email: 'a@example.com', role: 'Event Coordinator', organization: '', contact_details: '' },
      { user_id: newCoordinatorId, username: 'Marcus Lim', email: 'm@example.com', role: 'Event Coordinator', organization: '', contact_details: '' },
    ] })
    .mockResolvedValueOnce({ ...before, coordinatorId: newCoordinatorId, previousCoordinatorId: coordinatorId, assignedBy: leadId, assignedAt: '2026-10-16T13:05:00+00:00' })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator Lead" currentCoordinatorId={leadId} currentCoordinatorName="Grace Lee" resolveUserName={resolveName} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  fireEvent.click(screen.getByRole('button', { name: 'Reassign Coordinator' }))
  await screen.findByRole('option', { name: /Marcus Lim/ })
  fireEvent.change(screen.getByLabelText('New coordinator'), { target: { value: newCoordinatorId } })
  fireEvent.click(screen.getByRole('button', { name: 'Confirm Reassignment' }))

  expect(await screen.findByText(/Reassigned from/)).toHaveTextContent('Reassigned from Alicia Tan to Marcus Lim by Grace Lee')
})

test('the previous coordinator can no longer manage a reassigned event', async () => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, status: 'Under Review', decision: null, coordinatorId: newCoordinatorId, previousCoordinatorId: coordinatorId })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={resolveName} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(screen.getByText('Only the assigned Event Coordinator can update this event.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Save progress' })).not.toBeInTheDocument()
  expect(screen.queryByRole('region', { name: 'Venue bookings' })).not.toBeInTheDocument()
})

test('assigned coordinator updates the status and action details', async () => {
  const submittedEvent: SubmittedEvent = {
    ...event,
    status: 'Under Review',
    decision: null,
    actionDetails: 'Initial review completed.',
    actionHistory: [],
  }
  vi.mocked(eventApi).mockResolvedValueOnce(submittedEvent).mockResolvedValueOnce({
    ...submittedEvent,
    status: 'Approved',
    actionDetails: 'Venue and equipment confirmed.',
    actionHistory: [{
      status: 'Approved',
      details: 'Venue and equipment confirmed.',
      coordinatorId,
      recordedAt: '2026-10-03T10:00:00+08:00',
    }],
  })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'Approved' } })
  fireEvent.change(screen.getByLabelText('Action details'), { target: { value: 'Venue and equipment confirmed.' } })
  expect(screen.getByText('Unsaved changes')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Save progress' }))

  await waitFor(() => expect(eventApi).toHaveBeenLastCalledWith(
    `/events/${event.id}/progress`,
    { coordinatorId, status: 'Approved', actionDetails: 'Venue and equipment confirmed.' },
    'PATCH',
  ))
  expect(await screen.findByText('Event progress updated successfully.')).toBeInTheDocument()
  expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument()
})

test('rejected event status cannot be changed while action details remain editable', async () => {
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)

  await screen.findByRole('heading', { name: 'Community Workshop' })
  const status = screen.getByLabelText('Status')
  expect(status).toHaveValue('Rejected')
  expect(status.querySelectorAll('option')).toHaveLength(1)
  expect(status).toHaveTextContent('Rejected')

  fireEvent.change(screen.getByLabelText('Action details'), { target: { value: 'Follow-up recorded.' } })
  expect(screen.getByText('Unsaved changes')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Save progress' })).toBeEnabled()
})

// SCRUM-152 AC1: replaces "approved event can move to confirmed" — 'Confirmed'
// is the preparation stage and only the safety workflow sets it, so the
// coordinator is told what has to happen instead of being offered a dead option.
test('approved event offers only Approved and says to submit for safety check', async () => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, status: 'Approved' })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  const status = screen.getByLabelText('Status')
  expect(status.querySelectorAll('option')).toHaveLength(1)
  expect(status).toHaveTextContent('Approved')
  // 'Confirmed' isn't offered at all, not even as a disabled option.
  expect(screen.queryByRole('option', { name: 'Confirmed' })).not.toBeInTheDocument()
  expect(screen.getByRole('note')).toHaveTextContent(
    'Submit this event for safety check for it to progress to Confirmed.',
  )
})

test('pending safety check event shows the waiting reason', async () => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, status: 'Pending Safety Check' })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(screen.getByRole('note')).toHaveTextContent(
    "This event is waiting for the Safety Officer's decision.",
  )
})

test('SCRUM-150 AC3: a Safety Officer sees the Approve panel on a pending event', async () => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, status: 'Pending Safety Check' })
  render(<EventDetailPage eventId={event.id} role="Safety Officer" currentCoordinatorId="33333333-3333-4333-8333-333333333333" currentCoordinatorName="Nurul Huda" resolveUserName={() => 'Nurul Huda'} backLabel="safety checks" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(screen.getByRole('heading', { name: 'Operational Safety Check' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Safety review information' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Edit details' })).not.toBeInTheDocument()
  // The generic waiting note is the coordinator's message, not shown here.
  expect(screen.queryByText("This event is waiting for the Safety Officer's decision.")).not.toBeInTheDocument()
})

test('SCRUM-150 AC3: a Safety Officer sees no Approve panel once the event is Confirmed', async () => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, status: 'Confirmed' })
  render(<EventDetailPage eventId={event.id} role="Safety Officer" currentCoordinatorId="33333333-3333-4333-8333-333333333333" currentCoordinatorName="Nurul Huda" resolveUserName={() => 'Nurul Huda'} backLabel="safety checks" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(screen.queryByRole('heading', { name: 'Operational Safety Check' })).not.toBeInTheDocument()
})

test('an Event Coordinator sees no Approve panel on a pending event', async () => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, status: 'Pending Safety Check' })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(screen.queryByRole('heading', { name: 'Operational Safety Check' })).not.toBeInTheDocument()
})

test('safety changes requested event says what must happen', async () => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, status: 'Safety Changes Requested' })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(screen.getByRole('note')).toHaveTextContent(
    'The Safety Officer has requested changes that must be made and resubmitted.',
  )
})

test('API block on confirming is shown to the coordinator', async () => {
  const blocked = 'Submit this event for safety check for it to progress to Confirmed.'
  vi.mocked(eventApi)
    .mockResolvedValueOnce({ ...event, status: 'Approved' })
    .mockRejectedValueOnce(new Error(blocked))
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  // The dropdown gives no way to ask for this, so drive the save the way a
  // crafted request would and check the API's reason reaches the coordinator.
  fireEvent.change(screen.getByLabelText('Action details'), { target: { value: 'Starting preparation.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save progress' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(blocked)
})

// Boundary: the gate must not over-block an event that already passed its check.
test('a confirmed event has reached preparation and records progress', async () => {
  const confirmedEvent: SubmittedEvent = { ...event, status: 'Confirmed' }
  vi.mocked(eventApi).mockResolvedValueOnce(confirmedEvent).mockResolvedValueOnce({
    ...confirmedEvent,
    actionDetails: 'Preparation under way.',
  })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  // Already past the gate, so no hint — and nothing further to move to.
  expect(screen.queryByRole('note')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Status')).toHaveValue('Confirmed')
  fireEvent.change(screen.getByLabelText('Action details'), { target: { value: 'Preparation under way.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save progress' }))

  await waitFor(() => expect(eventApi).toHaveBeenLastCalledWith(
    `/events/${event.id}/progress`,
    { coordinatorId, status: 'Confirmed', actionDetails: 'Preparation under way.' },
    'PATCH',
  ))
  expect(await screen.findByText('Event progress updated successfully.')).toBeInTheDocument()
})

test.each(['Venue Staff', 'Technical Support'] as const)('%s views event details without edit controls', async (role) => {
  render(<EventDetailPage eventId={event.id} role={role} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" backLabel="my events" onBack={vi.fn()} />)

  expect(await screen.findByRole('heading', { name: 'Community Workshop' })).toBeInTheDocument()
  expect(eventApi).toHaveBeenCalledWith(
    `/events/${event.id}?coordinatorId=${coordinatorId}&viewerRole=${role.replace(' ', '+')}`,
  )
  expect(screen.getByText('Only the assigned Event Coordinator can update this event.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Save progress' })).not.toBeInTheDocument()
})

test('does not load event details for an attendee', () => {
  render(<EventDetailPage eventId={event.id} role="Attendee" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" backLabel="my events" onBack={vi.fn()} />)

  expect(screen.getByText('Event information is visible to Event Coordinators, Venue Staff, Technical Support, and Safety Officers.')).toBeInTheDocument()
  expect(eventApi).not.toHaveBeenCalled()
})

// --- SCRUM-149: who sees the submit-for-safety-check panel (AC5) -------------

const safetyPanel = () => screen.queryByRole('heading', { name: 'Submit for safety check' })

test('AC5: the assigned coordinator of an Approved event can submit it', async () => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, status: 'Approved' })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(safetyPanel()).toBeInTheDocument()
})

test('AC5: a coordinator who is not the assigned one never sees the panel', async () => {
  vi.mocked(eventApi).mockResolvedValue({
    ...event, status: 'Approved', coordinatorId: '22222222-2222-4222-8222-222222222222',
  })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(safetyPanel()).not.toBeInTheDocument()
})

test('AC5: the Lead viewing another coordinator\'s event cannot submit', async () => {
  vi.mocked(eventApi).mockResolvedValue({
    ...event, status: 'Approved', coordinatorId: '22222222-2222-4222-8222-222222222222',
  })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator Lead" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alice Tan" resolveUserName={() => 'Alice Tan'} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(safetyPanel()).not.toBeInTheDocument()
})

test.each(['Venue Staff', 'Technical Support'] as const)('AC5: %s cannot submit for a safety check', async (role) => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, status: 'Approved' })
  render(<EventDetailPage eventId={event.id} role={role} currentCoordinatorId={coordinatorId} currentCoordinatorName="Siti" backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(safetyPanel()).not.toBeInTheDocument()
})

test.each(['Submitted', 'Under Review', 'Clarification Requested', 'Rejected', 'Confirmed', 'Safety Changes Requested'] as const)(
  'the panel is hidden on a %s event', async (status) => {
    vi.mocked(eventApi).mockResolvedValue({ ...event, status })
    render(<EventDetailPage eventId={event.id} role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)
    await screen.findByRole('heading', { name: 'Community Workshop' })

    expect(safetyPanel()).not.toBeInTheDocument()
  },
)

test('AC1: a pending event shows when it was submitted, and no submit button', async () => {
  vi.mocked(eventApi).mockResolvedValue({
    ...event,
    status: 'Pending Safety Check',
    actionHistory: [{
      status: 'Pending Safety Check',
      details: 'Submitted for Operational Safety Check (round 1).',
      coordinatorId,
      recordedAt: '2026-10-05T02:00:00+00:00',
    }],
  })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(safetyPanel()).not.toBeInTheDocument()
  expect(screen.getByText(/Submitted for safety check on/)).toHaveTextContent('05/10/2026')
})

// --- SCRUM-151: booking panel hidden on Cancelled, history shows reason/areas

test('SCRUM-151 AC5: the venue bookings panel is hidden once the event is Cancelled', async () => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, status: 'Cancelled', coordinatorId })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(screen.queryByLabelText('Venue bookings')).not.toBeInTheDocument()
})

test('the venue bookings panel still shows for every other status', async () => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, status: 'Approved', coordinatorId })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(screen.getByLabelText('Venue bookings')).toBeInTheDocument()
})

test('SCRUM-151 AC6: action history shows the reason and areas for a change request', async () => {
  vi.mocked(eventApi).mockResolvedValue({
    ...event,
    status: 'Safety Changes Requested',
    actionHistory: [{
      status: 'Safety Changes Requested',
      details: 'Operational Safety Check: changes requested (round 1) for venue arrangement, event details.',
      coordinatorId,
      recordedAt: '2026-10-05T02:00:00+00:00',
      remarks: 'Needs another look.',
      areas: ['venue arrangement', 'event details'],
    }],
  })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(screen.getByText('Areas: venue arrangement, event details')).toBeInTheDocument()
  expect(screen.getByText('Reason: Needs another look.')).toBeInTheDocument()
})

test.each([
  ['Event Coordinator', coordinatorId, 'Safety Changes Requested', true],
  ['Event Coordinator', 'other-coordinator', 'Safety Changes Requested', false],
  ['Event Coordinator Lead', coordinatorId, 'Safety Changes Requested', true],
  ['Event Coordinator Lead', 'other-lead', 'Safety Changes Requested', false],
  ['Safety Officer', coordinatorId, 'Safety Changes Requested', false],
  ['Event Coordinator', coordinatorId, 'Approved', false],
] as const)('feedback access: %s / %s / %s', async (role, viewerId, status, visible) => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, status })
  render(<EventDetailPage eventId={event.id} role={role} currentCoordinatorId={viewerId} backLabel="events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: event.eventName })
  expect(Boolean(screen.queryByRole('region', { name: 'Safety Officer feedback' }))).toBe(visible)
  if (visible) await waitFor(() => expect(fetchSafetyFeedback).toHaveBeenCalledWith(event.id, coordinatorId))
  else expect(fetchSafetyFeedback).not.toHaveBeenCalled()
})

test('SCRUM-151 AC6: action history shows the reason for a rejection, with no areas', async () => {
  vi.mocked(eventApi).mockResolvedValue({
    ...event,
    status: 'Cancelled',
    actionHistory: [{
      status: 'Cancelled',
      details: 'Operational Safety Check rejected (round 1). The event is cancelled.',
      coordinatorId,
      recordedAt: '2026-10-05T02:00:00+00:00',
      remarks: 'Unsafe egress plan.',
    }],
  })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(screen.getByText('Reason: Unsafe egress plan.')).toBeInTheDocument()
  expect(screen.queryByText(/^Areas:/)).not.toBeInTheDocument()
})

// --- SCRUM-153: the Edit details button and the withdrawal in the history ----
// This file covers *who* gets the button and what the history renders; the
// dialog's own behaviour is EventEditDialog.test.tsx.

const renderPage = (role: Parameters<typeof EventDetailPage>[0]['role'] = 'Event Coordinator') =>
  render(<EventDetailPage eventId={event.id} role={role} currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)

const editButton = () => screen.queryByRole('button', { name: 'Edit details' })

test.each(['Submitted', 'Under Review', 'Approved', 'Pending Safety Check', 'Confirmed', 'Safety Changes Requested'] as const)(
  'SCRUM-153: the assigned coordinator can edit a %s event',
  async (status) => {
    vi.mocked(eventApi).mockResolvedValue({ ...event, status })
    renderPage()

    await screen.findByRole('heading', { name: 'Community Workshop' })

    expect(editButton()).toBeInTheDocument()
  },
)

test.each(['Rejected', 'Cancelled', 'Clarification Requested', 'Amendment Requested'] as const)(
  'SCRUM-153: a %s event has no details left to edit',
  async (status) => {
    vi.mocked(eventApi).mockResolvedValue({ ...event, status })
    renderPage()

    await screen.findByRole('heading', { name: 'Community Workshop' })

    expect(editButton()).not.toBeInTheDocument()
  },
)

test('SCRUM-153: only the assigned coordinator is offered the edit', async () => {
  vi.mocked(eventApi).mockResolvedValue({
    ...event,
    status: 'Confirmed',
    coordinatorId: '22222222-2222-4222-8222-222222222222',
  })
  renderPage()

  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(editButton()).not.toBeInTheDocument()
})

test('SCRUM-20: the Lead can edit an event that has no assigned coordinator', async () => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, status: 'Approved', coordinatorId: null })
  renderPage('Event Coordinator Lead')

  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(editButton()).toBeInTheDocument()
})

test('SCRUM-20: the Lead cannot edit an event assigned to another coordinator', async () => {
  vi.mocked(eventApi).mockResolvedValue({
    ...event,
    status: 'Approved',
    coordinatorId: '22222222-2222-4222-8222-222222222222',
  })
  renderPage('Event Coordinator Lead')

  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(editButton()).not.toBeInTheDocument()
})

test('SCRUM-153: a Safety Officer does not edit the event details', async () => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, status: 'Confirmed' })
  renderPage('Safety Officer')

  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(editButton()).not.toBeInTheDocument()
})

test('SCRUM-153: Edit details opens the dialog and Cancel closes it again', async () => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, status: 'Confirmed' })
  renderPage()
  await screen.findByRole('heading', { name: 'Community Workshop' })

  fireEvent.click(editButton() as HTMLElement)
  expect(screen.getByRole('dialog', { name: 'Edit event details' })).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('dialog', { name: 'Edit event details' })).not.toBeInTheDocument()
  expect(editButton()).toBeInTheDocument()
})

test('SCRUM-153 AC3: a withdrawal entry is tagged and lists what changed', async () => {
  vi.mocked(eventApi).mockResolvedValue({
    ...event,
    status: 'Pending Safety Check',
    actionHistory: [{
      status: 'Pending Safety Check',
      details: 'Safety approval withdrawn because Date/time and Expected attendance changed after approval.',
      changedFields: ['preferredStartDate', 'preferredEndDate', 'expectedAttendance'],
      highImpactFields: ['preferredStartDate', 'preferredEndDate', 'expectedAttendance'],
      withdrawnSafetyCheckId: '55555555-5555-4555-8555-555555555555',
      coordinatorId,
      recordedAt: '2026-10-16T06:00:00+08:00',
    }],
  })
  renderPage()

  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(screen.getByText('Safety approval withdrawn')).toBeInTheDocument()
  // Both date fields read as one "Date/time", as the backend's labels do.
  expect(screen.getByText('Changed: Date/time, Expected attendance')).toBeInTheDocument()
  expect(screen.getByText(/Safety approval withdrawn because Date\/time/)).toBeInTheDocument()
})

test('SCRUM-153 AC2: a plain edit entry lists its fields without the withdrawal tag', async () => {
  vi.mocked(eventApi).mockResolvedValue({
    ...event,
    status: 'Confirmed',
    actionHistory: [{
      status: 'Confirmed',
      details: 'Event details updated: Event name, Purpose.',
      changedFields: ['eventName', 'purpose'],
      coordinatorId,
      recordedAt: '2026-10-16T06:00:00+08:00',
    }],
  })
  renderPage()

  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(screen.getByText('Changed: Event name, Purpose')).toBeInTheDocument()
  expect(screen.queryByText('Safety approval withdrawn')).not.toBeInTheDocument()
})

test.each(['Submitted', 'Under Review', 'Approved'] as const)(
  'change request story: an organiser can request changes while an event is %s',
  async (status) => {
    vi.mocked(eventApi).mockResolvedValue({ ...event, status, organiserId: coordinatorId })
    render(<EventDetailPage eventId={event.id} role="Event Organiser" currentCoordinatorId={coordinatorId} backLabel="my events" onBack={vi.fn()} />)
    await screen.findByRole('heading', { name: 'Community Workshop' })
    expect(screen.getByRole('button', { name: 'Request changes' })).toBeInTheDocument()
  },
)

test.each(['Clarification Requested', 'Amendment Requested', 'Rejected', 'Pending Safety Check', 'Confirmed', 'Safety Changes Requested', 'Cancelled'] as const)(
  'change request story: an organiser cannot request changes while an event is %s',
  async (status) => {
    vi.mocked(eventApi).mockResolvedValue({ ...event, status, organiserId: coordinatorId })
    render(<EventDetailPage eventId={event.id} role="Event Organiser" currentCoordinatorId={coordinatorId} backLabel="my events" onBack={vi.fn()} />)
    await screen.findByRole('heading', { name: 'Community Workshop' })
    expect(screen.queryByRole('button', { name: 'Request changes' })).not.toBeInTheDocument()
  },
)

/** SCRUM-173 review P2: public event-detail DOM; existing panel/write guards stay intact. */
test.each([
  { label: 'cancelled assigned event', status: 'Cancelled' as const, role: 'Event Coordinator' as const, viewer: coordinatorId, assigned: coordinatorId },
  { label: 'viewable reassigned event as Lead', status: 'Under Review' as const, role: 'Event Coordinator Lead' as const, viewer: leadId, assigned: newCoordinatorId },
])('linked request explains unavailable access for $label', async ({ status, role, viewer, assigned }) => {
  vi.mocked(eventApi).mockResolvedValue({ ...event, status, coordinatorId: assigned, previousCoordinatorId: coordinatorId })
  render(<EventDetailPage eventId={event.id} targetBookingId="40000000-0000-0000-0000-000000000001" role={role} currentCoordinatorId={viewer} backLabel="notifications" onBack={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Community Workshop' })
  expect(screen.getByRole('status')).toHaveTextContent('The linked venue request is unavailable or you do not have access to it.')
  expect(screen.queryByLabelText('Venue bookings')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Edit details' })).not.toBeInTheDocument()
  if (viewer !== assigned) expect(screen.queryByRole('button', { name: 'Save progress' })).not.toBeInTheDocument()
  expect(vi.mocked(eventApi).mock.calls.every(call => call.length === 1)).toBe(true)
})

// SCRUM-16 AC3: while the organiser amends, the coordinator's own progress and
// detail edits are locked, and the open round is shown.
test('SCRUM-16: progress and edits are locked while an amendment is open', async () => {
  vi.mocked(eventApi).mockResolvedValue({
    ...event,
    status: 'Amendment Requested',
    decision: null,
    amendmentHistory: [{
      id: 'amendment-1',
      fields: ['expectedAttendance'],
      reason: 'The room holds 20.',
      requestedBy: coordinatorId,
      requestedAt: '2026-10-20T01:00:00+00:00',
      resubmittedBy: null,
      resubmittedAt: null,
      changes: null,
      note: null,
    }],
  })
  render(<EventDetailPage eventId={event.id} role="Event Coordinator" currentCoordinatorId={coordinatorId} currentCoordinatorName="Alicia Tan" resolveUserName={() => 'Alicia Tan'} backLabel="my events" onBack={vi.fn()} />)

  await screen.findByRole('heading', { name: 'Community Workshop' })

  expect(screen.getByText('Progress and event details are locked while the Event Organiser amends the flagged fields.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Save progress' })).not.toBeInTheDocument()
  expect(editButton()).not.toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Amendments' })).toBeInTheDocument()
  expect(screen.getByText('The room holds 20.')).toBeInTheDocument()
  expect(screen.getByText("Awaiting the Event Organiser's amendment.")).toBeInTheDocument()
})
