import type { User } from '../../types'
import type { Venue } from './venues'

export interface VenueHold {
  id: string
  venueId: string
  createdAt: string
  expiresAt: string
  heldBy: string | null
}

const availabilityServiceUrl = () => import.meta.env.VITE_VENUE_AVAILABILITY_SERVICE_URL || 'http://localhost:5008'

export async function fetchActiveVenueHolds(): Promise<VenueHold[]> {
  const response = await fetch(`${availabilityServiceUrl()}/venue-holds`)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to load active venue holds.')
  return body.holds as VenueHold[]
}

export async function placeVenueHold(
  venueId: string,
  expiresAt: string,
  user: Pick<User, 'id' | 'role'>,
  coordinatorId?: string,
  buffer: Pick<Venue, 'setupTimeMinutes' | 'turnaroundTimeMinutes'> = {},
): Promise<VenueHold> {
  const response = await fetch(`${availabilityServiceUrl()}/venue-holds`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Dev-User-Id': user.id,
      'X-Dev-Role': user.role,
    },
    body: JSON.stringify({ venueId, expiresAt, ...(coordinatorId ? { coordinatorId } : {}), ...(
      buffer.setupTimeMinutes !== undefined || buffer.turnaroundTimeMinutes !== undefined
        ? { setupTimeMinutes: buffer.setupTimeMinutes ?? 0, turnaroundTimeMinutes: buffer.turnaroundTimeMinutes ?? 0 }
        : {}
    ) }),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to place a hold on this venue.')
  return body.hold as VenueHold
}

// Holds placed for this coordinator that expire within 3 days; the service decides.
export async function fetchHoldReminders(user: Pick<User, 'id' | 'role'>): Promise<VenueHold[]> {
  const response = await fetch(`${availabilityServiceUrl()}/venue-holds/reminders`, {
    headers: { 'X-Dev-User-Id': user.id, 'X-Dev-Role': user.role },
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to load hold reminders.')
  return body.reminders as VenueHold[]
}

export function showVenueHoldStatus(venues: Venue[], holds: VenueHold[]): Venue[] {
  const heldVenueIds = new Set(holds.map((hold) => hold.venueId))
  return venues.map((venue) => heldVenueIds.has(venue.id) ? { ...venue, status: 'On Hold' } : venue)
}
