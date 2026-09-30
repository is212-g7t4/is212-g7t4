export interface Venue {
  id: string
  name: string
  location: string
  capacity: number | null
  facilities: string[]
  accessibility: string
  supportedLayouts: string[]
  status: string
}

const venueServiceUrl = () => import.meta.env.VITE_VENUE_SERVICE_URL || 'http://localhost:5006'

export async function fetchVenues(): Promise<Venue[]> {
  const response = await fetch(`${venueServiceUrl()}/venues`)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to load the venue catalogue.')
  return body.venues as Venue[]
}

export async function fetchVenue(id: string): Promise<Venue> {
  const response = await fetch(`${venueServiceUrl()}/venues/${encodeURIComponent(id)}`)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to load this venue.')
  return body.venue as Venue
}
