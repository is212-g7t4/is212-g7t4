import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import { EquipmentPage } from './EquipmentPage'
import { createEquipment, fetchEquipment } from '../features/equipment/equipment'
import type { Role, User } from '../types'

vi.mock('../features/equipment/equipment', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../features/equipment/equipment')>()),
  fetchEquipment: vi.fn(),
  createEquipment: vi.fn(),
}))

const user: User = { id: 'u1', username: 'Wei', email: 'w@x.com', role: 'Technical Support', organization: 'O', managerId: null }
const projector = { id: 'e1', type: 'Projector', description: '4K projector', totalQuantity: 5, location: 'Store', status: 'Available', setupRequirements: 'Mount it.' }

beforeEach(() => {
  vi.mocked(fetchEquipment).mockReset().mockResolvedValue([projector])
  vi.mocked(createEquipment).mockReset().mockResolvedValue(projector)
})

const show = (role: Role = 'Technical Support') => render(<EquipmentPage role={role} user={user} />)

test('lists available equipment by default', async () => {
  show()
  expect(await screen.findByText('4K projector')).toBeInTheDocument()
  expect(fetchEquipment).toHaveBeenCalledWith('Available')
})

test('other roles see the access notice and no request is made', () => {
  show('Event Coordinator')
  expect(screen.getByText(/visible to Technical Support/)).toBeInTheDocument()
  expect(fetchEquipment).not.toHaveBeenCalled()
})

test('filter All fetches without a status', async () => {
  show()
  await screen.findByText('4K projector')
  await userEvent.selectOptions(screen.getByLabelText('Filter by status'), 'All')
  await waitFor(() => expect(fetchEquipment).toHaveBeenLastCalledWith(undefined))
})

test('shows an empty state and a load error', async () => {
  vi.mocked(fetchEquipment).mockResolvedValueOnce([])
  const { unmount } = show()
  expect(await screen.findByText('No equipment found.')).toBeInTheDocument()
  unmount()
  vi.mocked(fetchEquipment).mockRejectedValueOnce(new Error('boom'))
  show()
  expect(await screen.findByRole('alert')).toHaveTextContent('boom')
})

async function fill(description: string, quantity: string, location: string) {
  await screen.findByText('4K projector')
  await userEvent.type(screen.getByLabelText(/Description/), description)
  await userEvent.type(screen.getByLabelText(/Total quantity/), quantity)
  await userEvent.type(screen.getByLabelText(/Location/), location)
  await userEvent.click(screen.getByRole('button', { name: 'Add equipment' }))
}

test('submits a new record, confirms it and reloads the list', async () => {
  show()
  await fill(' Laptop A ', '3', ' Store ')
  expect(await screen.findByText('Added Projector: 4K projector.')).toBeInTheDocument()
  expect(createEquipment).toHaveBeenCalledWith(
    { equipmentType: 'Microphone', description: 'Laptop A', totalQuantity: 3, location: 'Store', status: 'Available' },
    user,
  )
  expect(fetchEquipment).toHaveBeenCalledTimes(2)
})

test('validates before sending', async () => {
  show()
  await fill('Thing', '-1', 'Store')
  expect(await screen.findByRole('alert')).toHaveTextContent('whole number')
  expect(createEquipment).not.toHaveBeenCalled()
})

test('requires description and location', async () => {
  show()
  await screen.findByText('4K projector')
  await userEvent.type(screen.getByLabelText(/Total quantity/), '2')
  await userEvent.click(screen.getByRole('button', { name: 'Add equipment' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('required')
})

test('shows the service error when saving fails', async () => {
  vi.mocked(createEquipment).mockRejectedValueOnce(new Error('Only Technical Support can add equipment.'))
  show()
  await fill('Thing', '1', 'Store')
  expect(await screen.findByRole('alert')).toHaveTextContent('Only Technical Support')
})

test('"Add new…" reveals a field and submits the custom type', async () => {
  show()
  await screen.findByText('4K projector')
  await userEvent.selectOptions(screen.getByLabelText(/^Type/), 'Add new…')
  await userEvent.type(screen.getByLabelText(/New equipment type/), '  Drone ')
  await userEvent.type(screen.getByLabelText(/Description/), 'Camera drone')
  await userEvent.type(screen.getByLabelText(/Total quantity/), '2')
  await userEvent.type(screen.getByLabelText(/Location/), 'Store')
  await userEvent.click(screen.getByRole('button', { name: 'Add equipment' }))
  await waitFor(() => expect(createEquipment).toHaveBeenCalled())
  expect(vi.mocked(createEquipment).mock.calls[0][0]).toMatchObject({ equipmentType: 'Drone' })
  expect(screen.queryByLabelText(/New equipment type/)).toBeInTheDocument()
})

test('a new type name is required and length-limited', async () => {
  show()
  await screen.findByText('4K projector')
  await userEvent.selectOptions(screen.getByLabelText(/^Type/), 'Add new…')
  await userEvent.type(screen.getByLabelText(/Description/), 'Thing')
  await userEvent.type(screen.getByLabelText(/Total quantity/), '1')
  await userEvent.type(screen.getByLabelText(/Location/), 'Store')
  await userEvent.click(screen.getByRole('button', { name: 'Add equipment' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('name for the new equipment type')
  await userEvent.click(screen.getByLabelText(/New equipment type/))
  await userEvent.paste('x'.repeat(101))
  await userEvent.click(screen.getByRole('button', { name: 'Add equipment' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('100 characters')
  expect(createEquipment).not.toHaveBeenCalled()
})
