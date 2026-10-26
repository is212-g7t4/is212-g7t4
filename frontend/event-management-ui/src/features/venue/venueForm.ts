import type { User } from '../../types'
import type { Venue } from './venues'

export interface VenueFormData {
  name: string
  location: string
  capacity: string
  facilities: string
  accessibility: string
  supportedLayouts: string
  status: string
  setupTimeMinutes: string
  turnaroundTimeMinutes: string
  // SCRUM-167: saved by updateVenueSafetyInfo, never sent in the profile payload.
  emergencyAccessDetails: string
  knownRestrictions: string
}

export const SAFETY_INFO_MAX_LENGTH = 2000

export const VENUE_STATUSES = ['Available', 'Under Maintenance', 'Booked'] as const

export const emptyVenueForm: VenueFormData = {
  name: '',
  location: '',
  capacity: '',
  facilities: '',
  accessibility: '',
  supportedLayouts: '',
  status: 'Available',
  setupTimeMinutes: '0',
  turnaroundTimeMinutes: '0',
  emergencyAccessDetails: '',
  knownRestrictions: '',
}

function splitList(value: string): string[] {
  return value.split(',').map((item) => item.trim()).filter(Boolean)
}

export function validateVenueForm(form: VenueFormData) {
  const missingFields: string[] = []
  const errors: string[] = []

  if (!form.name.trim()) missingFields.push('Venue Name')
  if (!form.location.trim()) missingFields.push('Location')
  if (!form.capacity.trim()) missingFields.push('Capacity')
  if (splitList(form.facilities).length === 0) missingFields.push('Facilities')
  if (splitList(form.supportedLayouts).length === 0) missingFields.push('Supported Room Layouts')
  if (!form.status.trim()) missingFields.push('Operating Status')
  if (!form.setupTimeMinutes.trim()) missingFields.push('Setup Time')
  if (!form.turnaroundTimeMinutes.trim()) missingFields.push('Turnaround Time')

  if (missingFields.length) return { missingFields, errors }

  if (!/^\d+$/.test(form.capacity.trim()) || Number(form.capacity) < 1 || Number(form.capacity) > 2147483647) {
    errors.push('Capacity must be a positive whole number (maximum 2147483647).')
  }
  if (!(VENUE_STATUSES as readonly string[]).includes(form.status.trim())) {
    errors.push(`Operating Status must be one of: ${VENUE_STATUSES.join(', ')}.`)
  }
  for (const [value, label] of [
    [form.setupTimeMinutes, 'Setup Time'],
    [form.turnaroundTimeMinutes, 'Turnaround Time'],
  ] as const) {
    if (!/^\d+$/.test(value.trim()) || Number(value) > 2147483647) {
      errors.push(`${label} must be a non-negative whole number of minutes (maximum 2147483647).`)
    }
  }

  for (const [value, label] of [
    [form.emergencyAccessDetails, 'Emergency Access Details'],
    [form.knownRestrictions, 'Known Restrictions'],
  ] as const) {
    if (value.trim().length > SAFETY_INFO_MAX_LENGTH) {
      errors.push(`${label} must be at most ${SAFETY_INFO_MAX_LENGTH} characters.`)
    }
  }

  return { missingFields, errors }
}

export class VenueSubmissionError extends Error {
  missingFields: string[]
  errors: string[]
  constructor(message: string, missingFields: string[] = [], errors: string[] = []) {
    super(message)
    this.missingFields = missingFields
    this.errors = errors
  }
}

const venueServiceUrl = () => import.meta.env.VITE_VENUE_SERVICE_URL || 'http://localhost:5006'
const venueBookingServiceUrl = () => import.meta.env.VITE_VENUE_BOOKING_SERVICE_URL || 'http://localhost:5007'

export async function createVenue(form: VenueFormData): Promise<Venue> {
  return saveVenue('/venues', 'POST', form)
}

export async function updateVenue(venueId: string, form: VenueFormData): Promise<Venue> {
  return saveVenue(`/venues/${encodeURIComponent(venueId)}`, 'PUT', form)
}

async function saveVenue(path: string, method: 'POST' | 'PUT', form: VenueFormData): Promise<Venue> {
  const payload = {
    name: form.name.trim(),
    location: form.location.trim(),
    capacity: form.capacity.trim(),
    facilities: splitList(form.facilities),
    accessibility: form.accessibility.trim(),
    supportedLayouts: splitList(form.supportedLayouts),
    status: form.status.trim(),
    setupTimeMinutes: form.setupTimeMinutes.trim(),
    turnaroundTimeMinutes: form.turnaroundTimeMinutes.trim(),
  }
  // Editing a venue changes both its catalogue profile and the scheduling
  // rules applied to existing bookings, so the composite owns that workflow.
  const serviceUrl = method === 'PUT' ? venueBookingServiceUrl() : venueServiceUrl()
  const response = await fetch(`${serviceUrl}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new VenueSubmissionError(body.message || 'Unable to save the venue.', body.missingFields, body.errors)
  return body.venue as Venue
}

export type VenueSafetyInfo = Pick<VenueFormData, 'emergencyAccessDetails' | 'knownRestrictions'>

/** SCRUM-167: Venue Staff replace both safety fields together. Goes straight to
 *  Venue Service (it affects no booking, so Venue Booking has no part in it);
 *  blank text is sent as null so the venue reads "Not provided". */
export async function updateVenueSafetyInfo(
  venueId: string,
  safety: VenueSafetyInfo,
  user: Pick<User, 'id' | 'role'>,
): Promise<Venue> {
  const response = await fetch(`${venueServiceUrl()}/venues/${encodeURIComponent(venueId)}/safety-info`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', 'X-Dev-User-Id': user.id, 'X-Dev-Role': user.role },
    body: JSON.stringify({
      emergencyAccessDetails: safety.emergencyAccessDetails.trim() || null,
      knownRestrictions: safety.knownRestrictions.trim() || null,
    }),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new VenueSubmissionError(body.message || 'Unable to save the safety information.', [], body.errors)
  return body.venue as Venue
}
