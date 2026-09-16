import type { MockRequest, Role } from './types'

export const roles: Role[] = [
  'Requester',
  'Event Coordinator',
  'Venue Staff',
  'Technical Support',
]

export const users = [
  { id: 'e7334aa9-eb3a-4c45-84b5-280501b6c109', name: 'Alicia Tan', role: 'Event Coordinator', initials: 'AT' },
  { id: '7912075d-46f5-405b-9af3-05502f42f173', name: 'Marcus Lim', role: 'Event Coordinator', initials: 'ML' },
  { id: '7110f1a8-e707-4b76-9fb0-57808310da98', name: 'Priya Nair', role: 'Event Coordinator', initials: 'PN' },
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

