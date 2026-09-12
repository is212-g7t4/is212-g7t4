export type Role = 'Requester' | 'Event Coordinator' | 'Venue Staff' | 'Technical Support'
export type Route = 'dashboard' | 'submit' | 'assignment' | 'manage' | 'review'
export type RequestStatus = 'Pending' | 'Approved' | 'Rejected'

export interface EventData {
  title: string
  description: string
  purpose: string
  date: string
  venue: string
  equipment: string
  attendance: string
}

export interface MockRequest {
  id: number
  title: string
  date: string
  venue: string
  attendance: string
  status: RequestStatus
}
