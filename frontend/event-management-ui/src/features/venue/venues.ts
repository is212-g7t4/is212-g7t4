export interface Venue {
  id: string
  name: string
  location: string
  capacity: number | null
  facilities: unknown[] | Record<string, unknown>
  accessibility: string
  supportedLayouts: unknown[] | Record<string, unknown>
  status: string
}

export async function fetchVenues(): Promise<Venue[]> {
  const response = await fetch(`${import.meta.env.VITE_VENUE_SERVICE_URL || 'http://localhost:5006'}/venues`)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to load the venue catalogue.')
  return body.venues as Venue[]
}
