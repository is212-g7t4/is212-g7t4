import type { MockRequest, Role } from './types'

export const roles: Role[] = [
  'Requester',
  'Event Coordinator',
  'Venue Staff',
  'Technical Support',
]

export const users = [
  { name: 'Alicia Tan', role: 'Event Coordinator', initials: 'AT' },
  { name: 'Marcus Lim', role: 'Event Coordinator', initials: 'ML' },
  { name: 'Priya Nair', role: 'Event Coordinator', initials: 'PN' },
]

export const initialRequests: MockRequest[] = [
  {
    id: 1,
    title: 'Southeast Asia Technology Conference',
    date: '24 Oct 2026',
    venue: 'Auditorium, 300 seats',
    attendance: '280',
    status: 'Pending',
  },
  {
    id: 2,
    title: 'Design Thinking Workshop',
    date: '02 Nov 2026',
    venue: 'Innovation Lab',
    attendance: '70',
    status: 'Pending',
  },
]

