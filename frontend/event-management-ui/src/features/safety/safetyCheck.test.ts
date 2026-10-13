/**
 * SCRUM-149: the request shapes the safety panel sends, and how it reads the
 * two refusals it has to explain — AC2's `422` and AC4's `409`.
 */
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import {
  SafetySubmitError,
  approveSafetyCheck,
  fetchSafetyReadiness,
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
    message: "This event can't be submitted for a safety check until every venue booking and equipment request is approved.",
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
