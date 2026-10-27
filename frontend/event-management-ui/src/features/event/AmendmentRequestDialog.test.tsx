import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { AmendmentRequestDialog } from './AmendmentRequestDialog'

// SCRUM-16 AC1/AC2: the coordinator must flag at least one field and give a reason.

function renderDialog(props: Partial<Parameters<typeof AmendmentRequestDialog>[0]> = {}) {
  const onConfirm = vi.fn()
  const onCancel = vi.fn()
  render(<AmendmentRequestDialog eventName="Community Workshop" submitting={false} onCancel={onCancel} onConfirm={onConfirm} {...props} />)
  return { onConfirm, onCancel, send: () => screen.getByRole('button', { name: 'Send amendment request' }) }
}

test('AC1: confirm stays disabled until a field is flagged and a reason is given', () => {
  const { send } = renderDialog()
  expect(send()).toBeDisabled()

  fireEvent.click(screen.getByRole('checkbox', { name: 'Expected attendance' }))
  expect(send()).toBeDisabled()

  fireEvent.change(screen.getByLabelText(/Reason or details/), { target: { value: '   ' } })
  expect(send()).toBeDisabled()

  fireEvent.change(screen.getByLabelText(/Reason or details/), { target: { value: 'Too many guests.' } })
  expect(send()).toBeEnabled()

  fireEvent.click(screen.getByRole('checkbox', { name: 'Expected attendance' }))
  expect(send()).toBeDisabled()
})

test('AC1: "Date/time" is one checkbox that flags both dates', () => {
  const { onConfirm, send } = renderDialog()
  expect(screen.getAllByRole('checkbox', { name: 'Date/time' })).toHaveLength(1)

  fireEvent.click(screen.getByRole('checkbox', { name: 'Date/time' }))
  fireEvent.change(screen.getByLabelText(/Reason or details/), { target: { value: '  The hall is booked.  ' } })
  fireEvent.click(send())

  expect(onConfirm).toHaveBeenCalledWith(['preferredStartDate', 'preferredEndDate'], 'The hall is booked.')
})

test('AC1: every amendable field is offered, and the withdrawal deadline is not', () => {
  renderDialog()
  const labels = screen.getAllByRole('checkbox').map((box) => box.parentElement?.textContent?.trim())
  expect(labels).toEqual([
    'Event name', 'Date/time', 'Expected attendance', 'Venue requirements', 'Accessibility needs',
    'Equipment requirements', 'Description', 'Purpose', 'Registration needs',
  ])
})

test('AC2: the reason shows a live 1000-character counter', () => {
  renderDialog()
  const reason = screen.getByLabelText(/Reason or details/)
  expect(reason).toHaveAttribute('maxLength', '1000')
  expect(screen.getByText('0/1000 characters')).toBeInTheDocument()
  fireEvent.change(reason, { target: { value: 'x'.repeat(42) } })
  expect(screen.getByText('42/1000 characters')).toBeInTheDocument()
})

test('an API error is shown, and Cancel and Escape both close', () => {
  const { onCancel } = renderDialog({ error: 'Event request not found.' })
  expect(screen.getByRole('alert')).toHaveTextContent('Event request not found.')

  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  fireEvent(screen.getByRole('dialog'), new Event('cancel', { cancelable: true }))
  expect(onCancel).toHaveBeenCalledTimes(2)
})

test('while sending, every control is disabled', () => {
  renderDialog({ submitting: true })
  expect(screen.getByRole('button', { name: 'Sending…' })).toBeDisabled()
  expect(screen.getByRole('checkbox', { name: 'Purpose' })).toBeDisabled()
  expect(screen.getByLabelText(/Reason or details/)).toBeDisabled()
})
