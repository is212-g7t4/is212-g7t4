import { afterEach, expect, test, vi } from 'vitest'
import { fetchLegacyConflicts } from './legacyConflicts'

afterEach(() => vi.unstubAllGlobals())

test('loads the current venue conflict review from the composite workflow', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    venueId: 'venue-1', conflictCount: 0, conflicts: [],
  })))
  vi.stubGlobal('fetch', fetcher)

  await expect(fetchLegacyConflicts('venue/1')).resolves.toMatchObject({ conflictCount: 0 })
  expect(fetcher).toHaveBeenCalledWith('http://localhost:5007/venues/venue%2F1/legacy-conflicts')
})

test('does not silently treat a failed reconciliation as conflict-free', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ message: 'Conflict review unavailable' }), { status: 502 })))

  await expect(fetchLegacyConflicts('venue-1')).rejects.toThrow('Conflict review unavailable')
})
