export type Role = 'Requester' | 'Event Coordinator' | 'Venue Staff' | 'Technical Support'
export type Route = 'dashboard' | 'submit' | 'assignment' | 'manage' | 'review'
export type RequestStatus =
  | 'Pending'
  | 'Submitted'
  | 'Approved'
  | 'Rejected'

export interface EventData {
  // Required fields
  eventName: string
  description: string
  purpose: string
  preferredStartDate: string
  preferredEndDate: string
  expectedAttendance: string

  // Optional fields
  venueRequirements: string
  accessibilityNeeds: string
  equipmentRequirements: string
  registrationNeeds: string
}

export interface MockRequest {
  id: number
  title: string
  date: string
  venue: string
  attendance: string
  status: RequestStatus
}
