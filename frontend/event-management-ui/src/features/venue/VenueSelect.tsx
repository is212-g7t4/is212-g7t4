import { useEffect, useState } from 'react'
import { fetchVenues } from './venues'
import type { Venue } from './venues'

export function VenueSelect({
  value,
  onChange,
}: {
  value: string
  onChange: (value: string) => void
}) {
  const [venues, setVenues] = useState<Venue[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    fetchVenues().then((items) => {
      if (active) setVenues(items)
    }).catch((cause: Error) => {
      if (active) setError(cause.message)
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [])

  return (
    <label className="field">
      <span>Venue</span>

      {loading ? (
        <p className="muted">Loading venues…</p>
      ) : error ? (
        <p role="alert">{error}</p>
      ) : (
        <select value={value} onChange={(event) => onChange(event.target.value)}>
          <option value="">Select a venue</option>
          {venues.map((venue) => (
            // Only Operational venues are selectable — everything else is
            // shown but disabled, which browsers render greyed out.
            <option key={venue.id} value={venue.id} disabled={venue.status !== 'Available'}>
              {venue.name}{venue.status !== 'Available' ? ` (${venue.status})` : ''}
            </option>
          ))}
        </select>
      )}
    </label>
  )
}
