import type { MockRequest, Role } from './types'

export const roles: Role[] = [
  'Requester',
  'Event Coordinator',
  'Venue Staff',
  'Technical Support',
]

export const users = [
  { id: '11111111-1111-4111-8111-111111111111', name: 'Alicia Tan', role: 'Event Coordinator', initials: 'AT' },
  { id: '22222222-2222-4222-8222-222222222222', name: 'Marcus Lim', role: 'Event Coordinator', initials: 'ML' },
  { id: '33333333-3333-4333-8333-333333333333', name: 'Priya Nair', role: 'Event Coordinator', initials: 'PN' },
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

