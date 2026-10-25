/** SCRUM-45 AC2/AC3: organiser can inspect the recorded request decision and reason. */
import { render, screen } from '@testing-library/react'
import { test, expect, vi } from 'vitest'
import { OrganiserEventDetailPage } from './OrganiserEventDetailPage'
import { eventApi } from '../features/event/submission'
vi.mock('../features/event/submission', () => ({ eventApi: vi.fn() }))
test('rejected organiser request displays decision and full rejection reason', async () => {
  vi.mocked(eventApi).mockResolvedValue({
    id: '30000000-0000-0000-0000-000000000001', eventName: 'Community Workshop',
    status: 'Rejected', description: 'Workshop', expectedAttendance: '30',
    preferredStartDate: '2099-01-01T09:00', preferredEndDate: '2099-01-01T12:00',
    decision: { status: 'Rejected', reason: 'The proposal needs a safety plan.\nPlease revise.' },
  })
  render(<OrganiserEventDetailPage eventId="30000000-0000-0000-0000-000000000001"
    organiserId="10000000-0000-0000-0000-000000000001" backLabel="My events" onBack={vi.fn()} />)
  expect(await screen.findByRole('heading', { name: 'Event request decision' })).toBeInTheDocument()
  expect(screen.getByText('Rejection reason')).toBeInTheDocument()
  expect(screen.getByText(/The proposal needs a safety plan/)).toHaveTextContent('Please revise.')
})
