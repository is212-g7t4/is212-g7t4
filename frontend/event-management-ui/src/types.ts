// The Event Coordinator Lead assigns coordinators and otherwise works as an
// Event Coordinator (docs/db-structure.md, User.role).
export type Role = 'Event Organiser' | 'Event Coordinator' | 'Event Coordinator Lead' | 'Venue Staff' | 'Technical Support' | 'Safety Officer' | 'Attendee'
export type Route = 'notifications' | 'dashboard' | 'submit' | 'manage' | 'review' | 'changeRequests' | 'queue' | 'workload' | 'detail' | 'myEvents' | 'browseEvents' | 'myRegistrations' | 'venues' | 'venueDetail' | 'venueCalendar' | 'venueSearch' | 'addVenue' | 'editVenue' | 'equipment' | 'equipmentRequests' | 'safetyChecks' | 'newEquipmentRequest' | 'venueRequests' | 'editDraft'

export const routeTitles: Record<Route, string> = {
  notifications: 'Notifications',
  dashboard: 'Overview',
  submit: 'Submit an event',
  manage: 'Event information',
  review: 'Request review',
  changeRequests: 'Change requests',
  queue: 'Unassigned requests',
  workload: 'Coordinator workload',
  detail: 'Event record',
  myEvents: 'My events',
  browseEvents: 'Browse events',
  myRegistrations: 'My registrations',
  venues: 'Venue catalogue',
  venueDetail: 'Venue details',
  venueCalendar: 'Venue availability calendar',
  venueRequests: 'Venue requests',
  venueSearch: 'Find a venue',
  addVenue: 'Add venue',
  editVenue: 'Edit venue',
  equipment: 'Equipment catalogue',
  equipmentRequests: 'Equipment requests',
  safetyChecks: 'Safety checks',
  newEquipmentRequest: 'New equipment request',
  editDraft: 'Draft event request',
}

export interface User {
  id: string
  username: string
  email: string
  role: Role
  organization: string
  contactDetails?: string
}

export type RequestStatus =
  | 'Pending'
  | 'Submitted'
  | 'Under Review'
  | 'Clarification Requested'
  | 'Approved'
  | 'Confirmed'
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
  withdrawalDeadline?: string
}

export interface MockRequest {
  id: number
  title: string
  date: string
  venue: string
  attendance: string
  status: RequestStatus
}
