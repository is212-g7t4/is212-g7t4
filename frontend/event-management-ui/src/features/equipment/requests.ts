import { eventApi } from '../event/submission'
import type { SubmittedEvent } from '../event/submission'
import { authFetch } from '../auth/session'

export const REQUEST_STATUSES = ['Pending', 'Approved', 'Rejected'] as const
export type EquipmentRequestStatus = (typeof REQUEST_STATUSES)[number]

export const REQUESTABLE_EVENT_STATUSES = ['Under Review', 'Safety Changes Requested'] as const

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
  rejectionReason?: string | null
  safetyFeedback?: { reason: string | null; requestedChanges: string[] } | null
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


export async function fetchEventReservations(status?: EquipmentRequestStatus): Promise<EventReservation[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : ''
  const response = await authFetch(`${serviceUrl()}/equipment-reservations${query}`)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to load equipment requests.')
  return body.events as EventReservation[]
}

export async function reviewEquipmentRequest(id: string, status: 'Approved' | 'Rejected', rejectionReason?: string): Promise<ReviewedRequest> {
  const response = await authFetch(`${serviceUrl()}/equipment-reservations/requests/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, ...(status === 'Rejected' ? { rejectionReason } : {}) }),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to update this equipment request.')
  return body.request as ReviewedRequest
}

export async function reviewAllEventEquipmentRequests(eventId: string, status: 'Approved' | 'Rejected', rejectionReason?: string): Promise<ReviewedRequest[]> {
  const response = await authFetch(`${serviceUrl()}/equipment-reservations/events/${encodeURIComponent(eventId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, ...(status === 'Rejected' ? { rejectionReason } : {}) }),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to update this event\'s equipment requests.')
  return body.requests as ReviewedRequest[]
}

export interface NewEquipmentRequestItem {
  equipmentId: string
  quantityRequested: number
  technicalRequirements: string
}

/** Events assigned to the coordinator that can still take equipment requests. */
export async function fetchRequestableEvents(coordinatorId: string): Promise<SubmittedEvent[]> {
  const body = await eventApi(`/events?coordinatorId=${encodeURIComponent(coordinatorId)}`)
  return (body.events as SubmittedEvent[]).filter((event) => (REQUESTABLE_EVENT_STATUSES as readonly string[]).includes(event.status))
}

export async function createEquipmentRequests(eventId: string, items: NewEquipmentRequestItem[]): Promise<ReviewedRequest[]> {
  const response = await authFetch(`${serviceUrl()}/equipment-reservations/events/${encodeURIComponent(eventId)}/requests`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items }),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || 'Unable to submit this equipment request.')
  return body.requests as ReviewedRequest[]
}
