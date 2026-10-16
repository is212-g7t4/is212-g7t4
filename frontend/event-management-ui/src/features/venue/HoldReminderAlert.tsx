import { useEffect, useState } from 'react'
import type { User } from '../../types'
import { AlertIcon } from '../../components/Icon'
import { fetchHoldReminders } from './venueHolds'
import type { VenueHold } from './venueHolds'
import { fetchVenues } from './venues'

const POLL_MS = 60_000

// Service returns Singapore-local naive timestamps, so display them without timezone conversion.
function formatExpiry(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('en-SG', { dateStyle: 'medium', timeStyle: 'short' })
}

export function HoldReminderAlert({ user }: { user?: Pick<User, 'id' | 'role'> }) {
  const [reminders, setReminders] = useState<VenueHold[]>([])
  const [venueNames, setVenueNames] = useState<Record<string, string>>({})
  const isCoordinator = user?.role === 'Event Coordinator' || user?.role === 'Event Coordinator Lead'
  const userId = user?.id
  const userRole = user?.role

  useEffect(() => {
    if (!isCoordinator || !userId || !userRole) return
    let active = true
    const load = () => {
      fetchHoldReminders({ id: userId, role: userRole }).then(async (items) => {
        if (!active) return
        setReminders(items)
        if (items.length === 0) return
        const venues = await fetchVenues().catch(() => [])
        if (active) setVenueNames(Object.fromEntries(venues.map((venue) => [venue.id, venue.name])))
      }).catch(() => {
        // A failed poll keeps the last known reminders; the next poll retries.
      })
    }
    load()
    const interval = window.setInterval(load, POLL_MS)
    return () => { active = false; window.clearInterval(interval) }
  }, [isCoordinator, userId, userRole])

  if (!isCoordinator || reminders.length === 0) return null

  return <div className="notice error" role="alert">
    <AlertIcon size={15} />
    <ul>
      {reminders.map((hold) => <li key={hold.id}>
        Your hold on {venueNames[hold.venueId] ?? 'a venue'} expires on {formatExpiry(hold.expiresAt)}. Complete the required actions before then.
      </li>)}
    </ul>
  </div>
}
