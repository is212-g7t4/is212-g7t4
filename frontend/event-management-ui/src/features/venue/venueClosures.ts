import type { User } from '../../types'
import { singaporeInput, timestampMicros } from '../calendar/dates'
export interface VenueClosure {
  closureId: string; venueId: string | null; startDateTime: string; endDateTime: string
  reason: string; createdBy: string | null; createdAt: string | null
}
export interface ClosurePreview {
  closure: { venueId: string; startDateTime: string; endDateTime: string; reason: string }
  venueName: string
  affectedCount: number
  confirmationToken: string
  affectedRequests: { id: string; eventId: string; venueId: string; eventName: string; venueName: string; requestedStartTime: string; requestedEndTime: string; status: string }[]
}
type Identity = Pick<User, 'id' | 'role'>
const url = () => (import.meta.env.VITE_VENUE_BOOKING_SERVICE_URL || 'http://localhost:5007') + '/venue-closures'
const headers = (user: Identity) => ({ 'Content-Type': 'application/json', 'X-Dev-User-Id': user.id, 'X-Dev-Role': user.role })
const ambiguous = 'The closure may have been recorded. Refresh the closure list and load all pages before retrying; a retry can create a duplicate. If uncertain, reconcile with staff.'
function validClosure(value: unknown, venueId: string): value is VenueClosure {
  if (!value || typeof value !== 'object') return false
  const row = value as VenueClosure
  const start = timestampMicros(row.startDateTime), end = timestampMicros(row.endDateTime)
  return typeof row.closureId === 'string' && !!row.closureId && row.venueId === venueId &&
    start !== null && end !== null && end > start && typeof row.reason === 'string' && !!row.reason.trim() &&
    (row.createdBy === null || typeof row.createdBy === 'string') &&
    (row.createdAt === null || timestampMicros(row.createdAt) !== null)
}
export async function createClosure(venueId: string, start: string, end: string, reason: string, user: Identity, confirmationToken: string, signal?: AbortSignal): Promise<VenueClosure & { rejectedCount: number }> {
  const startDateTime = singaporeInput(start), endDateTime = singaporeInput(end)
  const a = timestampMicros(startDateTime), b = timestampMicros(endDateTime)
  if (a === null || b === null || b <= a || b <= BigInt(Date.now()) * 1000n)
    throw new Error('Enter valid Singapore dates: end must be after start and in the future.')
  if (!reason.trim()) throw new Error('A reason is required.')
  let response: Response
  try {
    response = await fetch(url(), { method: 'POST', headers: headers(user), signal,
      body: JSON.stringify({ venueId, startDateTime, endDateTime, reason: reason.trim(), confirmed: true, confirmationToken }) })
  } catch { throw Object.assign(new Error(ambiguous), { uncertain: true }) }
  const body = await response.json().catch(() => null)
  if (response.status >= 400 && response.status < 500) throw Object.assign(new Error(body?.message || 'Unable to record closure. Check your input and staff identity.'), { code: body?.code })
  if (response.status !== 201 || !validClosure(body?.closure, venueId) || !Number.isInteger(body?.rejectedCount) || body.rejectedCount < 0) throw Object.assign(new Error(ambiguous), { uncertain: true })
  return { ...body.closure, rejectedCount: body.rejectedCount }
}
export async function previewClosure(venueId: string, start: string, end: string, reason: string, user: Identity, signal?: AbortSignal): Promise<ClosurePreview> {
  const response = await fetch(`${url()}/preview`, { method: 'POST', headers: headers(user), signal,
    body: JSON.stringify({ venueId, startDateTime: singaporeInput(start), endDateTime: singaporeInput(end), reason: reason.trim() }) })
  const body = await response.json()
  if (!response.ok) throw new Error(body?.message || 'Unable to preview affected requests.')
  const validTime = (value: string) => timestampMicros(value) !== null
  const expectedStart = singaporeInput(start), expectedEnd = singaporeInput(end)
  if (!body || body.closure?.venueId !== venueId || body.closure?.reason !== reason.trim() ||
    timestampMicros(body.closure?.startDateTime) !== timestampMicros(expectedStart) ||
    timestampMicros(body.closure?.endDateTime) !== timestampMicros(expectedEnd) ||
    !validTime(body.closure?.startDateTime) || !validTime(body.closure?.endDateTime) ||
    typeof body.venueName !== 'string' || !body.venueName.trim() ||
    typeof body.confirmationToken !== 'string' || !body.confirmationToken.trim() ||
    !Array.isArray(body.affectedRequests) || body.affectedCount !== body.affectedRequests.length ||
    !body.affectedRequests.every((row: ClosurePreview['affectedRequests'][number]) => row &&
      typeof row.id === 'string' && !!row.id && typeof row.eventId === 'string' && !!row.eventId && row.venueId === venueId &&
      typeof row.eventName === 'string' && !!row.eventName.trim() && typeof row.venueName === 'string' && !!row.venueName.trim() &&
      ['Pending', 'Pending Review', 'Approved'].includes(row.status) && validTime(row.requestedStartTime) && validTime(row.requestedEndTime) &&
      timestampMicros(row.requestedStartTime)! < timestampMicros(row.requestedEndTime)!) ||
    new Set(body.affectedRequests.map((row: { id: string }) => row.id)).size !== body.affectedCount)
    throw new Error('Unable to verify the complete affected-request preview. Please preview again.')
  return body
}
export async function listClosures(venueId: string, user: Identity, cursor?: string, signal?: AbortSignal): Promise<{ closures: VenueClosure[]; nextCursor: string | null }> {
  const query = new URLSearchParams({ venueId, limit: '50' })
  if (cursor) query.set('cursor', cursor)
  const response = await fetch(`${url()}?${query}`, { headers: headers(user), signal })
  const body = await response.json().catch(() => null)
  if (!response.ok || !Array.isArray(body?.closures) || !body.closures.every((row: unknown) => validClosure(row, venueId)) ||
    !(body.nextCursor === null || (typeof body.nextCursor === 'string' && body.nextCursor.length > 0)) ||
    new Set(body.closures.map((row: VenueClosure) => row.closureId)).size !== body.closures.length)
    throw new Error('Unable to load recorded closures. Refresh to try again.')
  return body
}
