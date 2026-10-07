import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import { EquipmentRequestsPage } from './EquipmentRequestsPage'
import { fetchEventReservations, reviewAllEventEquipmentRequests, reviewEquipmentRequest } from '../features/equipment/requests'
import type { EquipmentRequest, EventReservation } from '../features/equipment/requests'
import type { Role, User } from '../types'

vi.mock('../features/equipment/requests', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../features/equipment/requests')>()),
  fetchEventReservations: vi.fn(),
  reviewAllEventEquipmentRequests: vi.fn(),
  reviewEquipmentRequest: vi.fn(),
}))

const user: User = { id: 'u1', username: 'Wei', email: 'w@x.com', role: 'Technical Support', organization: 'O', managerId: null }

const line = (overrides: Partial<EquipmentRequest> = {}): EquipmentRequest => ({
  id: 'r1',
  eventId: 'ev1',
  equipmentId: 'eq1',
  quantityRequested: 4,
  technicalRequirements: '2 handheld, 2 lapel',
  status: 'Pending',
  reviewedBy: null,
  equipment: { description: 'Wireless mic', type: 'Microphone', totalQuantity: 9, status: 'Available' },
  availability: { reservedQuantity: 0, availableStock: 9, isInsufficient: false },
  ...overrides,
})
const chair = (overrides: Partial<EquipmentRequest> = {}) => line({
  id: 'r2',
  equipmentId: 'eq2',
  quantityRequested: 50,
  equipment: { description: 'Folding chair', type: 'Chair', totalQuantity: 60, status: 'Available' },
  availability: { reservedQuantity: 40, availableStock: 20, isInsufficient: true },
  ...overrides,
})
const event = (requests: EquipmentRequest[], overrides: Partial<EventReservation> = {}): EventReservation => ({
  eventId: 'ev1', eventName: 'Hackday', eventStatus: 'Approved', startTime: '2026-10-01T09:00:00', endTime: '2026-10-01T17:00:00', requests, ...overrides,
})
const decided = (item: EquipmentRequest, status: 'Approved' | 'Rejected') => ({
  id: item.id, eventId: item.eventId, equipmentId: item.equipmentId, quantityRequested: item.quantityRequested,
  technicalRequirements: item.technicalRequirements, status, reviewedBy: 'u1',
})

beforeEach(() => {
  vi.mocked(fetchEventReservations).mockReset().mockResolvedValue([event([line()])])
  vi.mocked(reviewAllEventEquipmentRequests).mockReset().mockResolvedValue([decided(line(), 'Approved')])
  vi.mocked(reviewEquipmentRequest).mockReset().mockResolvedValue(decided(line(), 'Approved'))
})

const show = (role: Role = 'Technical Support') => render(<EquipmentRequestsPage role={role} user={user} />)
const showAll = async () => {
  await screen.findByText('Wireless mic')
  await userEvent.selectOptions(screen.getByLabelText('Filter by status'), 'All')
  await waitFor(() => expect(fetchEventReservations).toHaveBeenLastCalledWith(user, undefined))
}

test('AC1: shows equipment, type, quantity and technical requirements of pending requests', async () => {
  show()
  expect(await screen.findByRole('heading', { name: 'Hackday' })).toBeInTheDocument()
  const row = screen.getByText('Wireless mic').closest('tr')!
  expect(within(row).getByText('Microphone')).toBeInTheDocument()
  expect(within(row).getByText('4')).toBeInTheDocument()
  expect(within(row).getByText('2 handheld, 2 lapel')).toBeInTheDocument()
  const equipmentCell = within(row).getByText('Wireless mic').closest('td')!
  expect(within(equipmentCell).getByText('Pending')).toHaveClass('status-badge')
  expect(screen.queryByRole('columnheader', { name: 'Status' })).not.toBeInTheDocument()
  expect(fetchEventReservations).toHaveBeenCalledWith(user, 'Pending')
})

test('groups every requested item of one event under a single event card', async () => {
  vi.mocked(fetchEventReservations).mockResolvedValue([
    event([line(), chair({ availability: { reservedQuantity: 0, availableStock: 60, isInsufficient: false } })]),
    event([line({ id: 'r3', eventId: 'ev2' })], { eventId: 'ev2', eventName: 'Gala' }),
  ])
  show()
  await screen.findByRole('heading', { name: 'Hackday' })
  expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(['Hackday', 'Gala'])
  const card = screen.getByRole('heading', { name: 'Hackday' }).closest('article')!
  expect(within(card).getByText('Wireless mic')).toBeInTheDocument()
  expect(within(card).getByText('Folding chair')).toBeInTheDocument()
})

test('the stock column is labelled Available and shows the remaining unallocated balance', async () => {
  vi.mocked(fetchEventReservations).mockResolvedValue([event([line({ availability: { reservedQuantity: 4, availableStock: 5, isInsufficient: false } })])])
  show()
  const row = (await screen.findByText('Wireless mic')).closest('tr')!
  expect(screen.getByRole('columnheader', { name: 'Available' })).toBeInTheDocument()
  expect(screen.queryByRole('columnheader', { name: 'In stock' })).not.toBeInTheDocument()
  expect(within(row).getByText('5')).toBeInTheDocument()
  expect(within(row).queryByText('9')).not.toBeInTheDocument()
})

test('flags only the lines that exceed the remaining balance as Insufficient', async () => {
  vi.mocked(fetchEventReservations).mockResolvedValue([event([line(), chair()])])
  show()
  const chairRow = (await screen.findByText('Folding chair')).closest('tr')!
  const stockCell = within(chairRow).getByText('Insufficient').closest('td')!
  expect(within(stockCell).getByText('20')).toBeInTheDocument()
  expect(within(stockCell).getByText('Insufficient')).toHaveClass('status-badge')
  expect(within(chairRow).getByText('50')).toBeInTheDocument()
  expect(within(screen.getByText('Wireless mic').closest('tr')!).queryByText('Insufficient')).not.toBeInTheDocument()
})

test('hides the Available and Action columns once nothing in an event is pending', async () => {
  vi.mocked(fetchEventReservations).mockResolvedValue([event([line({ status: 'Approved', reviewedBy: 'u1', availability: null })])])
  show()
  await screen.findByText('Wireless mic')
  expect(screen.queryByRole('columnheader', { name: 'Available' })).not.toBeInTheDocument()
  expect(screen.queryByRole('columnheader', { name: 'Action' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Approve All' })).not.toBeInTheDocument()
  expect(screen.getByRole('columnheader', { name: 'Requested' })).toBeInTheDocument()
})

test('other roles see the access notice and no request is made', () => {
  show('Event Coordinator')
  expect(screen.getByText(/visible to Technical Support/)).toBeInTheDocument()
  expect(fetchEventReservations).not.toHaveBeenCalled()
})

// --- insufficiency gating -------------------------------------------------

test('batch Approve is disabled while any line in the event is insufficient, but Reject stays enabled', async () => {
  vi.mocked(fetchEventReservations).mockResolvedValue([event([line(), chair()])])
  show()
  await screen.findByText('Folding chair')
  const approveAll = screen.getByRole('button', { name: 'Approve All' })
  expect(approveAll).toBeDisabled()
  expect(approveAll).toHaveAttribute('title', expect.stringMatching(/Not enough stock/))
  expect(screen.getByRole('button', { name: 'Reject All' })).toBeEnabled()
  await userEvent.click(approveAll)
  expect(reviewAllEventEquipmentRequests).not.toHaveBeenCalled()
})

test('the insufficient line cannot be approved on its own, but can be rejected', async () => {
  vi.mocked(fetchEventReservations).mockResolvedValue([event([line(), chair()])])
  show()
  const chairRow = (await screen.findByText('Folding chair')).closest('tr')!
  expect(within(chairRow).getByRole('button', { name: 'Approve' })).toBeDisabled()
  expect(within(chairRow).getByRole('button', { name: 'Reject' })).toBeEnabled()
  expect(within(screen.getByText('Wireless mic').closest('tr')!).getByRole('button', { name: 'Approve' })).toBeEnabled()
})

test('batch Approve is enabled again once the insufficient line has been rejected', async () => {
  vi.mocked(fetchEventReservations).mockResolvedValue([event([line(), chair()])])
  vi.mocked(reviewEquipmentRequest).mockResolvedValue(decided(chair(), 'Rejected'))
  show()
  await screen.findByText('Folding chair')
  expect(screen.getByRole('button', { name: 'Approve All' })).toBeDisabled()
  await userEvent.click(within(screen.getByText('Folding chair').closest('tr')!).getByRole('button', { name: 'Reject' }))
  await waitFor(() => expect(screen.queryByText('Folding chair')).not.toBeInTheDocument())
  expect(screen.getByRole('button', { name: 'Approve All' })).toBeEnabled()
})

test('a physically unavailable item shows zero available and is insufficient', async () => {
  vi.mocked(fetchEventReservations).mockResolvedValue([event([line({
    equipment: { description: 'Laptop', type: 'Laptop', totalQuantity: 8, status: 'Unavailable' },
    availability: { reservedQuantity: 0, availableStock: 0, isInsufficient: true },
  })])])
  show()
  const row = (await screen.findByText('Laptop', { selector: 'span' })).closest('tr')!
  expect(within(row).getByText('0')).toBeInTheDocument()
  expect(within(row).getByText('Insufficient')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Approve All' })).toBeDisabled()
})

// --- decisions -------------------------------------------------------------

test('AC2: Approve acts on one equipment row only and the other stays pending', async () => {
  const second = line({ id: 'r2', equipmentId: 'eq2', equipment: { description: 'Folding chair', type: 'Chair', totalQuantity: 60, status: 'Available' } })
  vi.mocked(fetchEventReservations).mockResolvedValue([event([line(), second])])
  show()
  await screen.findByText('Folding chair')
  expect(screen.getAllByRole('button', { name: 'Approve' })).toHaveLength(2)
  await userEvent.click(screen.getAllByRole('button', { name: 'Approve' })[0])
  await waitFor(() => expect(reviewEquipmentRequest).toHaveBeenCalledWith('r1', 'Approved', user))
  await waitFor(() => expect(screen.queryByText('Wireless mic')).not.toBeInTheDocument())
  expect(screen.getByText('Folding chair')).toBeInTheDocument()
  expect(reviewEquipmentRequest).toHaveBeenCalledTimes(1)
})

test('AC2: rejecting one row under the All filter updates only that row and removes its buttons', async () => {
  const second = line({ id: 'r2', equipmentId: 'eq2', equipment: { description: 'Folding chair', type: 'Chair', totalQuantity: 60, status: 'Available' } })
  vi.mocked(fetchEventReservations).mockResolvedValue([event([line(), second])])
  vi.mocked(reviewEquipmentRequest).mockResolvedValue(decided(line(), 'Rejected'))
  show()
  await showAll()
  await userEvent.click((await screen.findAllByRole('button', { name: 'Reject' }))[0])
  await waitFor(() => expect(document.querySelectorAll('.status-badge.rejected')).toHaveLength(1))
  expect(reviewEquipmentRequest).toHaveBeenCalledWith('r1', 'Rejected', user)
  expect(screen.getAllByRole('button', { name: 'Reject' })).toHaveLength(1)
  expect(screen.getByText('Reviewed')).toBeInTheDocument()
})

test('Approve All approves every pending request in the event', async () => {
  const second = line({ id: 'r2', equipmentId: 'eq2' })
  vi.mocked(fetchEventReservations).mockResolvedValue([event([line(), second])])
  vi.mocked(reviewAllEventEquipmentRequests).mockResolvedValue([decided(line(), 'Approved'), decided(second, 'Approved')])
  show()
  const button = await screen.findByRole('button', { name: 'Approve All' })
  expect(button).toBeEnabled()
  expect(button.closest('footer')).toHaveClass('equipment-request-bulk-actions')
  await userEvent.click(button)
  await waitFor(() => expect(reviewAllEventEquipmentRequests).toHaveBeenCalledWith('ev1', 'Approved', user))
  expect(await screen.findByText('No equipment requests found.')).toBeInTheDocument()
})

test('Reject All works even when a line is insufficient and updates all rows under the All filter', async () => {
  const second = chair()
  vi.mocked(fetchEventReservations).mockResolvedValue([event([line(), second])])
  vi.mocked(reviewAllEventEquipmentRequests).mockResolvedValue([decided(line(), 'Rejected'), decided(second, 'Rejected')])
  show()
  await showAll()
  await userEvent.click(await screen.findByRole('button', { name: 'Reject All' }))
  await waitFor(() => expect(document.querySelectorAll('.status-badge.rejected')).toHaveLength(2))
  expect(reviewAllEventEquipmentRequests).toHaveBeenCalledWith('ev1', 'Rejected', user)
  expect(screen.queryByRole('button', { name: 'Reject All' })).not.toBeInTheDocument()
})

test('shows the service error when a review fails and keeps the request', async () => {
  vi.mocked(reviewEquipmentRequest).mockRejectedValue(new Error('Cannot approve, insufficient stock: Wireless mic.'))
  show()
  await userEvent.click(await screen.findByRole('button', { name: 'Approve' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('insufficient stock')
  expect(screen.getByText('Wireless mic')).toBeInTheDocument()
})

test('shows the service error when a batch decision fails', async () => {
  vi.mocked(reviewAllEventEquipmentRequests).mockRejectedValue(new Error('Stock changed.'))
  show()
  await userEvent.click(await screen.findByRole('button', { name: 'Approve All' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Stock changed.')
  expect(screen.getByText('Wireless mic')).toBeInTheDocument()
})

test('shows a load error, and unknown equipment and empty requirements fall back', async () => {
  vi.mocked(fetchEventReservations).mockRejectedValueOnce(new Error('boom'))
  const { unmount } = show()
  expect(await screen.findByRole('alert')).toHaveTextContent('boom')
  unmount()
  vi.mocked(fetchEventReservations).mockResolvedValueOnce([event([line({ equipment: null, availability: null, technicalRequirements: '' })], { eventName: 'Unknown event' })])
  show()
  expect(await screen.findByText('Unknown equipment')).toBeInTheDocument()
  expect(screen.getByText('Unknown event')).toBeInTheDocument()
  expect(screen.getByText('None')).toBeInTheDocument()
  expect(screen.getByText('—', { selector: 'td' })).toBeInTheDocument()
})

test('refresh reloads the list', async () => {
  show()
  await screen.findByText('Wireless mic')
  await userEvent.click(screen.getByRole('button', { name: /Refresh requests/ }))
  await waitFor(() => expect(fetchEventReservations).toHaveBeenCalledTimes(2))
})
