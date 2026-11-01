/**
 * SCRUM-149: the request shapes the safety panel sends, and how it reads the
 * two refusals it has to explain — AC2's `422` and AC4's `409`.
 */
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import {
  SafetySubmitError,
  approveSafetyCheck,
  fetchSafetyFeedback,
  fetchSafetyQueue,
  fetchSafetyReadiness,
  fetchSafetyReview,
  fetchSafetyResubmissionReadiness,
  rejectSafetyCheck,
  requestSafetyChanges,
  resubmitSafetyCheck,
  submitSafetyCheck,
  submittedForSafetyCheckAt,
} from './safetyCheck'
import type { SubmittedEvent } from '../event/submission'

const eventId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const coordinatorId = '11111111-1111-4111-8111-111111111111'
const officerId = '33333333-3333-4333-8333-333333333333'

const respond = (status: number, body: unknown) => vi.fn().mockResolvedValue({
  ok: status >= 200 && status < 300,
  status,
  json: () => Promise.resolve(body),
})

beforeEach(() => {
  vi.stubGlobal('fetch', respond(200, {}))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

test('readiness is read from Safety Check Service with both identifiers', async () => {
  const readiness = { ready: true, eventStatus: 'Approved', outstanding: [], openSafetyCheck: null }
  vi.stubGlobal('fetch', respond(200, readiness))

  expect(await fetchSafetyReadiness(eventId, coordinatorId)).toEqual(readiness)
  const [url] = vi.mocked(fetch).mock.calls[0]
  expect(String(url)).toBe(
    `http://localhost:5012/safety-checks/readiness?eventId=${eventId}&coordinatorId=${coordinatorId}`,
  )
})

test('AC1: feedback is read through the composite as the assigned coordinator', async () => {
  const safetyChecks = [{ roundNumber: 2, status: 'Changes Requested', remarks: 'Keep exits clear.', flags: [] }]
  vi.stubGlobal('fetch', respond(200, { safetyChecks }))
  expect(await fetchSafetyFeedback(eventId, coordinatorId)).toEqual(safetyChecks)
  expect(fetch).toHaveBeenCalledWith(
    `http://localhost:5012/safety-checks/feedback?eventId=${eventId}&coordinatorId=${coordinatorId}`, undefined,
  )
})

test('resubmission readiness uses the separate equipment-only endpoint', async () => {
  const readiness = { ready: true, eventStatus: 'Safety Changes Requested', outstanding: [] }
  vi.stubGlobal('fetch', respond(200, readiness))
  expect(await fetchSafetyResubmissionReadiness(eventId, coordinatorId)).toEqual(readiness)
  expect(fetch).toHaveBeenCalledWith(
    `http://localhost:5012/safety-checks/resubmit/readiness?eventId=${eventId}&coordinatorId=${coordinatorId}`, undefined,
  )
})

test('resubmission posts to its own workflow endpoint rather than saving progress', async () => {
  const body = { eventId, coordinatorId, equipmentPlacementNotes: 'Cables secured.' }
  vi.stubGlobal('fetch', respond(201, { safetyCheck: { roundNumber: 2 }, event: {} }))
  await resubmitSafetyCheck(body)
  const [url, init] = vi.mocked(fetch).mock.calls[0]
  expect(url).toBe('http://localhost:5012/safety-checks/resubmit')
  expect(init?.method).toBe('POST')
  expect(JSON.parse(String(init?.body))).toEqual(body)
})

test('SCRUM-162: the queue is read from Safety Check Service as the officer', async () => {
  const events = [{ eventId, eventName: 'Community Workshop', resubmission: false }]
  vi.stubGlobal('fetch', respond(200, { events }))

  expect(await fetchSafetyQueue(officerId)).toEqual(events)
  const [url] = vi.mocked(fetch).mock.calls[0]
  expect(String(url)).toBe(`http://localhost:5012/safety-checks/queue?safetyOfficerId=${officerId}`)
})

test('SCRUM-162: a queue refusal carries the service message', async () => {
  vi.stubGlobal('fetch', respond(403, { code: 'NOT_SAFETY_OFFICER', message: 'Only a Safety Officer can decide.' }))

  await expect(fetchSafetyQueue(officerId)).rejects.toMatchObject({
    code: 'NOT_SAFETY_OFFICER',
    message: 'Only a Safety Officer can decide.',
  })
})

test('SCRUM-163: the review is fetched from Safety Check Service as the officer', async () => {
  const review = { event: {}, safetyCheck: {}, venues: [], equipment: [], history: [] }
  vi.stubGlobal('fetch', respond(200, review))

  expect(await fetchSafetyReview(eventId, officerId)).toEqual(review)
  const [url] = vi.mocked(fetch).mock.calls[0]
  expect(String(url)).toBe(
    `http://localhost:5012/safety-checks/${eventId}/review?safetyOfficerId=${officerId}`,
  )
})

test('AC3: both note fields are sent with the submission', async () => {
  vi.stubGlobal('fetch', respond(201, { safetyCheck: { roundNumber: 1 }, event: {} }))

  await submitSafetyCheck({
    eventId,
    coordinatorId,
    equipmentPlacementNotes: 'Speakers either side of the stage.',
    crowdMovementNotes: 'Entry through Door A.',
  })

  const [url, init] = vi.mocked(fetch).mock.calls[0]
  expect(String(url)).toBe('http://localhost:5012/safety-checks')
  expect(init?.method).toBe('POST')
  expect(JSON.parse(String(init?.body))).toEqual({
    eventId,
    coordinatorId,
    equipmentPlacementNotes: 'Speakers either side of the stage.',
    crowdMovementNotes: 'Entry through Door A.',
  })
})

test('AC2: a 422 carries the outstanding arrangements so the panel can list them', async () => {
  const outstanding = [
    {
      type: 'venue', id: 'booking-a', status: 'Pending Review',
      label: 'Booking 12 Nov 2026 09:00–17:00 (120 people)',
      reason: 'Waiting for Venue Staff approval.',
    },
  ]
  vi.stubGlobal('fetch', respond(422, {
    code: 'ARRANGEMENTS_OUTSTANDING',
    message: "This event can't be submitted for a safety check until it has an approved venue booking and no venue booking or equipment request is still waiting for a decision.",
    outstanding,
  }))

  await expect(submitSafetyCheck({ eventId, coordinatorId })).rejects.toThrowError(
    SafetySubmitError,
  )
  await expect(submitSafetyCheck({ eventId, coordinatorId })).rejects.toMatchObject({
    code: 'ARRANGEMENTS_OUTSTANDING',
    outstanding,
  })
})

test('AC4: a 409 carries the open round so the panel can say when it was submitted', async () => {
  vi.stubGlobal('fetch', respond(409, {
    code: 'SAFETY_CHECK_ALREADY_PENDING',
    message: 'This event is already waiting for its safety check. It was submitted on 2026-11-01T02:30:00+00:00.',
    safetyCheck: { id: 'record-a', roundNumber: 1, status: 'Pending' },
  }))

  await expect(submitSafetyCheck({ eventId, coordinatorId })).rejects.toMatchObject({
    code: 'SAFETY_CHECK_ALREADY_PENDING',
    safetyCheck: { roundNumber: 1 },
  })
})

test('AC5: a 403 surfaces as an error with its code', async () => {
  vi.stubGlobal('fetch', respond(403, {
    code: 'NOT_ASSIGNED_COORDINATOR',
    message: "Only the event's assigned coordinator can submit it for a safety check.",
  }))

  await expect(fetchSafetyReadiness(eventId, coordinatorId)).rejects.toMatchObject({
    code: 'NOT_ASSIGNED_COORDINATOR',
    message: "Only the event's assigned coordinator can submit it for a safety check.",
  })
})

test('a failure with no JSON body still reads as an error', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: false,
    status: 502,
    json: () => Promise.reject(new Error('not JSON')),
  }))

  await expect(fetchSafetyReadiness(eventId, coordinatorId)).rejects.toThrowError(
    'Unable to complete the safety check request.',
  )
})

test('SCRUM-150 AC2: eventId, safetyOfficerId and remarks are sent to approve', async () => {
  vi.stubGlobal('fetch', respond(200, { safetyCheck: { roundNumber: 1 }, event: {} }))

  await approveSafetyCheck({ eventId, safetyOfficerId: officerId, remarks: 'Looks safe.' })

  const [url, init] = vi.mocked(fetch).mock.calls[0]
  expect(String(url)).toBe('http://localhost:5012/safety-checks/approve')
  expect(init?.method).toBe('POST')
  expect(JSON.parse(String(init?.body))).toEqual({
    eventId,
    safetyOfficerId: officerId,
    remarks: 'Looks safe.',
  })
})

test('SCRUM-150 AC3: a 409 when the event is not Pending Safety Check surfaces its code', async () => {
  vi.stubGlobal('fetch', respond(409, {
    code: 'EVENT_NOT_PENDING_SAFETY_CHECK',
    message: "Only an event 'Pending Safety Check' can be approved (current status: 'Approved').",
    currentStatus: 'Approved',
  }))

  await expect(approveSafetyCheck({ eventId, safetyOfficerId: officerId })).rejects.toMatchObject({
    code: 'EVENT_NOT_PENDING_SAFETY_CHECK',
  })
})

test('SCRUM-151 AC1: reason and flags are sent to request-changes', async () => {
  vi.stubGlobal('fetch', respond(200, { safetyCheck: { roundNumber: 1 }, event: {} }))

  await requestSafetyChanges({
    eventId,
    safetyOfficerId: officerId,
    reason: 'Needs another look.',
    flags: [{ area: 'venue arrangement', changeRequired: 'Move the stage.' }],
  })

  const [url, init] = vi.mocked(fetch).mock.calls[0]
  expect(String(url)).toBe('http://localhost:5012/safety-checks/request-changes')
  expect(init?.method).toBe('POST')
  expect(JSON.parse(String(init?.body))).toEqual({
    eventId,
    safetyOfficerId: officerId,
    reason: 'Needs another look.',
    flags: [{ area: 'venue arrangement', changeRequired: 'Move the stage.' }],
  })
})

test('SCRUM-151 AC1: a 400 for missing areas surfaces as an error', async () => {
  vi.stubGlobal('fetch', respond(400, { message: 'Select at least one affected area.' }))

  await expect(requestSafetyChanges({
    eventId, safetyOfficerId: officerId, reason: 'Needs another look.', flags: [],
  })).rejects.toThrowError('Select at least one affected area.')
})

test('SCRUM-151 AC3: reject always sends confirmed: true', async () => {
  const release = { venueBookingsReleased: ['b1'], venueBookingsNotReleased: [], equipment: 'Released.' }
  vi.stubGlobal('fetch', respond(200, { safetyCheck: { roundNumber: 1 }, event: {}, release }))

  const result = await rejectSafetyCheck({
    eventId, safetyOfficerId: officerId, reason: 'Unsafe egress plan.',
  })

  const [url, init] = vi.mocked(fetch).mock.calls[0]
  expect(String(url)).toBe('http://localhost:5012/safety-checks/reject')
  expect(JSON.parse(String(init?.body))).toEqual({
    eventId, safetyOfficerId: officerId, reason: 'Unsafe egress plan.', confirmed: true,
  })
  expect(result.release).toEqual(release)
})

test('SCRUM-151 AC3: a 400 without confirmation surfaces its code', async () => {
  vi.stubGlobal('fetch', respond(400, {
    code: 'REJECTION_NOT_CONFIRMED',
    message: 'Confirm the rejection before it can be saved.',
  }))

  await expect(rejectSafetyCheck({
    eventId, safetyOfficerId: officerId, reason: 'Unsafe egress plan.',
  })).rejects.toMatchObject({ code: 'REJECTION_NOT_CONFIRMED' })
})

test('AC1: the submission time comes from the event\'s own history', () => {
  const event = {
    actionHistory: [
      { status: 'Approved', details: 'Approved.', coordinatorId, recordedAt: '2026-10-02T01:00:00+00:00' },
      { status: 'Pending Safety Check', details: 'Submitted for Operational Safety Check (round 1).', coordinatorId, recordedAt: '2026-10-03T01:00:00+00:00' },
      { status: 'Pending Safety Check', details: 'Submitted for Operational Safety Check (round 2).', coordinatorId, recordedAt: '2026-10-09T01:00:00+00:00' },
    ],
  } as unknown as SubmittedEvent

  // The latest round's submission, not the first.
  expect(submittedForSafetyCheckAt(event)).toBe('2026-10-09T01:00:00+00:00')
})

test('an event never submitted has no submission time', () => {
  const event = { actionHistory: [] } as unknown as SubmittedEvent

  expect(submittedForSafetyCheckAt(event)).toBeNull()
})

test('SCRUM-9: a staff view of the event, without actionHistory, has no submission time', () => {
  expect(submittedForSafetyCheckAt({} as SubmittedEvent)).toBeNull()
})
