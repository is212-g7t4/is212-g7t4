export type Role = 'Event Organiser' | 'Event Coordinator' | 'Venue Staff' | 'Technical Support'
export type Route = 'dashboard' | 'submit' | 'manage' | 'review' | 'detail' | 'myEvents'

export const routeTitles: Record<Route, string> = {
  dashboard: 'Overview',
  submit: 'Submit an event',
  manage: 'Event information',
  review: 'Request review',
  detail: 'Event record',
  myEvents: 'My events',
}

export interface User {
  id: string
  username: string
  email: string
  role: Role
  organization: string
  managerId: string | null
}

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
