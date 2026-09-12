import type { EventData, MockRequest, Role } from './types'

export const roles: Role[] = ['Requester', 'Event Coordinator', 'Venue Staff', 'Technical Support']

export const users = [
  { name: 'Alicia Tan', role: 'Event Coordinator', initials: 'AT' },
  { name: 'Marcus Lim', role: 'Event Coordinator', initials: 'ML' },
  { name: 'Priya Nair', role: 'Event Coordinator', initials: 'PN' },
]

export const initialRequests: MockRequest[] = [
  { id: 1, title: 'Southeast Asia Technology Conference', date: '24 Oct 2026', venue: 'Auditorium, 300 seats', attendance: '280', status: 'Pending' },
  { id: 2, title: 'Design Thinking Workshop', date: '02 Nov 2026', venue: 'Innovation Lab', attendance: '70', status: 'Pending' },
]

export const initialEvent: EventData = {
  title: 'Southeast Asia Technology Conference',
  description: 'A one-day conference connecting students and technology leaders.',
  purpose: 'Share practical insights about emerging technology careers.',
  date: '24 Oct 2026, 9:00 AM - 5:00 PM',
  venue: 'Auditorium, 300 seats',
  equipment: 'Projector, 2 wireless microphones, stage lighting',
  attendance: '280 attendees',
}
