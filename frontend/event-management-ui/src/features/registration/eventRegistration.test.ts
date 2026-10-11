import { afterEach, expect, test, vi } from 'vitest'
import { EventRegistrationError, registerForEvent } from './eventRegistration'

afterEach(() => vi.unstubAllGlobals())

test('registration sends only the event and attendee IDs', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ message: 'ok' }), { status: 201 }))
  vi.stubGlobal('fetch', fetchMock)

  await registerForEvent({ eventId: 'event-1', attendeeId: 'attendee-1' })

  const [, init] = fetchMock.mock.calls[0]
  expect(JSON.parse(init.body)).toEqual({ eventId: 'event-1', attendeeId: 'attendee-1' })
})

test('registration surfaces the server error code', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
    JSON.stringify({ code: 'DUPLICATE_REGISTRATION', message: 'You are already registered for this event.' }),
    { status: 409 },
  )))

  const error = await registerForEvent({ eventId: 'event-1', attendeeId: 'attendee-1' }).catch((cause) => cause)

  expect(error).toBeInstanceOf(EventRegistrationError)
  expect(error.code).toBe('DUPLICATE_REGISTRATION')
})
