import type { Venue } from './venues'

export interface VenueFormData {
  name: string
  location: string
  capacity: string
  facilities: string
  accessibility: string
  supportedLayouts: string
  status: string
}

export const VENUE_STATUSES = ['Available', 'Under Maintenance', 'Booked'] as const

export const emptyVenueForm: VenueFormData = {
  name: '',
  location: '',
  capacity: '',
  facilities: '',
  accessibility: '',
  supportedLayouts: '',
  status: 'Available',
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

  if (missingFields.length) return { missingFields, errors }

  if (!/^\d+$/.test(form.capacity.trim()) || Number(form.capacity) < 1 || Number(form.capacity) > 2147483647) {
    errors.push('Capacity must be a positive whole number (maximum 2147483647).')
  }
  if (!(VENUE_STATUSES as readonly string[]).includes(form.status.trim())) {
    errors.push(`Operating Status must be one of: ${VENUE_STATUSES.join(', ')}.`)
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
  }
  const response = await fetch(`${venueServiceUrl()}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new VenueSubmissionError(body.message || 'Unable to save the venue.', body.missingFields, body.errors)
  return body.venue as Venue
}
