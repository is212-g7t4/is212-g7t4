import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import type { SubmittedEvent } from './submission'
import { ChangeRequestDialog } from './ChangeRequestDialog'

const event: SubmittedEvent = {
  id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  eventName: 'Community Workshop',
  description: 'Original description',
  purpose: 'Learning',
  preferredStartDate: '2026-11-01T09:00',
  preferredEndDate: '2026-11-01T12:00',
  expectedAttendance: '30',
  venueRequirements: 'Seminar room',
  accessibilityNeeds: 'Step-free access',
  equipmentRequirements: 'Projector',
  registrationNeeds: 'Online registration',
  status: 'Under Review',
  submittedAt: '2026-10-01T00:00:00Z',
  coordinatorId: null,
  organiserId: '11111111-1111-4111-8111-111111111111',
  decision: null,
  decisionHistory: [],
  actionDetails: '',
  actionHistory: [],
}

afterEach(() => vi.unstubAllGlobals())

test('requires a real field change and a justification, then submits only changed fields', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'Pending Review' }) })
  vi.stubGlobal('fetch', fetchMock)
  const submitted = vi.fn()
  render(<ChangeRequestDialog event={event} organiserId={event.organiserId!} onCancel={vi.fn()} onSubmitted={submitted} />)

  const submit = screen.getByRole('button', { name: 'Submit change request' })
  expect(submit).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Expected Attendance'), { target: { value: '40' } })
  expect(submit).toBeDisabled()
  fireEvent.change(screen.getByLabelText(/Reason or justification/), { target: { value: 'More guests accepted.' } })
  expect(submit).toBeEnabled()
  fireEvent.click(submit)

  await waitFor(() => expect(submitted).toHaveBeenCalledOnce())
  const [, options] = fetchMock.mock.calls[0]
  expect(JSON.parse(options.body)).toEqual({
    organiserId: event.organiserId,
    changes: { expectedAttendance: '40' },
    reason: 'More guests accepted.',
  })
  expect(screen.queryByText(/attachment/i)).not.toBeInTheDocument()
})

test('shows the service error and keeps the form open', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: false,
    json: async () => ({ message: 'This event already has a change request pending review.' }),
  }))
  render(<ChangeRequestDialog event={event} organiserId={event.organiserId!} onCancel={vi.fn()} onSubmitted={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('Purpose'), { target: { value: 'Updated purpose' } })
  fireEvent.change(screen.getByLabelText(/Reason or justification/), { target: { value: 'The programme changed.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Submit change request' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('already has a change request')
})
