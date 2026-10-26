import { expect, test } from 'vitest'
import { ALLOWED_TRANSITIONS, PREPARATION_STATUS, canReassign, isAwaitingOrganiser, safetyBlockMessage, showsSafetyHint } from './eventStatus'
import type { SubmittedEvent } from './submission'
import type { EventStatus } from './submission'

// SCRUM-152: these must stay in step with ALLOWED_TRANSITIONS and
// SAFETY_BLOCK_MESSAGES in services/event-service/app/models.py.

test('the transition table matches the backend', () => {
  expect(ALLOWED_TRANSITIONS).toEqual({
    Submitted: ['Submitted', 'Under Review'],
    'Under Review': ['Under Review', 'Approved', 'Rejected'],
    'Clarification Requested': [],
    'Amendment Requested': [],
    Approved: ['Approved'],
    Rejected: ['Rejected'],
    'Pending Safety Check': ['Pending Safety Check'],
    Confirmed: ['Confirmed'],
    'Safety Changes Requested': ['Safety Changes Requested'],
    Cancelled: ['Cancelled'],
  })
})

test("AC1: no status lets a coordinator move an event into 'Confirmed'", () => {
  for (const [status, targets] of Object.entries(ALLOWED_TRANSITIONS)) {
    // 'Confirmed' lists itself for action-detail saves; clarification is the
    // deliberate exception and is locked behind its response endpoint.
    if (status === PREPARATION_STATUS) continue
    expect(targets).not.toContain(PREPARATION_STATUS)
  }
})

test('AC1: an approved event offers only itself', () => {
  expect(ALLOWED_TRANSITIONS.Approved).toEqual(['Approved'])
})

test('Confirmed is the preparation stage, with nothing after it', () => {
  expect(PREPARATION_STATUS).toBe('Confirmed')
  expect(ALLOWED_TRANSITIONS.Confirmed).toEqual(['Confirmed'])
})

test.each([
  ['Approved', 'Submit this event for safety check for it to progress to Confirmed.'],
  ['Submitted', 'This event must be approved and pass its Operational Safety Check before it can progress to Confirmed.'],
  ['Under Review', 'This event must be approved and pass its Operational Safety Check before it can progress to Confirmed.'],
  ['Clarification Requested', "This event is waiting for the Event Organiser's clarification response."],
  ['Amendment Requested', "This event is waiting for the Event Organiser's amendment."],
  ['Rejected', "This event was rejected, so it can't progress to Confirmed."],
  ['Pending Safety Check', "This event is waiting for the Safety Officer's decision."],
  ['Safety Changes Requested', 'The Safety Officer has requested changes that must be made and resubmitted.'],
  ['Cancelled', "This event was cancelled after its safety check, so it can't progress to Confirmed."],
] as const)('AC1: %s explains itself', (status, message) => {
  expect(safetyBlockMessage(status)).toBe(message)
})

test('the hint shows only where the coordinator can act on it', () => {
  const actionable: EventStatus[] = ['Approved', 'Pending Safety Check', 'Safety Changes Requested']
  expect(actionable.every(showsSafetyHint)).toBe(true)
  // Confirmed has progressed; the rest aren't at the safety stage yet.
  const quiet: EventStatus[] = ['Submitted', 'Under Review', 'Clarification Requested', 'Rejected', 'Confirmed', 'Cancelled']
  expect(quiet.some(showsSafetyHint)).toBe(false)
})

// SCRUM-16: an open amendment locks the request with its organiser.
test('SCRUM-16 AC4: an event under amendment keeps its coordinator', () => {
  const event = { coordinatorId: '11111111-1111-4111-8111-111111111111' } as SubmittedEvent
  expect(canReassign({ ...event, status: 'Amendment Requested' })).toBe(false)
  expect(canReassign({ ...event, status: 'Under Review' })).toBe(true)
})

test('SCRUM-16: clarification and amendment both wait on the organiser', () => {
  expect(isAwaitingOrganiser('Clarification Requested')).toBe(true)
  expect(isAwaitingOrganiser('Amendment Requested')).toBe(true)
  const others: EventStatus[] = ['Submitted', 'Under Review', 'Approved', 'Rejected', 'Confirmed']
  expect(others.some(isAwaitingOrganiser)).toBe(false)
})
