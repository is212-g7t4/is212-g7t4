export interface EventRegistrationData {
  eventId: string
  attendeeId: string
  fullName: string
  email: string
  organization: string
}

export interface RegistrationValidation {
  fullName?: string
  email?: string
}

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function validateRegistrationForm(data: Pick<EventRegistrationData, 'fullName' | 'email'>): RegistrationValidation {
  const errors: RegistrationValidation = {}
  if (!data.fullName.trim()) errors.fullName = 'Full name is required.'
  if (!data.email.trim()) errors.email = 'Email address is required.'
  else if (!EMAIL_PATTERN.test(data.email.trim())) errors.email = 'Enter a valid email address.'
  return errors
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
