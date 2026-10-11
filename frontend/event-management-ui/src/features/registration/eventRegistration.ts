// The attendee's name, email and organisation come from their User record,
// so a registration needs only the event and the attendee.
export interface EventRegistrationData {
  eventId: string
  attendeeId: string
}

export class EventRegistrationError extends Error {
  code?: string
  constructor(message: string, code?: string) {
    super(message)
    this.code = code
  }
}

export async function registerForEvent(data: EventRegistrationData) {
  const response = await fetch(
    `${import.meta.env.VITE_ATTENDEE_REGISTRATION_SERVICE_URL || 'http://localhost:5009'}/registrations`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    },
  )
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new EventRegistrationError(body.message || 'Unable to register for this event.', body.code)
  return body
}
