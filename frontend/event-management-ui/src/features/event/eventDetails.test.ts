/**
 * SCRUM-153: the edit request Event Service receives, and the one refusal the
 * dialog has to treat as a question rather than an error — AC1's
 * `409 SAFETY_RECHECK_REQUIRED`.
 */
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import {
  EDITABLE_FIELDS,
  EventEditError,
  FIELD_LABELS,
  HIGH_IMPACT_FIELDS,
  LOW_IMPACT_FIELDS,
  SafetyRecheckRequired,
  fieldLabels,
  isHighImpact,
  sentenceList,
  updateEventDetails,
} from './eventDetails'

const eventId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const coordinatorId = '11111111-1111-4111-8111-111111111111'

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

test('the edit is PATCHed to Event Service with only the changed fields', async () => {
  vi.stubGlobal('fetch', respond(200, { id: eventId, status: 'Confirmed' }))

  const saved = await updateEventDetails(eventId, coordinatorId, {
    eventName: 'Community Workshop (Autumn)',
  })

  expect(saved.status).toBe('Confirmed')
  const [url, init] = vi.mocked(fetch).mock.calls[0]
  expect(String(url)).toBe(`http://localhost:5003/events/${eventId}/details`)
  expect(init?.method).toBe('PATCH')
  expect(JSON.parse(String(init?.body))).toEqual({
    coordinatorId,
    changes: { eventName: 'Community Workshop (Autumn)' },
  })
})

test('AC2: a low-impact edit comes back with the event still Confirmed', async () => {
  vi.stubGlobal('fetch', respond(200, { id: eventId, status: 'Confirmed' }))

  const saved = await updateEventDetails(eventId, coordinatorId, { purpose: 'Rewritten.' })

  expect(saved.status).toBe('Confirmed')
})

test('AC1: SAFETY_RECHECK_REQUIRED throws its own type, carrying the labels', async () => {
  vi.stubGlobal('fetch', respond(409, {
    code: 'SAFETY_RECHECK_REQUIRED',
    message: 'Changing Date/time will withdraw this event’s safety approval.',
    changedFields: ['preferredStartDate', 'eventName'],
    highImpactFields: ['preferredStartDate'],
    labels: ['Date/time'],
  }))

  await expect(
    updateEventDetails(eventId, coordinatorId, { preferredStartDate: '2026-11-10T08:00' }),
  ).rejects.toSatisfy((error: unknown) => {
    expect(error).toBeInstanceOf(SafetyRecheckRequired)
    const recheck = error as SafetyRecheckRequired
    expect(recheck.labels).toEqual(['Date/time'])
    expect(recheck.highImpactFields).toEqual(['preferredStartDate'])
    expect(recheck.changedFields).toEqual(['preferredStartDate', 'eventName'])
    expect(recheck.message).toContain('withdraw')
    return true
  })
})

test('a SAFETY_RECHECK_REQUIRED with no detail still has usable defaults', async () => {
  vi.stubGlobal('fetch', respond(409, { code: 'SAFETY_RECHECK_REQUIRED' }))

  const error = await updateEventDetails(eventId, coordinatorId, {}).catch((cause) => cause)

  expect(error).toBeInstanceOf(SafetyRecheckRequired)
  expect(error.labels).toEqual([])
  expect(error.message).toBe('This change needs a new safety check.')
})

test('only that code becomes SafetyRecheckRequired; other 409s are plain errors', async () => {
  vi.stubGlobal('fetch', respond(409, {
    code: 'EVENT_UNDER_SAFETY_REVIEW',
    message: 'This event is waiting for its Operational Safety Check.',
  }))

  const error = await updateEventDetails(eventId, coordinatorId, {}).catch((cause) => cause)

  expect(error).toBeInstanceOf(EventEditError)
  expect(error).not.toBeInstanceOf(SafetyRecheckRequired)
  expect(error.code).toBe('EVENT_UNDER_SAFETY_REVIEW')
})

test('a validation 400 carries its missing fields and errors', async () => {
  vi.stubGlobal('fetch', respond(400, {
    message: 'Please correct the event details.',
    missingFields: ['Purpose'],
    errors: ['Preferred End Date & Time must be after the start.'],
  }))

  const error = await updateEventDetails(eventId, coordinatorId, {}).catch((cause) => cause)

  expect(error).toBeInstanceOf(EventEditError)
  expect(error.missingFields).toEqual(['Purpose'])
  expect(error.errors).toEqual(['Preferred End Date & Time must be after the start.'])
})

test('a refusal with no body still produces a readable message', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: false,
    status: 503,
    json: () => Promise.reject(new Error('not JSON')),
  }))

  const error = await updateEventDetails(eventId, coordinatorId, {}).catch((cause) => cause)

  expect(error.message).toBe('Unable to save these event details.')
  expect(error.missingFields).toEqual([])
})

// --- The field classification, mirrored from Event Service -------------------

test('the two field sets partition the editable fields', () => {
  expect([...LOW_IMPACT_FIELDS, ...HIGH_IMPACT_FIELDS].sort()).toEqual([...EDITABLE_FIELDS].sort())
  expect(Object.keys(FIELD_LABELS).sort()).toEqual([...EDITABLE_FIELDS].sort())
})

test('AC1: exactly the five details whose change invalidates a safety review', () => {
  expect([...HIGH_IMPACT_FIELDS]).toEqual([
    'preferredStartDate',
    'preferredEndDate',
    'expectedAttendance',
    'venueRequirements',
    'equipmentRequirements',
    'accessibilityNeeds',
  ])
  expect(isHighImpact('expectedAttendance')).toBe(true)
  expect(isHighImpact('eventName')).toBe(false)
  expect(isHighImpact('status')).toBe(false)
})

test('both date fields read as one "Date/time" label', () => {
  expect(fieldLabels(['preferredStartDate', 'preferredEndDate'])).toEqual(['Date/time'])
})

test('labels come back in a stable order, whatever order the fields arrive in', () => {
  expect(fieldLabels(['eventName', 'expectedAttendance'])).toEqual([
    'Event name',
    'Expected attendance',
  ])
  expect(fieldLabels(['expectedAttendance', 'eventName'])).toEqual([
    'Event name',
    'Expected attendance',
  ])
  expect(fieldLabels(['notAField'])).toEqual([])
})

test('the sentence list reads naturally at every length', () => {
  expect(sentenceList([])).toBe('')
  expect(sentenceList(['Date/time'])).toBe('Date/time')
  expect(sentenceList(['Date/time', 'Expected attendance'])).toBe(
    'Date/time and Expected attendance',
  )
  expect(sentenceList(['Date/time', 'Expected attendance', 'Venue requirements'])).toBe(
    'Date/time, Expected attendance and Venue requirements',
  )
})
