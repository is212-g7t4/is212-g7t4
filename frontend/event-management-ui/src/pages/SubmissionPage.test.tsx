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

const ORGANISER_ID = '33333333-3333-4333-8333-333333333333'

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

  test('AC1: saves partial details as a draft without requiring the other fields', async () => {
    vi.mocked(eventApi).mockResolvedValue({ id: 'draft-1', status: 'Draft' })
    render(<SubmissionPage role="Event Organiser" currentOrganiserId={ORGANISER_ID} />)
    const user = userEvent.setup()
    await user.type(screen.getByLabelText(/Event Name/), 'Community Workshop')

    await user.click(screen.getByRole('button', { name: 'Save as Draft' }))

    expect(await screen.findByText(/Draft saved\. Only you can see it/)).toBeInTheDocument()
    expect(eventApi).toHaveBeenCalledExactlyOnceWith('/events/drafts', expect.objectContaining({
      eventName: 'Community Workshop', description: '', expectedAttendance: '', organiserId: ORGANISER_ID,
    }))
  })

  test('AC1: while a draft saves, only the save button shows progress', async () => {
    vi.mocked(eventApi).mockReturnValue(new Promise(() => {}))
    render(<SubmissionPage role="Event Organiser" currentOrganiserId={ORGANISER_ID} />)
    const user = userEvent.setup()
    await user.type(screen.getByLabelText(/Event Name/), 'Community Workshop')

    await user.click(screen.getByRole('button', { name: 'Save as Draft' }))

    expect(await screen.findByRole('button', { name: 'Saving…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Submit Request' })).toBeDisabled()
    expect(screen.queryByText('Submitting…')).not.toBeInTheDocument()
  })

  test('AC1: asks for an Event Name before saving a draft', async () => {
    render(<SubmissionPage role="Event Organiser" currentOrganiserId={ORGANISER_ID} />)

    await userEvent.setup().click(screen.getByRole('button', { name: 'Save as Draft' }))

    expect(screen.getByRole('region', { name: 'Name Your Draft' })).toHaveTextContent('Event Name')
    expect(eventApi).not.toHaveBeenCalled()
  })

  test('AC2: opening a draft pre-fills the form and saving updates that same draft', async () => {
    vi.mocked(eventApi).mockResolvedValueOnce({ id: 'draft-2', eventName: 'Winter Gala', description: 'Year-end party', status: 'Draft' })
      .mockResolvedValue({ id: 'draft-2', status: 'Draft' })
    render(<SubmissionPage role="Event Organiser" currentOrganiserId={ORGANISER_ID} draftId="draft-2" />)
    const user = userEvent.setup()

    expect(await screen.findByDisplayValue('Winter Gala')).toBeInTheDocument()
    expect(eventApi).toHaveBeenCalledWith(`/events/draft-2?organiserId=${ORGANISER_ID}`)
    await user.type(screen.getByLabelText(/Purpose/), 'Celebrate')
    await user.click(screen.getByRole('button', { name: 'Save as Draft' }))
    await screen.findByText(/Draft saved/)
    await user.click(screen.getByRole('button', { name: 'Save as Draft' }))

    await waitFor(() => expect(eventApi).toHaveBeenCalledTimes(3))
    for (const call of vi.mocked(eventApi).mock.calls.slice(1)) {
      expect(call).toEqual(['/events/drafts/draft-2', expect.objectContaining({ eventName: 'Winter Gala', purpose: 'Celebrate' }), 'PATCH'])
    }
  })

  test('AC5: submitting an opened draft submits that draft, not a new request', async () => {
    vi.mocked(eventApi).mockResolvedValueOnce({ id: 'draft-2', eventName: 'Community Workshop', status: 'Draft' })
      .mockResolvedValue({ eventName: 'Community Workshop', submittedAt: '2026-10-21T01:30:00+00:00' })
    render(<SubmissionPage role="Event Organiser" currentOrganiserId={ORGANISER_ID} draftId="draft-2" />)
    await screen.findByDisplayValue('Community Workshop')
    await userEvent.setup().clear(screen.getByLabelText(/Event Name/))
    const user = await completeForm('40')

    await user.click(screen.getByRole('button', { name: 'Submit Request' }))

    expect(await screen.findByText(/Community Workshop was submitted on/)).toBeInTheDocument()
    expect(eventApi).toHaveBeenLastCalledWith('/events/drafts/draft-2/submit', expect.objectContaining({ organiserId: ORGANISER_ID, expectedAttendance: '40' }))
    expect(eventApi).not.toHaveBeenCalledWith('/events', expect.anything())
  })

  test('AC5: submitting an incomplete draft lists the missing fields and does not submit', async () => {
    vi.mocked(eventApi).mockResolvedValueOnce({ id: 'draft-2', eventName: 'Winter Gala', status: 'Draft' })
    render(<SubmissionPage role="Event Organiser" currentOrganiserId={ORGANISER_ID} draftId="draft-2" />)
    await screen.findByDisplayValue('Winter Gala')

    await userEvent.setup().click(screen.getByRole('button', { name: 'Submit Request' }))

    expect(screen.getByRole('region', { name: 'Missing Required Fields' })).toHaveTextContent('Description')
    expect(eventApi).toHaveBeenCalledOnce()  // only the draft load
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
