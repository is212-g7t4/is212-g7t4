import type { User } from '../../types'

export const REQUEST_STATUSES = ['Pending', 'Approved', 'Rejected'] as const
export type EquipmentRequestStatus = (typeof REQUEST_STATUSES)[number]

export interface RequestAvailability {
  reservedQuantity: number
  availableStock: number
  isInsufficient: boolean
}

export interface EquipmentRequest {
  id: string
  eventId: string
  equipmentId: string
  quantityRequested: number
  technicalRequirements: string
  status: EquipmentRequestStatus
  reviewedBy: string | null
  equipment: { description: string; type: string; totalQuantity: number; status: string } | null
  /** Only Pending lines are checked for availability. */
  availability: RequestAvailability | null
}

export interface EventReservation {
  eventId: string
  eventName: string
  eventStatus: string | null
  coordinatorId: string | null
  startTime: string | null
  endTime: string | null
  requests: EquipmentRequest[]
}

/** The decision endpoints return the bare request; the page keeps its equipment and availability. */
export type ReviewedRequest = Omit<EquipmentRequest, 'equipment' | 'availability'>

// Equipment Reservation Service decides availability, so the page talks only to it.
const serviceUrl = () => import.meta.env.VITE_EQUIPMENT_RESERVATION_SERVICE_URL || 'http://localhost:5010'

/** DEV headers identify the switcher user; they are spoofable until real auth lands. */
const devHeaders = (user: Pick<User, 'id' | 'role'>) => ({ 'X-Dev-User-Id': user.id, 'X-Dev-Role': user.role })

export async function fetchEventReservations(user: Pick<User, 'id' | 'role'>, status?: EquipmentRequestStatus): Promise<EventReservation[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : ''
  const response = await fetch(`${serviceUrl()}/equipment-reservations${query}`, { headers: devHeaders(user) })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to load equipment requests.')
  return body.events as EventReservation[]
}

export async function reviewEquipmentRequest(id: string, status: 'Approved' | 'Rejected', user: Pick<User, 'id' | 'role'>): Promise<ReviewedRequest> {
  const response = await fetch(`${serviceUrl()}/equipment-reservations/requests/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...devHeaders(user) },
    body: JSON.stringify({ status }),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to update this equipment request.')
  return body.request as ReviewedRequest
}

export async function reviewAllEventEquipmentRequests(eventId: string, status: 'Approved' | 'Rejected', user: Pick<User, 'id' | 'role'>): Promise<ReviewedRequest[]> {
  const response = await fetch(`${serviceUrl()}/equipment-reservations/events/${encodeURIComponent(eventId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...devHeaders(user) },
    body: JSON.stringify({ status }),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to update this event\'s equipment requests.')
  return body.requests as ReviewedRequest[]
}
