import { useEffect, useState } from 'react'
import { fetchVenues } from './venues'
import type { Venue } from './venues'
import { InlineLoading } from '../../components/Loading'

export function VenueSelect({
  value,
  onChange,
}: {
  value: string
  onChange: (value: string, venue: Venue | null) => void
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
        <InlineLoading label="Loading venues…" />
      ) : error ? (
        <p className="field-error" role="alert">{error}</p>
      ) : (
        <select value={value} onChange={(event) => {
          const venueId = event.target.value
          onChange(venueId, venues.find((venue) => venue.id === venueId) || null)
        }}>
          <option value="">Select a venue</option>
          {venues.map((venue) => (
            <option key={venue.id} value={venue.id} disabled={venue.status !== 'Available'}>
              {venue.name}{venue.status !== 'Available' ? ` (${venue.status})` : ''}
            </option>
          ))}
        </select>
      )}
    </label>
  )
}
