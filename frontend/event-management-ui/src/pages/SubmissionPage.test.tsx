import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { eventApi, validateEvent } from '../features/event/submission'
import { SubmissionPage } from './SubmissionPage'

vi.mock('../features/event/submission', async () => {
  const actual = await vi.importActual<typeof import('../features/event/submission')>('../features/event/submission')
  return { ...actual, eventApi: vi.fn() }
})
vi.mock('../components/SubmissionPopup', () => ({
  SubmissionPopup: ({ title, messages }: { title: string; messages: string[] }) => (
    <section aria-label={title}>{messages.map((message) => <p key={message}>{message}</p>)}</section>
  ),
}))

async function completeForm(expectedAttendance: string) {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText(/Event Name/), 'Community Workshop')
  await user.type(screen.getByLabelText(/Description/), 'A practical workshop')
  await user.type(screen.getByLabelText(/Purpose/), 'Learning')
  fireEvent.change(screen.getByLabelText(/Preferred Start Date/), { target: { value: '2026-11-10T09:00' } })
  fireEvent.change(screen.getByLabelText(/Preferred End Date/), { target: { value: '2026-11-10T12:00' } })
  fireEvent.change(screen.getByLabelText(/Expected Attendance/), { target: { value: expectedAttendance } })
  return user
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(eventApi).mockResolvedValue({
    eventName: 'Community Workshop',
    submittedAt: '2026-10-03T01:30:00+00:00',
  })
})

describe('event request submission', () => {
  test('allows an Event Organiser to open the request form', async () => {
    render(<SubmissionPage role="Event Organiser" />)

    expect(screen.getByRole('heading', { name: 'Create Event Request' })).toBeVisible()
    // Venues are chosen later as booking requests, not on the event request.
    expect(screen.queryByLabelText('Venue')).not.toBeInTheDocument()
  })

  test.each(['Event Coordinator', 'Venue Staff'] as const)('does not let %s submit event requests', (role) => {
    render(<SubmissionPage role={role} />)

    expect(screen.getByText('Only Event Organisers can submit event requests.')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Create Event Request' })).not.toBeInTheDocument()
  })

  test('confirms a successful submission without a venue', async () => {
    render(<SubmissionPage role="Event Organiser" />)
    const user = await completeForm('40')

    await user.click(screen.getByRole('button', { name: 'Submit Request' }))

    expect(await screen.findByText(/Community Workshop was submitted on/)).toBeInTheDocument()
    expect(eventApi).toHaveBeenCalledOnce()
    expect(vi.mocked(eventApi).mock.calls[0][1]).not.toHaveProperty('venueId')
  })

  test.each(['', '-1'])('blocks blank or negative attendance with a field error', async (attendance) => {
    render(<SubmissionPage role="Event Organiser" />)
    const user = await completeForm(attendance)

    await user.click(screen.getByRole('button', { name: 'Submit Request' }))

    await waitFor(() => expect(screen.getByLabelText(/Expected Attendance/).closest('label')).toHaveTextContent(
      attendance ? 'Expected Attendance must be a positive whole number' : 'Expected Attendance is required.',
    ))
    expect(eventApi).not.toHaveBeenCalled()
  })

  test('rejects non-numeric attendance before submission', () => {
    const result = validateEvent({
      eventName: 'Community Workshop', description: 'Workshop', purpose: 'Learning',
      preferredStartDate: '2026-11-10T09:00', preferredEndDate: '2026-11-10T12:00',
      expectedAttendance: 'abc', venueRequirements: '', accessibilityNeeds: '',
      equipmentRequirements: '', registrationNeeds: '',
    })

    expect(result.errors).toContain('Expected Attendance must be a positive whole number (maximum 2147483647).')
  })
})
