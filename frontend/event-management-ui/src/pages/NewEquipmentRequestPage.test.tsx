import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import { NewEquipmentRequestPage } from './NewEquipmentRequestPage'
import { fetchEquipment } from '../features/equipment/equipment'
import type { Equipment } from '../features/equipment/equipment'
import { createEquipmentRequests, fetchRequestableEvents } from '../features/equipment/requests'
import type { SubmittedEvent } from '../features/event/submission'
import type { Role, User } from '../types'

vi.mock('../features/equipment/equipment', () => ({ fetchEquipment: vi.fn() }))
vi.mock('../features/equipment/requests', () => ({ fetchRequestableEvents: vi.fn(), createEquipmentRequests: vi.fn() }))
vi.mock('../components/SubmissionPopup', () => ({
  SubmissionPopup: ({ title, messages }: { title: string; messages: string[] }) => (
    <section aria-label={title}>{messages.map((message) => <p key={message}>{message}</p>)}</section>
  ),
}))

const coordinator: User = { id: 'coord-1', username: 'Alicia', email: 'a@x.com', role: 'Event Coordinator', organization: 'O' }

const mic: Equipment = { id: 'eq-mic', type: 'Microphone', description: 'Wireless mic', totalQuantity: 10, location: 'AV', status: 'Available', setupRequirements: '' }
const chair: Equipment = { ...mic, id: 'eq-chair', type: 'Chair', description: 'Folding chair', totalQuantity: 300 }

const event = (overrides: Partial<SubmittedEvent> = {}) => ({
  id: 'ev1', eventName: 'Hackday', status: 'Under Review', preferredStartDate: '2026-11-01T09:00:00', preferredEndDate: '2026-11-01T17:00:00',
  ...overrides,
}) as SubmittedEvent

const onBack = vi.fn()
const onCreated = vi.fn()

beforeEach(() => {
  vi.mocked(fetchRequestableEvents).mockReset().mockResolvedValue([event(), event({ id: 'ev2', eventName: 'Gala', status: 'Under Review' })])
  vi.mocked(fetchEquipment).mockReset().mockResolvedValue([mic, chair])
  vi.mocked(createEquipmentRequests).mockReset().mockResolvedValue([])
  onBack.mockReset()
  onCreated.mockReset()
})

const show = (role: Role = 'Event Coordinator') =>
  render(<NewEquipmentRequestPage role={role} user={{ ...coordinator, role }} onBack={onBack} onCreated={onCreated} />)

const row = (n: number) => screen.getAllByRole('group', { name: 'Equipment row' })[n - 1]
const rowCount = () => screen.queryAllByRole('group', { name: 'Equipment row' }).length

async function fillRow(n: number, equipmentId: string, quantity: string, requirements = '') {
  const scope = within(row(n))
  await userEvent.selectOptions(scope.getByLabelText(/^Equipment/), equipmentId)
  if (quantity) await userEvent.type(scope.getByLabelText(/^Quantity/), quantity)
  if (requirements) await userEvent.type(scope.getByLabelText('Technical requirements'), requirements)
}

const addedRows = () => within(screen.getByRole('table', { name: 'Added equipment' })).getAllByRole('row').slice(1)

// Create request AC1 (access): only Event Coordinators can record equipment needs.
test('other roles see the access notice and nothing is loaded', () => {
  show('Technical Support')
  expect(screen.getByText('Only Event Coordinators can request equipment.')).toBeInTheDocument()
  expect(fetchRequestableEvents).not.toHaveBeenCalled()
  expect(fetchEquipment).not.toHaveBeenCalled()
})

// Create request AC1/AC2: equipment and type are selectable against the corresponding event schedule.
test('the event dropdown lists the coordinator\'s requestable events and equipment comes from the Available catalogue', async () => {
  show()
  const select = await screen.findByLabelText(/^Event/)
  expect(fetchRequestableEvents).toHaveBeenCalledWith('coord-1')
  expect(fetchEquipment).toHaveBeenCalledWith('Available')
  expect(within(select).getAllByRole('option').map((option) => option.textContent)).toEqual([
    'Choose an event…',
    expect.stringMatching(/^Hackday · .*\(Under Review\)$/),
    expect.stringMatching(/^Gala · .*\(Under Review\)$/),
  ])
  expect(within(row(1)).getAllByRole('option').map((option) => option.textContent)).toEqual([
    'Choose equipment…', 'Wireless mic (Microphone)', 'Folding chair (Chair)',
  ])
})

// Create request AC1: added lines retain equipment, type, quantity and technical requirements.
test('+ adds the row to the Added equipment list and leaves an empty row ready', async () => {
  show()
  await screen.findByLabelText(/^Event/)
  await fillRow(1, 'eq-mic', '4', '2 handheld')

  await userEvent.click(within(row(1)).getByRole('button', { name: 'Add this equipment' }))

  expect(addedRows()).toHaveLength(1)
  expect(within(addedRows()[0]).getAllByRole('cell').map((cell) => cell.textContent)).toEqual(['Wireless mic', 'Microphone', '4', '2 handheld', ''])
  expect(rowCount()).toBe(1)
  expect(within(row(1)).getByLabelText(/^Equipment/)).toHaveValue('')
})

// Create request AC1 (validation): incomplete equipment selections and invalid quantities are not recorded.
test.each([
  ['', '3', 'Choose the equipment to request.'],
  ['eq-mic', '', 'Quantity must be a whole number of at least 1.'],
  ['eq-mic', '0', 'Quantity must be a whole number of at least 1.'],
  ['eq-mic', '1.5', 'Quantity must be a whole number of at least 1.'],
])('+ refuses an incomplete row (equipment %j, quantity %j)', async (equipmentId, quantity, message) => {
  show()
  await screen.findByLabelText(/^Event/)
  if (equipmentId) await userEvent.selectOptions(within(row(1)).getByLabelText(/^Equipment/), equipmentId)
  if (quantity) await userEvent.type(within(row(1)).getByLabelText(/^Quantity/), quantity)

  await userEvent.click(within(row(1)).getByRole('button', { name: 'Add this equipment' }))

  expect(within(row(1)).getByRole('alert')).toHaveTextContent(message)
  expect(screen.queryByRole('table', { name: 'Added equipment' })).not.toBeInTheDocument()
})

// Create request AC1 (validation): duplicate lines within one submission are prevented.
test('the same equipment cannot be added twice', async () => {
  show()
  await screen.findByLabelText(/^Event/)
  await fillRow(1, 'eq-mic', '2')
  await userEvent.click(within(row(1)).getByRole('button', { name: 'Add this equipment' }))
  await fillRow(1, 'eq-mic', '5')

  await userEvent.click(within(row(1)).getByRole('button', { name: 'Add this equipment' }))

  expect(within(row(1)).getByRole('alert')).toHaveTextContent('already in the request')
  expect(addedRows()).toHaveLength(1)
})

// Create request AC1 (form controls): clearing an unfinished row preserves already-added requirements.
test('there is a single input row with no separate Add equipment button, and − clears it', async () => {
  show()
  await screen.findByLabelText(/^Event/)
  expect(rowCount()).toBe(1)
  expect(screen.queryByRole('button', { name: 'Add equipment' })).not.toBeInTheDocument()
  await fillRow(1, 'eq-chair', '40', 'Rows of 10')
  await userEvent.click(within(row(1)).getByRole('button', { name: 'Add this equipment' }))
  await fillRow(1, 'eq-mic', '0')
  await userEvent.click(within(row(1)).getByRole('button', { name: 'Add this equipment' }))

  await userEvent.click(within(row(1)).getByRole('button', { name: 'Clear this row' }))

  expect(rowCount()).toBe(1)
  expect(within(row(1)).getByLabelText(/^Equipment/)).toHaveValue('')
  expect(within(row(1)).getByLabelText(/^Quantity/)).toHaveValue(null)
  expect(within(row(1)).queryByRole('alert')).not.toBeInTheDocument()
  expect(addedRows()).toHaveLength(1)
})

// Create request AC1 (form controls): removed equipment is excluded from the draft request.
test('an added item can be removed from the request', async () => {
  show()
  await screen.findByLabelText(/^Event/)
  await fillRow(1, 'eq-mic', '2')
  await userEvent.click(within(row(1)).getByRole('button', { name: 'Add this equipment' }))

  await userEvent.click(screen.getByRole('button', { name: 'Remove Wireless mic' }))

  expect(screen.queryByRole('table', { name: 'Added equipment' })).not.toBeInTheDocument()
})

// Create request AC1/AC2: submit all equipment needs linked to the selected event, which owns the schedule.
test('submitting sends the event and every added item, then reports success', async () => {
  show()
  await userEvent.selectOptions(await screen.findByLabelText(/^Event/), 'ev2')
  await fillRow(1, 'eq-mic', '4', ' 2 lapel ')
  await userEvent.click(within(row(1)).getByRole('button', { name: 'Add this equipment' }))
  await fillRow(1, 'eq-chair', '60')
  await userEvent.click(within(row(1)).getByRole('button', { name: 'Add this equipment' }))

  await userEvent.click(screen.getByRole('button', { name: 'Submit request' }))

  await waitFor(() => expect(onCreated).toHaveBeenCalledWith('Requested 2 equipment items for Gala.'))
  expect(createEquipmentRequests).toHaveBeenCalledWith('ev2', [
    { equipmentId: 'eq-mic', quantityRequested: 4, technicalRequirements: '2 lapel' },
    { equipmentId: 'eq-chair', quantityRequested: 60, technicalRequirements: '' },
  ], expect.objectContaining({ id: 'coord-1' }))
})

// Create request AC1/AC2 (validation): recording requires equipment needs and a corresponding event.
test('submitting without an event or any added item lists what is missing', async () => {
  show()
  await screen.findByLabelText(/^Event/)

  await userEvent.click(screen.getByRole('button', { name: 'Submit request' }))

  const popup = screen.getByRole('region', { name: 'Check Equipment Request' })
  expect(popup).toHaveTextContent('Choose the event to request equipment for.')
  expect(popup).toHaveTextContent('Add at least one equipment item with the + button.')
  expect(createEquipmentRequests).not.toHaveBeenCalled()
})

// Create request AC1 (validation): entered equipment needs must not be silently omitted.
test('a filled-in row that was never added blocks submission so it is not silently dropped', async () => {
  show()
  await userEvent.selectOptions(await screen.findByLabelText(/^Event/), 'ev1')
  await fillRow(1, 'eq-mic', '2')
  await userEvent.click(within(row(1)).getByRole('button', { name: 'Add this equipment' }))
  await fillRow(1, 'eq-chair', '5')

  await userEvent.click(screen.getByRole('button', { name: 'Submit request' }))

  expect(screen.getByRole('region', { name: 'Check Equipment Request' })).toHaveTextContent('still being filled in')
  expect(createEquipmentRequests).not.toHaveBeenCalled()
})

// Create request AC1 (failure): a failed save preserves the equipment needs for correction or retry.
test('a rejected submission shows the service message and keeps the form', async () => {
  vi.mocked(createEquipmentRequests).mockRejectedValue(new Error('This equipment is Unavailable: Wireless mic.'))
  show()
  await userEvent.selectOptions(await screen.findByLabelText(/^Event/), 'ev1')
  await fillRow(1, 'eq-mic', '2')
  await userEvent.click(within(row(1)).getByRole('button', { name: 'Add this equipment' }))

  await userEvent.click(screen.getByRole('button', { name: 'Submit request' }))

  expect(await screen.findByRole('region', { name: 'Submission Failed' })).toHaveTextContent('Unavailable: Wireless mic')
  expect(addedRows()).toHaveLength(1)
  expect(onCreated).not.toHaveBeenCalled()
})

// Create request AC1/AC2 (eligibility): no request can be recorded without an eligible assigned event.
test('with no requestable events the form explains why and cannot be submitted', async () => {
  vi.mocked(fetchRequestableEvents).mockResolvedValue([])
  show()
  expect(await screen.findByText('You have no eligible events assigned to you.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Submit request' })).toBeDisabled()
})

// Create request AC1 (eligibility): no equipment can be selected from an empty Available catalogue.
test('with no Available equipment there are no rows to fill in', async () => {
  vi.mocked(fetchEquipment).mockResolvedValue([])
  show()
  expect(await screen.findByText('No equipment is currently Available to request.')).toBeInTheDocument()
  expect(rowCount()).toBe(0)
})

// Create request AC1 (supporting failure/navigation): loading errors are visible and the form can be exited.
test('a load failure is shown and Back / Cancel return to the list', async () => {
  vi.mocked(fetchEquipment).mockRejectedValueOnce(new Error('Equipment Service is down.'))
  const { unmount } = show()
  expect(await screen.findByRole('alert')).toHaveTextContent('Equipment Service is down.')
  await userEvent.click(screen.getByRole('button', { name: /Back to equipment requests/ }))
  unmount()

  show()
  await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
  expect(onBack).toHaveBeenCalledTimes(2)
})
