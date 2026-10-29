/**
 * # SCRUM-48 — Equipment request notifications
 * AC1: A multi-item submission alerts Technical Support with the full item list.
 * AC2: Approval alerts the assigned Event Coordinator for the decided request.
 * AC3: Rejection alerts the assigned Event Coordinator without a reason in the alert.
 *
 * Public seam: real App / inbox / equipment page / HTTP adapters, mocked fetch.
 * Supporting navigation/access rules remain supporting rules, not additional ACs.
 * These are retrospective regression tests, not historical RED evidence. They
 * prove rendered navigation and caller-scoped HTTP intent, not recipient selection,
 * authorization enforcement, persistence, broker delivery, or a real-browser journey.
 */
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { fetchUsers } from './features/user/users'
import type { InboxItem } from './features/notifications/notifications'
import type { EquipmentRequest, EventReservation } from './features/equipment/requests'
import type { User } from './types'
import { signInAs, tokenOf } from './test/session'

vi.mock('./features/user/users', async (original) => ({ ...await original<typeof import('./features/user/users')>(), fetchUsers: vi.fn() }))
// Venue reminders are unrelated to the agreed equipment/inbox seam.
vi.mock('./features/venue/venueHolds', () => ({ fetchHoldReminders: vi.fn(async () => []) }))

const EVENT = '30000000-0000-0000-0000-000000000001'
const OTHER_EVENT = '30000000-0000-0000-0000-000000000002'
const MIC = '40000000-0000-0000-0000-000000000001'
const PROJECTOR = '40000000-0000-0000-0000-000000000002'
const UNLINKED = '40000000-0000-0000-0000-000000000003'
const MISSING = '40000000-0000-0000-0000-000000000004'
const staff: User = { id: '10000000-0000-0000-0000-000000000001', username: 'Tech', role: 'Technical Support', email: '', organization: '' }
const coordinator: User = { ...staff, id: '10000000-0000-0000-0000-000000000002', username: 'Assigned coordinator', role: 'Event Coordinator' }
const otherCoordinator: User = { ...coordinator, id: '10000000-0000-0000-0000-000000000003', username: 'Other coordinator' }
const attendee: User = { ...staff, id: '10000000-0000-0000-0000-000000000004', username: 'Attendee', role: 'Attendee' }
// EquipmentRequest/EventReservation match src/features/equipment/requests.ts.
// Wire list shape: equipment-reservation-service/app/routes.py reservations_list.
const line = (id: string, description: string, quantityRequested: number, status: EquipmentRequest['status'] = 'Pending'): EquipmentRequest => ({
  id, eventId: EVENT, equipmentId: id, quantityRequested, status, reviewedBy: status === 'Pending' ? null : staff.id,
  technicalRequirements: '', equipment: { description, type: 'AV', totalQuantity: 20, status: 'Available' },
  availability: { reservedQuantity: 0, availableStock: 20, isInsufficient: false },
})
const reservations = (): EventReservation[] => [{
  eventId: EVENT, eventName: 'SCRUM48 Symposium', eventStatus: 'Under Review', coordinatorId: coordinator.id,
  startTime: null, endTime: null,
  requests: [line(MIC, 'Wireless microphone', 5), line(PROJECTOR, 'HD projector', 2), line(UNLINKED, 'Unlinked speaker', 1)],
}, {
  eventId: OTHER_EVENT, eventName: 'Unrelated event', eventStatus: 'Under Review', coordinatorId: coordinator.id,
  startTime: null, endTime: null, requests: [{ ...line(MIC, 'Other event microphone', 7), eventId: OTHER_EVENT }],
}]
const alert = (id: string, requestIds: string[], type = 'equipment.request-submission', message = 'Equipment requested for SCRUM48 Symposium: Wireless microphone x5, HD projector x2.'): InboxItem => ({
  id, type, eventId: EVENT, createdAt: '2026-10-28T01:00:00Z', readAt: null,
  payload: { message, details: { eventName: 'SCRUM48 Symposium' }, destination: { kind: 'equipment-requests', eventId: EVENT, requestIds } },
})
const target = (ids: string[]) => `/equipment-requests?event=${EVENT}${ids.map(id => `&request=${id}`).join('')}`
const response = (body: unknown, ok = true) => ({ ok, json: async () => body }) as Response
let inbox: InboxItem[]
let rows: EventReservation[]
let equipmentRead: (init: RequestInit) => Promise<Response>
let unexpected: string[]
let http: ReturnType<typeof vi.fn>

beforeEach(() => {
  inbox = [alert('submission', [MIC, PROJECTOR])]
  rows = reservations()
  unexpected = []
  equipmentRead = async () => response({ events: rows })
  vi.mocked(fetchUsers).mockResolvedValue([staff, coordinator, otherCoordinator, attendee])
  signInAs(staff)
  window.history.replaceState({}, '', '/notifications')
  http = vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = new URL(input)
    if (url.pathname === '/notifications/unread-count') return response({ unreadCount: inbox.filter(item => !item.readAt).length })
    if (url.pathname === '/notifications') return response({ notifications: inbox, nextCursor: null })
    if (url.pathname.startsWith('/notifications/') && init.method === 'PATCH') {
      const item = inbox.find(item => item.id === decodeURIComponent(url.pathname.split('/').at(-1)!))!
      return response({ notification: { ...item, readAt: '2026-10-28T01:01:00Z' } })
    }
    if (url.pathname === '/auth/login') return response({ accessToken: 'unused', expiresAt: 4102444800, user: { user_id: attendee.id, username: attendee.username, email: '', role: attendee.role, organization: '', contact_details: '' } })
    if (url.pathname === '/equipment-reservations') return equipmentRead(init)
    // Ordinary navigation from a targeted coordinator view can visit and leave
    // the real new-request form; no creation writes are part of this test seam.
    if (url.pathname === '/events') return response({ events: [] })
    if (url.pathname === '/equipment') return response({ equipment: [] })
    unexpected.push(`${init.method ?? 'GET'} ${input}`)
    throw new Error(`Unmocked HTTP request: ${input}`)
  })
  vi.stubGlobal('fetch', http)
})
afterEach(() => {
  expect(unexpected, 'Every HTTP request at this seam must have an explicit mock').toEqual([])
  vi.unstubAllGlobals()
})

async function openAlert(index = 0) {
  const links = await screen.findAllByRole('link', { name: 'Open notification' })
  await userEvent.click(links[index])
}
async function expectRows(names: string[]) {
  await waitFor(() => expect(screen.getAllByRole('row').slice(1).map(row => within(row).getAllByRole('cell')[0].textContent)).toEqual(names))
  expect(screen.queryByRole('heading', { name: 'Unrelated event' })).not.toBeInTheDocument()
  expect(screen.queryByText('Unlinked speaker')).not.toBeInTheDocument()
}
async function travel(direction: 'back' | 'forward', path: string) {
  // Use the actual history traversal/popstate path, not a mocked navigate callback.
  await act(async () => {
    await new Promise<void>(resolve => {
      window.addEventListener('popstate', () => resolve(), { once: true })
      window.history[direction]()
    })
  })
  expect(window.location.pathname + window.location.search).toBe(path)
}

describe('SCRUM-48 original ACs — click an equipment alert through App', () => {
  it('AC1: opens every submitted request, not every event row or physical unit, and hides event-wide bulk actions', async () => {
    // Arrange: two submitted lines, another submission in the same event, and another event.
    render(<App />)
    expect(await screen.findByText('Equipment requested for SCRUM48 Symposium: Wireless microphone x5, HD projector x2.')).toBeInTheDocument()
    // Act: follow the real inbox link into the equipment page; fetch is mocked.
    // Why: the submission link must retain its exact records, not broaden to the event.
    await openAlert()
    // Assert: independent exact URL, rows, quantities, and safe action scope.
    expect(window.location.pathname + window.location.search).toBe(target([MIC, PROJECTOR]))
    await expectRows(['Wireless microphonePending', 'HD projectorPending'])
    expect(within(screen.getByText('Wireless microphone').closest('tr')!).getByText('5')).toBeInTheDocument()
    expect(within(screen.getByText('HD projector').closest('tr')!).getByText('2')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Approve' })).toHaveLength(2)
    expect(screen.queryByRole('button', { name: 'Approve All' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reject All' })).not.toBeInTheDocument()
    expect(http).toHaveBeenCalledWith('http://localhost:5010/equipment-reservations', { headers: { Authorization: `Bearer ${staff.id} ${staff.role}` } })
  })

  /** AC2=Approved; AC3=Rejected. A workflow reason may appear only after navigation. */
  it.each(['Approved', 'Rejected'] as const)('%s decision (AC2/AC3): opens only the decided row as the assigned coordinator', async status => {
    // Arrange: producer-like decision envelope; workflow reason is NOT in the alert.
    signInAs(coordinator)
    const message = `HD projector x2 for SCRUM48 Symposium was ${status.toLowerCase()}.`
    inbox = [alert('decision', [PROJECTOR], 'equipment.request-decision', message)]
    rows[0].requests[1] = { ...line(PROJECTOR, 'HD projector', 2, status), rejectionReason: status === 'Rejected' ? 'Workflow-only technician reason.' : null }
    render(<App />)
    expect(await screen.findByText(message)).toBeInTheDocument()
    expect(screen.queryByText('Workflow-only technician reason.')).not.toBeInTheDocument()
    // Act / Assert: current coordinator identity reaches the adapter; no staff actions.
    await openAlert()
    await expectRows([`HD projector${status}`])
    expect(window.location.pathname + window.location.search).toBe(target([PROJECTOR]))
    expect(screen.queryByText('Wireless microphone')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
    expect(http).toHaveBeenCalledWith('http://localhost:5010/equipment-reservations', { headers: { Authorization: `Bearer ${coordinator.id} ${coordinator.role}` } })
    // The workflow page may show its reason; AC3 forbids it in the notification, not here.
    if (status === 'Rejected') expect(screen.getByText('Workflow-only technician reason.')).toBeInTheDocument()
  })
})

describe('SCRUM-48 supporting navigation and access rules (not extra ACs)', () => {
  it('successive alerts, browser back/forward, and ordinary sidebar navigation replace or clear the target', async () => {
    // Arrange: two alerts with different request sets under the same route/event.
    inbox = [alert('first', [MIC]), alert('second', [PROJECTOR])]
    render(<App />)
    await openAlert(0)
    await expectRows(['Wireless microphonePending'])
    // Act: open the second alert from the bell without leaving the equipment route.
    await userEvent.click(screen.getByRole('button', { name: /Notifications, / }))
    await openAlert(1)
    await expectRows(['HD projectorPending'])
    await travel('back', target([MIC]))
    await expectRows(['Wireless microphonePending'])
    await travel('back', '/notifications')
    await travel('forward', target([MIC]))
    await expectRows(['Wireless microphonePending'])
    await travel('forward', target([PROJECTOR]))
    await expectRows(['HD projectorPending'])
    // Assert: ordinary navigation has no stale query and restores event-wide view/actions.
    await userEvent.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Equipment requests' }))
    expect(window.location.pathname + window.location.search).toBe('/equipment-requests')
    expect(await screen.findByText('Unlinked speaker')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Unrelated event' })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Approve All' })).toHaveLength(2)
  })

  it('signing out removes previous rows immediately, ignores their late HTTP response and the next user starts clean', async () => {
    // Arrange: start with staff data, then leave a refresh unresolved.
    render(<App />)
    await openAlert()
    await expectRows(['Wireless microphonePending', 'HD projectorPending'])
    let finish!: (value: Response) => void
    equipmentRead = () => new Promise(resolve => { finish = resolve })
    await userEvent.click(screen.getByRole('button', { name: /Refresh requests/ }))
    await waitFor(() => expect(finish).toBeTypeOf('function'))
    // Act: sign out, then sign in as an attendee while staying on the deep link.
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(screen.queryByText('Wireless microphone')).not.toBeInTheDocument()
    signInAs(attendee)
    await userEvent.type(screen.getByLabelText(/Email/), 'attendee@example.com')
    await userEvent.type(screen.getByLabelText(/Password/), 'secret')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await act(async () => { finish(response({ events: reservations() })) })
    // Assert: unauthorized role sees no stale/late event data or equipment actions.
    expect(await screen.findByText('Equipment requests are visible to Technical Support and assigned Event Coordinators.')).toBeInTheDocument()
    expect(screen.queryByText('Wireless microphone')).not.toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    const equipmentCalls = http.mock.calls.filter(([url]) => new URL(url).pathname === '/equipment-reservations')
    expect(equipmentCalls.map(([, init]) => tokenOf(init))).toEqual([`Bearer ${staff.id} ${staff.role}`, `Bearer ${staff.id} ${staff.role}`])
  })

  it('partial missing/deleted targets show available target rows and an access-safe warning only', async () => {
    // Arrange / Act: one target is no longer returned by the scoped API.
    inbox = [alert('partial', [MIC, MISSING])]
    render(<App />)
    await openAlert()
    // Assert: never substitute another request for the missing target.
    await expectRows(['Wireless microphonePending'])
    expect(screen.getByRole('status')).toHaveTextContent('Some requested equipment is unavailable or you no longer have access.')
    expect(screen.queryByText('HD projector')).not.toBeInTheDocument()
  })

  /** Supporting privacy rule: distinct missing/access causes intentionally share safe copy. */
  it.each(['deleted event', 'reassigned coordinator', 'missing request'] as const)('%s: all unavailable targets never fall back to unrelated data', async situation => {
    // Arrange: API no longer exposes the event, or exposes it without this request.
    if (situation === 'deleted event') rows = []
    if (situation === 'reassigned coordinator') {
      rows = [rows[1]]
      signInAs(otherCoordinator)
    }
    if (situation === 'missing request') inbox = [alert('missing', [MISSING])]
    render(<App />)
    await openAlert()
    // Assert: deliberately indistinguishable missing/access-denied copy, no identifiers/data.
    expect(await screen.findByText('This equipment request is unavailable or you no longer have access.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Unrelated event' })).not.toBeInTheDocument()
    expect(screen.queryByText('Unlinked speaker')).not.toBeInTheDocument()
  })

  it('an in-flight targeted read shows no data; denied access then refresh recovers without broadening the target', async () => {
    // Arrange: controlled transport, then a safe authorization error from the API.
    let finish!: (value: Response) => void
    equipmentRead = () => new Promise(resolve => { finish = resolve })
    render(<App />)
    await openAlert()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByText('This equipment request is unavailable or you no longer have access.')).not.toBeInTheDocument()
    // Act: complete the denied read and retry with newly accessible data.
    await act(async () => { finish(response({ message: 'Permission denied.' }, false)) })
    expect(await screen.findByRole('alert')).toHaveTextContent('Permission denied.')
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    equipmentRead = async () => response({ events: rows })
    await userEvent.click(screen.getByRole('button', { name: /Refresh requests/ }))
    // Assert: recovery retains the two-row target rather than exposing other submissions.
    await expectRows(['Wireless microphonePending', 'HD projectorPending'])
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  /** Supporting URL safety: malformed request UUID, hostile event ID, then arbitrary URL kind. */
  it.each([
    { kind: 'equipment-requests', eventId: EVENT, requestIds: ['javascript:alert(1)'] },
    { kind: 'equipment-requests', eventId: '//evil.example', requestIds: [MIC] },
    { kind: 'url', url: 'https://evil.example/equipment-requests' },
  ])('hostile destination is displayed as unavailable and cannot initiate navigation: %j', async destination => {
    // Arrange / Act: producer-controlled input reaches the real inbox renderer.
    inbox = [{ ...alert('invalid', [MIC]), payload: { message: 'Invalid equipment destination', destination } }]
    render(<App />)
    // Assert: no unsafe href, no click path, no equipment fetch, route unchanged.
    expect(await screen.findByText('Destination unavailable.')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Open notification' })).not.toBeInTheDocument()
    expect(window.location.pathname).toBe('/notifications')
    expect(http.mock.calls.filter(([url]) => new URL(url).pathname === '/equipment-reservations')).toHaveLength(0)
  })

  it('leaving a targeted view for the new-request form and returning clears the old target', async () => {
    // Arrange: a coordinator opens one request through the inbox.
    signInAs(coordinator)
    inbox = [alert('single', [PROJECTOR])]
    render(<App />)
    await openAlert()
    await expectRows(['HD projectorPending'])
    // Act: ordinary navigation uses the real form entry and Back control.
    await userEvent.click(screen.getByRole('button', { name: /New request/ }))
    expect(window.location.pathname + window.location.search).toBe('/equipment-requests/new')
    await userEvent.click(await screen.findByRole('button', { name: /Back to equipment requests/ }))
    // Assert: this is a fresh ordinary list, not the prior one-request notification view.
    expect(window.location.pathname + window.location.search).toBe('/equipment-requests')
    expect(await screen.findByText('Unlinked speaker')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Unrelated event' })).toBeInTheDocument()
  })

  it('a direct deep link survives initial App routing without requiring an inbox click', async () => {
    // Arrange / Act: simulate a saved same-origin URL.
    window.history.replaceState({}, '', target([PROJECTOR]))
    render(<App />)
    // Assert: the initial query is honored by the real equipment page.
    await expectRows(['HD projectorPending'])
  })
})
