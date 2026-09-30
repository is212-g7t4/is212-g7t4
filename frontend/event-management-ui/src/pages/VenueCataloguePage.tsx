import { useEffect, useState } from 'react'
import type { Role } from '../types'
import { fetchVenues } from '../features/venue/venues'
import type { Venue } from '../features/venue/venues'

function displayList(value: Venue['facilities']): string {
  if (Array.isArray(value)) return value.map(String).join(', ')
  return Object.entries(value).map(([key, item]) => `${key}: ${String(item)}`).join(', ')
}

export function VenueCataloguePage({ role }: { role: Role }) {
  const [venues, setVenues] = useState<Venue[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  useEffect(() => {
    if (role !== 'Venue Staff') return
    let active = true
    const load = () => {
      fetchVenues().then((items) => {
        if (active) {
          setVenues(items)
          setError('')
          setLastUpdated(new Date())
        }
      }).catch((cause: Error) => {
        if (active) setError(cause.message)
      }).finally(() => {
        if (active) setLoading(false)
      })
    }
    load()
    const interval = window.setInterval(load, 30_000)
    return () => {
      active = false
      window.clearInterval(interval)
    }
  }, [role])

  if (role !== 'Venue Staff') return <p className="role-warning">The Venue Catalogue is visible to Venue Staff.</p>

  return <div className="page-stack">
    <section className="intro"><h1>Venue catalogue</h1><p className="muted">Review venue profiles and their current operational status. The catalogue refreshes automatically every 30 seconds.</p></section>
    {lastUpdated && <p className="muted" role="status">Last updated {lastUpdated.toLocaleTimeString()}</p>}
    {loading ? <p role="status">Loading venues...</p> : error ? <p role="alert">{error}</p> : venues.length === 0 ? <p>No venues are available.</p> : <section className="panel venue-table-panel"><div className="table-scroll"><table className="venue-table"><thead><tr><th>Venue</th><th>Location</th><th>Capacity</th><th>Accessibility</th><th>Facilities</th><th>Layouts</th><th>Status</th></tr></thead><tbody>
      {venues.map((venue) => <tr key={venue.id}><td><strong>{venue.name}</strong></td><td>{venue.location || 'Not specified'}</td><td>{venue.capacity ?? 'Not specified'}</td><td>{venue.accessibility || 'Not specified'}</td><td>{displayList(venue.facilities) || 'Not specified'}</td><td>{displayList(venue.supportedLayouts) || 'Not specified'}</td><td><span className={`venue-status ${venue.status.toLowerCase().replace(/\s+/g, '-')}`}>{venue.status}</span></td></tr>)}
    </tbody></table></div></section>}
  </div>
}
