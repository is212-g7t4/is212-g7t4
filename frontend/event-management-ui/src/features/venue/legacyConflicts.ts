export interface LegacyConflictBooking {
  id: string
  eventId: string | null
  eventName?: string | null
  status: string
  requestedStartTime: string
  requestedEndTime: string
  effectiveStartTime: string
  effectiveEndTime: string
  conflictReason: 'BUFFER_OVERLAP'
}

export interface LegacyConflict {
  reason: 'BUFFER_OVERLAP'
  firstBooking: LegacyConflictBooking
  secondBooking: LegacyConflictBooking
}

export interface LegacyConflictResult {
  venueId: string
  conflictCount: number
  conflicts: LegacyConflict[]
}

const serviceUrl = () => import.meta.env.VITE_VENUE_BOOKING_SERVICE_URL || 'http://localhost:5007'

export async function fetchLegacyConflicts(
  venueId: string,
  viewer?: { id: string; role: string },
): Promise<LegacyConflictResult> {
  const url = `${serviceUrl()}/venues/${encodeURIComponent(venueId)}/legacy-conflicts`
  const response = await (viewer
    ? fetch(url, { headers: { 'X-Dev-User-Id': viewer.id, 'X-Dev-Role': viewer.role } })
    : fetch(url))
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to identify scheduling conflicts.')
  return body as LegacyConflictResult
}
