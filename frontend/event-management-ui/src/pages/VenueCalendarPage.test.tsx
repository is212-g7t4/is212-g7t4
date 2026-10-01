import { act, fireEvent, render as renderPage, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { VenueCalendarPage } from './VenueCalendarPage'
import { fetchVenues } from '../features/venue/venues'
import { fetchCalendar } from '../features/calendar/api'
import type { Role } from '../types'
vi.mock('../features/venue/venues', () => ({ fetchVenues: vi.fn() }))
vi.mock('../features/calendar/api', () => ({ fetchCalendar: vi.fn() }))
function render(ui: Parameters<typeof renderPage>[0]) {
  const page = renderPage(ui)
  page.container.querySelector('details.calendar-venue-picker')?.setAttribute('open', '')
  return page
}
const user = {
  id: '00000000-0000-0000-0000-000000000001',
  role: 'Event Coordinator' as Role,
}
const venues = [
  {
    id: user.id,
    name: 'Hall',
    location: 'SG',
    capacity: 20,
    facilities: [],
    accessibility: '',
    supportedLayouts: [],
    status: 'Unavailable',
  },
  {
    id: '00000000-0000-0000-0000-000000000002',
    name: 'Room',
    location: 'SG',
    capacity: 10,
    facilities: [],
    accessibility: '',
    supportedLayouts: [],
    status: 'Available',
  },
]
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(fetchVenues).mockResolvedValue(venues)
  vi.mocked(fetchCalendar).mockResolvedValue([])
})
test('bulk venue buttons select all from single or partial, deselect all and avoid no-op requests', async () => {
  vi.mocked(fetchVenues).mockResolvedValue([...venues, {...venues[1], id: '00000000-0000-0000-0000-000000000003', name: 'Studio'}])
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  const all = screen.getByRole('button', {name: 'Select all'})
  const none = screen.getByRole('button', {name: 'Deselect all'})
  expect(all).toHaveAttribute('type', 'button')
  expect(none).toHaveAttribute('type', 'button')
  fireEvent.click(all)
  await waitFor(() => expect(fetchCalendar).toHaveBeenCalledTimes(4))
  expect(screen.getAllByRole('checkbox').every(box => (box as HTMLInputElement).checked)).toBe(true)
  expect(all).toBeDisabled()
  fireEvent.click(all)
  expect(fetchCalendar).toHaveBeenCalledTimes(4)
  fireEvent.click(screen.getByRole('checkbox', {name: 'Room'}))
  await waitFor(() => expect(fetchCalendar).toHaveBeenCalledTimes(6))
  fireEvent.click(all)
  await waitFor(() => expect(fetchCalendar).toHaveBeenCalledTimes(9))
  fireEvent.click(none)
  expect(screen.getByText('Choose at least one venue.')).toBeInTheDocument()
  expect(screen.getByRole('button', {name: 'Inspect time range'})).toBeDisabled()
  expect(none).toBeDisabled()
  fireEvent.click(none)
  expect(fetchCalendar).toHaveBeenCalledTimes(9)
  expect(document.querySelector('.calendar-venue-picker')).toHaveAttribute('open')
  fireEvent.click(all)
  await waitFor(() => expect(fetchCalendar).toHaveBeenCalledTimes(12))
})

test.each(['Select all', 'Deselect all'])('bulk %s aborts stale grid and inspection chains and resets inputs', async action => {
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  let finishGrid!: (rows: typeof approved[]) => void
  let finishInspection!: (rows: typeof approved[]) => void
  vi.mocked(fetchCalendar).mockClear()
    .mockImplementationOnce(() => new Promise(r => {finishGrid = r}))
    .mockImplementationOnce(() => new Promise(r => {finishInspection = r}))
  fireEvent.click(screen.getByRole('button', {name: 'Refresh'}))
  const gridSignal = vi.mocked(fetchCalendar).mock.calls[0][3]!
  range('2027-01-01T09:00', '2027-04-01T10:00')
  fireEvent.click(screen.getByRole('button', {name: 'Inspect range'}))
  const inspectionSignal = vi.mocked(fetchCalendar).mock.calls[1][3]!
  fireEvent.click(screen.getByRole('button', {name: action}))
  expect(gridSignal.aborted).toBe(true)
  expect(inspectionSignal.aborted).toBe(true)
  expect(screen.getByLabelText('Start (SGT)')).toHaveValue('')
  expect(screen.getByLabelText('End (SGT)')).toHaveValue('')
  expect(screen.queryByText('Loading inspection…')).not.toBeInTheDocument()
  await act(async () => { finishGrid([approved]); finishInspection([approved]) })
  expect(fetchCalendar).toHaveBeenCalledTimes(action === 'Select all' ? 4 : 2)
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  expect(document.querySelector('.calendar-approved')).toBeNull()
})

test.each(['Select all', 'Deselect all'])('bulk %s clears a completed inspected result', async action => {
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  range('2027-02-10T09:00', '2027-02-11T00:00')
  fireEvent.click(screen.getByRole('button', {name: 'Inspect range'}))
  await screen.findByRole('region', {name: 'Inspected range · Week'})
  fireEvent.click(screen.getByRole('button', {name: action}))
  expect(screen.queryByRole('region', {name: 'Inspected range · Week'})).not.toBeInTheDocument()
  expect(screen.getAllByRole('button', {name: /^Open /})).toHaveLength(42)
})

test('bulk buttons stay disabled with an empty catalogue', async () => {
  vi.mocked(fetchVenues).mockResolvedValue([])
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No venues available in the catalogue.')
  expect(screen.getByRole('button', {name: 'Select all'})).toBeDisabled()
  expect(screen.getByRole('button', {name: 'Deselect all'})).toBeDisabled()
  expect(fetchCalendar).not.toHaveBeenCalled()
})

test('checkbox selection adds venues, preserves same-ID entries with names and permits zero selection', async () => {
  vi.mocked(fetchCalendar).mockImplementation(async venueId => [{...approved, venueId}])
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByRole('checkbox', {name: 'Hall'})
  expect(screen.getByRole('checkbox', {name: 'Hall'})).toBeChecked()
  fireEvent.click(screen.getByRole('checkbox', {name: 'Room'}))
  await waitFor(() => expect(screen.getByRole('button', {name:'Open 2026-10-01'})).toHaveTextContent('+1 more'))
  expect(document.querySelectorAll('.calendar-month .calendar-approved')).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', {name: 'Open 2026-10-01'}))
  await waitFor(() => expect(document.querySelectorAll('.calendar-day .calendar-approved')).toHaveLength(2))
  expect(document.querySelector('.calendar-days')).toHaveTextContent('Hall')
  expect(document.querySelector('.calendar-days')).toHaveTextContent('Room')
  fireEvent.click(screen.getByRole('checkbox', {name: 'Hall'}))
  await waitFor(() => expect(document.querySelectorAll('.calendar-day .calendar-approved')).toHaveLength(1))
  expect(document.querySelector('.calendar-days')).not.toHaveTextContent('Hall')
  fireEvent.click(screen.getByRole('checkbox', {name: 'Room'}))
  expect(screen.getByText('Choose at least one venue.')).toBeInTheDocument()
  expect(screen.getByRole('button', {name: 'Inspect time range'})).toBeDisabled()
  expect(document.querySelector('.calendar-days')).toBeNull()
})

test('multi-venue inspection independently queries selected venues outside view, retaining same IDs and names', async () => {
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  fireEvent.click(screen.getByRole('checkbox', {name: 'Room'}))
  await waitFor(() => expect(fetchCalendar).toHaveBeenCalledTimes(3))
  vi.mocked(fetchCalendar).mockClear().mockImplementation(async venueId => [{...approved, venueId, requestedStartTime: '2027-02-10T09:00:00+08:00', requestedEndTime: '2027-02-10T10:00:00+08:00'}])
  range('2027-02-10T09:00', '2027-02-12T00:00')
  fireEvent.click(screen.getByRole('button', {name: 'Inspect range'}))
  const result = await screen.findByRole('region', {name: 'Inspected range · Week'})
  expect(result).toHaveTextContent('2 unavailable')
  expect(result.querySelectorAll('.calendar-approved')).toHaveLength(2)
  expect(result.querySelectorAll('.calendar-approved')[0]).toHaveTextContent('Hall')
  expect(result.querySelectorAll('.calendar-approved')[1]).toHaveTextContent('Room')
  expect(screen.getByRole('status')).toHaveTextContent('Hall, Room')
  expect(vi.mocked(fetchCalendar).mock.calls.map(c => [c[0], c[1]])).toEqual(venues.map(v => [v.id, {start: '2027-02-10', end: '2027-02-12'}]))
  fireEvent.click(screen.getByRole('button', {name: 'Back to calendar'}))
  expect(screen.getByRole('checkbox', {name: 'Hall'})).toBeChecked()
  expect(screen.getByRole('checkbox', {name: 'Room'})).toBeChecked()
})

test('obsolete multi-venue chains abort transport and never start later venues or chunks', async () => {
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  fireEvent.click(screen.getByRole('checkbox', {name: 'Room'}))
  await waitFor(() => expect(fetchCalendar).toHaveBeenCalledTimes(3))
  let finish!: (rows: typeof approved[]) => void
  vi.mocked(fetchCalendar).mockClear().mockImplementationOnce(() => new Promise(r => {finish = r}))
  range('2027-01-01T09:00', '2027-04-01T10:00')
  fireEvent.click(screen.getByRole('button', {name: 'Inspect range'}))
  const signal = vi.mocked(fetchCalendar).mock.calls[0][3]
  expect(signal).toBeInstanceOf(AbortSignal)
  range('2027-01-02T09:00', '2027-01-02T10:00')
  expect(signal!.aborted).toBe(true)
  await act(async () => finish([]))
  expect(fetchCalendar).toHaveBeenCalledTimes(1)
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

test('normal Week and Day separate centered weekday strips from date headings', async () => {
  const {container} = render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  fireEvent.click(screen.getByRole('button', {name: 'Week'}))
  await waitFor(() => expect(container.querySelectorAll('.calendar-days .calendar-weekdays')).toHaveLength(7))
  expect([...container.querySelectorAll('.calendar-day h3')].map(e => e.textContent)).toEqual(['2026-09-28','2026-09-29','2026-09-30','2026-10-01','2026-10-02','2026-10-03','2026-10-04'])
  fireEvent.click(screen.getByRole('button', {name: 'Day'}))
  await waitFor(() => expect(container.querySelectorAll('.calendar-days .calendar-weekdays')).toHaveLength(1))
  expect(container.querySelector('.calendar-days .calendar-weekdays')).toHaveTextContent('Thu')
})

test.each(['grid', 'inspection'])('one selected venue failure rejects complete %s result', async mode => {
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  if (mode === 'grid') vi.mocked(fetchCalendar).mockImplementation(async id => {
    if (id === venues[1].id) throw new Error('Room offline')
    return [approved]
  })
  fireEvent.click(screen.getByRole('checkbox', {name: 'Room'}))
  await waitFor(() => expect(fetchCalendar).toHaveBeenCalledTimes(3))
  if (mode === 'inspection') {
    vi.mocked(fetchCalendar).mockImplementation(async id => {
      if (id === venues[1].id) throw new Error('Room offline')
      return [approved]
    })
    range('2026-10-01T09:00', '2026-10-01T10:00')
    fireEvent.click(screen.getByRole('button', {name: 'Inspect range'}))
  }
  expect(await screen.findByRole('alert')).toHaveTextContent('no availability can be inferred')
  expect(document.querySelectorAll('.calendar-approved')).toHaveLength(0)
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

test('keyboard changes native multi-select; zero selection issues no requests and resets errors', async () => {
  const keyboard = userEvent.setup()
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  vi.mocked(fetchCalendar).mockClear()
  screen.getByRole('checkbox', {name: 'Hall'}).focus()
  await keyboard.keyboard(' ')
  expect(screen.getByText('Choose at least one venue.')).toBeInTheDocument()
  expect(fetchCalendar).not.toHaveBeenCalled()
  screen.getByRole('checkbox', {name: 'Room'}).focus()
  await keyboard.keyboard(' ')
  await screen.findByText('No bookings in this window.')
  expect(fetchCalendar).toHaveBeenCalledTimes(1)
  expect(vi.mocked(fetchCalendar).mock.calls[0][0]).toBe(venues[1].id)
})

test('clearing selected set clears obsolete grid failure without falling back to all venues', async () => {
  vi.mocked(fetchCalendar).mockRejectedValue(new Error('offline'))
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByRole('alert')
  fireEvent.click(screen.getByRole('checkbox', {name: 'Hall'}))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.getByText('Choose at least one venue.')).toBeInTheDocument()
  expect(fetchCalendar).toHaveBeenCalledTimes(1)
})

test('multi-venue long inspection deduplicates within each venue only and caps every chunk', async () => {
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  fireEvent.click(screen.getByRole('checkbox', {name: 'Room'}))
  await waitFor(() => expect(fetchCalendar).toHaveBeenCalledTimes(3))
  vi.mocked(fetchCalendar).mockClear().mockImplementation(async venueId => [{...approved, venueId, requestedStartTime: '2027-01-01T09:00:00+08:00', requestedEndTime: '2027-03-01T10:00:00+08:00'}])
  range('2027-01-01T09:00', '2027-03-01T00:00')
  fireEvent.click(screen.getByRole('button', {name: 'Inspect range'}))
  expect(await screen.findByRole('status')).toHaveTextContent('2 unavailable')
  expect(vi.mocked(fetchCalendar).mock.calls.map(c => [c[0], c[1]])).toEqual(venues.flatMap(v => [[v.id,{start:'2027-01-01',end:'2027-02-12'}],[v.id,{start:'2027-02-12',end:'2027-03-01'}]]))
})

test.each(['success', 'failure'])('combined snapshot ignores stale %s after selected-set A+B to A to A+B', async outcome => {
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  let resolve!: (rows: typeof approved[]) => void
  let reject!: (error: Error) => void
  vi.mocked(fetchCalendar).mockImplementationOnce(() => new Promise((r,j) => {resolve=r;reject=j}))
  fireEvent.click(screen.getByRole('checkbox', {name:'Room'}))
  const signal=vi.mocked(fetchCalendar).mock.calls[1][3]!
  fireEvent.click(screen.getByRole('checkbox', {name:'Room'}))
  fireEvent.click(screen.getByRole('checkbox', {name:'Room'}))
  await screen.findByText('No bookings in this window.')
  expect(signal.aborted).toBe(true)
  await act(async () => {if(outcome==='success') resolve([approved]); else reject(new Error('old failure'))})
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(document.querySelectorAll('.calendar-approved')).toHaveLength(0)
})

test.each(['success', 'failure'])('selected-set edit aborts multi-venue inspection and ignores late %s', async outcome => {
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  fireEvent.click(screen.getByRole('checkbox', {name:'Room'}))
  await waitFor(() => expect(fetchCalendar).toHaveBeenCalledTimes(3))
  let resolve!: (rows: typeof approved[]) => void
  let reject!: (error: Error) => void
  vi.mocked(fetchCalendar).mockClear().mockImplementationOnce(() => new Promise((r,j) => {resolve=r;reject=j}))
  range('2027-01-01T09:00','2027-03-01T00:00')
  fireEvent.click(screen.getByRole('button', {name:'Inspect range'}))
  const signal=vi.mocked(fetchCalendar).mock.calls[0][3]!
  fireEvent.click(screen.getByRole('checkbox', {name:'Room'}))
  await screen.findByText('No bookings in this window.')
  expect(signal.aborted).toBe(true)
  await act(async () => {if(outcome==='success') resolve([approved]); else reject(new Error('old failure'))})
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(fetchCalendar).toHaveBeenCalledTimes(2)
})

test('unsupported anchor is rejected without replacing the safe window', async () => {
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  fireEvent.change(screen.getByLabelText('Anchor date'), { target: { value: '10000-01-01' } })
  expect(screen.getByRole('alert')).toHaveTextContent('Supported anchor dates')
  expect(screen.getByLabelText('Anchor date')).toHaveValue('2026-10-01')
  expect(fetchCalendar).toHaveBeenCalledTimes(1)
})
test.each([['0002-01-01', 'Previous'], ['9998-12-31', 'Next']])('anchor boundary %s disables crossing in all views', async (anchor, direction) => {
  render(<VenueCalendarPage user={user} initialDate={anchor} />)
  await screen.findByText('No bookings in this window.')
  expect(screen.getByLabelText('Anchor date')).toHaveAttribute('min', '0002-01-01')
  expect(screen.getByLabelText('Anchor date')).toHaveAttribute('max', '9998-12-31')
  for (const view of ['Day', 'Week', 'Month']) {
    fireEvent.click(screen.getByRole('button', { name: view }))
    expect(screen.getByRole('button', { name: direction })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: direction }))
    expect(screen.getByLabelText('Anchor date')).toHaveValue(anchor)
  }
  for (const cell of screen.getAllByRole('button', { name: /^Open / })) {
    const date = cell.getAttribute('aria-label')!.slice(5)
    if (date < '0002-01-01' || date > '9998-12-31') expect(cell).toBeDisabled()
  }
  await waitFor(() => expect(fetchCalendar).toHaveBeenCalled())
})
test('unsupported initial anchor renders controlled feedback and a safe fallback', async () => {
  render(<VenueCalendarPage user={user} initialDate="10000-01-01" />)
  expect(screen.getByRole('alert')).toHaveTextContent('Supported anchor dates')
  await screen.findByText('No bookings in this window.')
  fireEvent.click(screen.getByRole('button', { name: 'Today' }))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})
test.each(['success', 'failure'])('identity switch ignores old identity late %s', async (outcome) => {
  let resolveOld!: (rows: (typeof approved)[]) => void
  let rejectOld!: (error: Error) => void
  let resolveNew!: (rows: (typeof approved)[]) => void
  vi.mocked(fetchCalendar)
    .mockImplementationOnce(() => new Promise((resolve, reject) => { resolveOld = resolve; rejectOld = reject }))
    .mockImplementationOnce(() => new Promise((resolve) => { resolveNew = resolve }))
  const page = render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await waitFor(() => expect(fetchCalendar).toHaveBeenCalledTimes(1))
  const nextUser = { ...user, id: venues[1].id }
  page.rerender(<VenueCalendarPage user={nextUser} initialDate="2026-10-01" />)
  await waitFor(() => expect(fetchCalendar).toHaveBeenCalledTimes(2))
  expect(fetchCalendar).toHaveBeenLastCalledWith(user.id, { start: '2026-09-28', end: '2026-11-09' }, nextUser, expect.any(AbortSignal))
  await act(async () => { if (outcome === 'success') resolveOld([approved]); else rejectOld(new Error('old identity')) })
  openInspector()
  expect(screen.getByLabelText('Start (SGT)')).toBeEnabled()
  expect(screen.queryByText('Unavailable · 09:00–10:00 SGT')).not.toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  await act(async () => resolveNew([]))
  expect(screen.getByLabelText('Start (SGT)')).toBeEnabled()
})
test.each(['success', 'failure'])('A to B to A ignores first A late %s despite matching key', async (outcome) => {
  let resolveOld!: (rows: (typeof approved)[]) => void
  let rejectOld!: (error: Error) => void
  let resolveCurrent!: (rows: (typeof approved)[]) => void
  vi.mocked(fetchCalendar)
    .mockImplementationOnce(() => new Promise((resolve, reject) => { resolveOld = resolve; rejectOld = reject }))
    .mockResolvedValueOnce([])
    .mockImplementationOnce(() => new Promise((resolve) => { resolveCurrent = resolve }))
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await waitFor(() => expect(fetchCalendar).toHaveBeenCalledTimes(1))
  selectOnly(1)
  await screen.findByText('No bookings in this window.')
  selectOnly(0)
  await waitFor(() => expect(fetchCalendar).toHaveBeenCalledTimes(3))
  await act(async () => { if (outcome === 'success') resolveOld([approved]); else rejectOld(new Error('old A')) })
  openInspector()
  expect(screen.getByLabelText('Start (SGT)')).toBeEnabled()
  expect(screen.queryByText('Unavailable · 09:00–10:00 SGT')).not.toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  await act(async () => resolveCurrent([]))
  expect(screen.getByLabelText('Start (SGT)')).toBeEnabled()
})
test('default month loads real catalogue choices including non-requestable venues and empty snapshot', async () => {
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  expect(
    await screen.findByText('No bookings in this window.'),
  ).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Month' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  expect(screen.getByRole('checkbox', { name: 'Hall' })).toBeEnabled()
  expect(fetchCalendar).toHaveBeenCalledWith(
    user.id,
    { start: '2026-09-28', end: '2026-11-09' },
    user, expect.any(AbortSignal),
  )
})
test.each(['Event Organiser', 'Attendee'] as Role[])(
  'direct page denies %s without requests',
  (role) => {
    render(<VenueCalendarPage user={{ ...user, role }} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Permission denied')
    expect(fetchVenues).not.toHaveBeenCalled()
  },
)

test('view/navigation preserve anchor, month dates open day, venue and refresh refetch', async () => {
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  fireEvent.click(screen.getByRole('button', { name: 'Month' }))
  await waitFor(() =>
    expect(fetchCalendar).toHaveBeenLastCalledWith(
      user.id,
      { start: '2026-09-28', end: '2026-11-09' },
      user, expect.any(AbortSignal),
    ),
  )
  fireEvent.click(screen.getByRole('button', { name: 'Day' }))
  await waitFor(() =>
    expect(fetchCalendar).toHaveBeenLastCalledWith(
      user.id,
      { start: '2026-10-01', end: '2026-10-02' },
      user, expect.any(AbortSignal),
    ),
  )
  fireEvent.click(screen.getByRole('button', { name: 'Next' }))
  await waitFor(() =>
    expect(fetchCalendar).toHaveBeenLastCalledWith(
      user.id,
      { start: '2026-10-02', end: '2026-10-03' },
      user, expect.any(AbortSignal),
    ),
  )
  fireEvent.click(screen.getByRole('button', { name: 'Previous' }))
  fireEvent.click(screen.getByRole('button', { name: 'Month' }))
  fireEvent.click(
    await screen.findByRole('button', { name: 'Open 2026-10-15' }),
  )
  await waitFor(() =>
    expect(fetchCalendar).toHaveBeenLastCalledWith(
      user.id,
      { start: '2026-10-15', end: '2026-10-16' },
      user, expect.any(AbortSignal),
    ),
  )
  selectOnly(1)
  await waitFor(() =>
    expect(fetchCalendar).toHaveBeenLastCalledWith(
      venues[1].id,
      { start: '2026-10-15', end: '2026-10-16' },
      user, expect.any(AbortSignal),
    ),
  )
  const calls = vi.mocked(fetchCalendar).mock.calls.length
  fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
  await waitFor(() => expect(fetchCalendar).toHaveBeenCalledTimes(calls + 1))
  fireEvent.click(screen.getByRole('button', { name: 'Today' }))
  await waitFor(() =>
    expect(screen.getByLabelText('Anchor date')).not.toHaveValue('2026-10-15'),
  )
})

const approved = {
  id: 'booking',
  eventId: 'event',
  venueId: user.id,
  requestedBy: null,
  reviewedBy: null,
  status: 'Approved' as const,
  blocksSelection: true,
  requestedStartTime: '2026-10-01T09:00:00+08:00',
  requestedEndTime: '2026-10-01T10:00:00+08:00',
}
test('microsecond approved tail is inspectable and counted', async () => {
  vi.mocked(fetchCalendar).mockResolvedValue([{ ...approved,
    requestedEndTime: '2026-10-01T10:00:00.000001+08:00' }])
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('Unavailable · 09:00–10:00 SGT')
  range('2026-10-01T10:00:00', '2026-10-01T10:01:00')
  fireEvent.click(screen.getByRole('button', { name: 'Inspect range' }))
  expect(await screen.findByRole('status')).toHaveTextContent('1 unavailable')
})
function selectOnly(index: number) {
  for (const [i, venue] of venues.entries()) {
    const checkbox = screen.getByRole('checkbox', {name: venue.name}) as HTMLInputElement
    if (checkbox.checked && i !== index) fireEvent.click(checkbox)
  }
  const target = screen.getByRole('checkbox', {name: venues[index].name}) as HTMLInputElement
  if (!target.checked) fireEvent.click(target)
}
function openInspector() {
  const toggle = screen.getByRole('button', { name: 'Inspect time range' })
  if (toggle.getAttribute('aria-expanded') === 'false') fireEvent.click(toggle)
}
function range(start: string, end: string) {
  openInspector()
  fireEvent.change(screen.getByLabelText('Start (SGT)'), {
    target: { value: start },
  })
  fireEvent.change(screen.getByLabelText('End (SGT)'), {
    target: { value: end },
  })
}
test.each(['Event Coordinator', 'Venue Staff', 'Technical Support'] as Role[])(
  '%s inspects approved, pending and free ranges',
  async (role) => {
    vi.mocked(fetchCalendar).mockResolvedValue([
      approved,
      {
        ...approved,
        id: 'pending',
        status: 'Pending',
        blocksSelection: false,
        requestedStartTime: '2026-10-01T11:00:00+08:00',
        requestedEndTime: '2026-10-01T12:00:00+08:00',
      },
    ])
    render(
      <VenueCalendarPage user={{ ...user, role }} initialDate="2026-10-01" />,
    )
    await screen.findByText(/Unavailable · 09:00–10:00 SGT/)
    range('2026-10-01T09:30', '2026-10-01T10:30')
    fireEvent.click(screen.getByRole('button', {name: 'Inspect range'}))
    expect(await screen.findByRole('status')).toHaveTextContent('1 unavailable')
    range('2026-10-01T10:00', '2026-10-01T10:01')
    fireEvent.click(screen.getByRole('button', { name: 'Inspect range' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Selected range')
    range('2026-10-01T11:00', '2026-10-01T12:00')
    fireEvent.click(screen.getByRole('button', { name: 'Inspect range' }))
    expect(await screen.findByRole('status')).toHaveTextContent(
      '1 pending confirmation',
    )
    expect(await screen.findByRole('status')).toHaveTextContent('not a reservation')
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.queryByText(/Selected range/)).not.toBeInTheDocument()
  },
)
test('grid loading/failure ignores stale rows while independent inspection stays enabled', async () => {
  let resolveOld!: (rows: (typeof approved)[]) => void
  vi.mocked(fetchCalendar)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOld = resolve
        }),
    )
    .mockRejectedValueOnce(new Error('offline'))
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await waitFor(() => expect(fetchCalendar).toHaveBeenCalledTimes(1))
  openInspector()
  expect(screen.getByLabelText('Start (SGT)')).toBeEnabled()
  selectOnly(1)
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Availability unavailable',
  )
  await act(async () => resolveOld([approved]))
  expect(screen.queryByText(/Unavailable · 09:00–10:00 SGT/)).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Inspect range' })).toBeEnabled()
})

test('empty catalogue and catalogue outage are explicit and retryable', async () => {
  vi.mocked(fetchVenues)
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValueOnce([])
  render(<VenueCalendarPage user={user} />)
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Unable to load venues',
  )
  fireEvent.click(screen.getByRole('button', { name: 'Retry venues' }))
  expect(
    await screen.findByText('No venues available in the catalogue.'),
  ).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Inspect time range' })).toBeDisabled()
})
test('month booking appears inside clickable date cell; Pending Review remains nonblocking', async () => {
  vi.mocked(fetchCalendar).mockResolvedValue([
    { ...approved, status: 'Pending Review', blocksSelection: false },
  ])
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('Pending confirmation · 09:00–10:00 SGT')
  fireEvent.click(screen.getByRole('button', { name: 'Month' }))
  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: 'Open 2026-10-01' }),
    ).toHaveTextContent('Pending confirmation'),
  )
  expect(screen.queryByLabelText('Start (SGT)')).not.toBeInTheDocument()
})

test('inspection fetches outside the grid independently without navigating or using cached bookings', async () => {
  vi.mocked(fetchCalendar).mockResolvedValueOnce([approved]).mockResolvedValueOnce([
    {...approved, requestedStartTime: '2027-01-01T09:00:00+08:00', requestedEndTime: '2027-01-01T10:00:00+08:00'},
  ])
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('Unavailable · 09:00–10:00 SGT')
  range('2027-01-01T09:30', '2027-01-01T10:30')
  fireEvent.click(screen.getByRole('button', {name: 'Inspect range'}))
  expect(await screen.findByRole('status')).toHaveTextContent('1 unavailable')
  expect(fetchCalendar).toHaveBeenLastCalledWith(user.id, {start: '2027-01-01', end: '2027-01-02'}, user, expect.any(AbortSignal))
  expect(screen.getByLabelText('Anchor date')).toHaveValue('2026-10-01')
  expect(screen.queryByRole('button', {name: /^Open /})).not.toBeInTheDocument()
})

test.each([
  ['', '', 'Start date/time is required'],
  ['2026-10-01T09:00', '', 'End date/time is required'],
  ['2026-10-01T10:00', '2026-10-01T09:00', 'End date/time must be after start date/time'],
  ['2026-10-01T10:00', '2026-10-01T10:00', 'End date/time must be after start date/time'],
])('range validation %s %s is explicit on submit', async (start, end, message) => {
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  range(start, end)
  expect(screen.getByRole('button', {name: 'Inspect range'})).toBeEnabled()
  fireEvent.click(screen.getByRole('button', {name: 'Inspect range'}))
  expect(screen.getByRole('alert')).toHaveTextContent(message)
  expect(fetchCalendar).toHaveBeenCalledTimes(1)
})


test('long inspection uses sequential 42-day chunks and deduplicates spanning records', async () => {
  let finish!: (rows: typeof approved[]) => void
  const spanning = {...approved, requestedStartTime: '2027-01-01T09:00:00+08:00', requestedEndTime: '2027-04-01T10:00:00+08:00'}
  vi.mocked(fetchCalendar).mockResolvedValueOnce([])
    .mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    .mockResolvedValueOnce([spanning]).mockResolvedValueOnce([spanning])
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  range('2027-01-01T09:00', '2027-04-01T10:00')
  fireEvent.click(screen.getByRole('button', {name: 'Inspect range'}))
  expect(fetchCalendar).toHaveBeenCalledTimes(2)
  expect(fetchCalendar).toHaveBeenLastCalledWith(user.id, {start: '2027-01-01', end: '2027-02-12'}, user, expect.any(AbortSignal))
  expect(screen.getByText('Loading inspection…')).toBeInTheDocument()
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  await act(async () => finish([spanning]))
  expect(await screen.findByRole('status')).toHaveTextContent('1 unavailable')
  expect(fetchCalendar).toHaveBeenNthCalledWith(3, user.id, {start: '2027-02-12', end: '2027-03-26'}, user, expect.any(AbortSignal))
  expect(fetchCalendar).toHaveBeenLastCalledWith(user.id, {start: '2027-03-26', end: '2027-04-02'}, user, expect.any(AbortSignal))
})

test.each(['conflict', 'failure'])('later chunk %s fails the whole inspection without partial results', async kind => {
  const spanning = {...approved, requestedEndTime: '2027-02-01T10:00:00+08:00'}
  vi.mocked(fetchCalendar).mockResolvedValueOnce([]).mockResolvedValueOnce([spanning])
  if (kind === 'conflict') vi.mocked(fetchCalendar).mockResolvedValueOnce([{...spanning, reviewedBy: 'changed'}])
  else vi.mocked(fetchCalendar).mockRejectedValueOnce(new Error('offline'))
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  range('2026-10-01T09:00', '2027-02-01T10:00')
  fireEvent.click(screen.getByRole('button', {name: 'Inspect range'}))
  expect(await screen.findByRole('alert')).toHaveTextContent('Inspection unavailable')
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  expect(fetchCalendar).toHaveBeenCalledTimes(3)
  expect(screen.getByText('No bookings in this window.')).toBeInTheDocument()
})

test('overnight month pills include both dates and day headers show actual weekday', async () => {
  vi.mocked(fetchCalendar).mockResolvedValue([{...approved,
    requestedStartTime: '2026-10-01T23:00:00+08:00', requestedEndTime: '2026-10-02T01:00:00+08:00'}])
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  const label = 'Unavailable · 2026-10-01 23:00–2026-10-02 01:00 SGT'
  await screen.findAllByText(label)
  expect(screen.getByRole('button', {name: 'Open 2026-10-01'})).toHaveTextContent(label)
  fireEvent.click(screen.getByRole('button', {name: 'Day'}))
  expect(await screen.findByRole('heading', {name: '2026-10-01'})).toBeInTheDocument()
  expect(await screen.findByText(label)).toBeInTheDocument()
})

test.each(['success', 'failure'])('stale inspection %s is ignored after range edit, including A to B to A', async outcome => {
  let resolve!: (rows: typeof approved[]) => void
  let reject!: (reason: Error) => void
  vi.mocked(fetchCalendar).mockResolvedValueOnce([])
    .mockImplementationOnce(() => new Promise((r, j) => {resolve = r; reject = j}))
    .mockResolvedValueOnce([])
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  range('2026-10-01T09:00', '2027-01-01T10:00')
  fireEvent.click(screen.getByRole('button', {name: 'Inspect range'}))
  range('2026-10-02T09:00', '2026-10-02T10:00')
  range('2026-10-01T09:00', '2026-10-01T10:00')
  fireEvent.click(screen.getByRole('button', {name: 'Inspect range'}))
  expect(await screen.findByRole('status')).toHaveTextContent('0 unavailable')
  await act(async () => {if (outcome === 'success') resolve([approved]); else reject(new Error('old'))})
  expect(screen.getByRole('status')).toHaveTextContent('0 unavailable')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(fetchCalendar).toHaveBeenCalledTimes(3)
})

test.each(['venue', 'identity', 'unmount'])('inspection is invalidated on %s change', async change => {
  let resolve!: (rows: typeof approved[]) => void
  vi.mocked(fetchCalendar).mockResolvedValueOnce([]).mockImplementationOnce(() => new Promise(r => {resolve = r}))
  const page = render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  range('2026-10-01T09:00', '2026-10-01T10:00')
  fireEvent.click(screen.getByRole('button', {name: 'Inspect range'}))
  if (change === 'venue') selectOnly(1)
  else if (change === 'identity') page.rerender(<VenueCalendarPage user={{...user, id: venues[1].id}} initialDate="2026-10-01" />)
  else page.unmount()
  await act(async () => resolve([approved]))
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

test('midnight end excludes next day and ignores records outside precise range', async () => {
  vi.mocked(fetchCalendar).mockResolvedValueOnce([]).mockResolvedValueOnce([approved])
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  range('2026-10-01T10:00:01', '2026-10-02T00:00:00')
  fireEvent.click(screen.getByRole('button', {name: 'Inspect range'}))
  expect(await screen.findByRole('status')).toHaveTextContent('0 unavailable')
  expect(fetchCalendar).toHaveBeenLastCalledWith(user.id, {start: '2026-10-01', end: '2026-10-02'}, user, expect.any(AbortSignal))
  fireEvent.click(screen.getByRole('button', {name: 'Refresh'}))
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

test('out-of-supported-year inspection reports invalid input without a request', async () => {
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  range('10000-01-01T10:00', '10000-01-02T10:00')
  fireEvent.click(screen.getByRole('button', {name: 'Inspect range'}))
  expect(screen.getByRole('alert')).toHaveTextContent('Enter valid dates and times')
  expect(fetchCalendar).toHaveBeenCalledTimes(1)
})

test.each(['Approved', 'Pending', 'Pending Review'] as const)('%s label and complete interval appear in every view and inspection', async status => {
  vi.mocked(fetchCalendar).mockResolvedValue([{...approved, status, blocksSelection: status === 'Approved'}])
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  const label = `${status === 'Approved' ? 'Unavailable' : 'Pending confirmation'} · 09:00–10:00 SGT`
  for (const view of ['Month', 'Day', 'Week']) {
    fireEvent.click(screen.getByRole('button', {name: view}))
    expect(await screen.findByText(label)).toBeInTheDocument()
  }
  range('2026-10-01T09:30', '2026-10-01T09:31')
  fireEvent.click(screen.getByRole('button', {name: 'Inspect range'}))
  expect(await screen.findByRole('status')).toHaveTextContent(status === 'Approved' ? '1 unavailable; 0 pending confirmation' : '0 unavailable; 1 pending confirmation')
})

test('inspection retries independently of failed grid without inferring availability', async () => {
  vi.mocked(fetchCalendar).mockRejectedValueOnce(new Error('grid offline'))
    .mockRejectedValueOnce(new Error('inspection offline')).mockResolvedValueOnce([approved])
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText(/Availability unavailable/)
  range('2026-10-01T09:00', '2026-10-01T10:00')
  fireEvent.click(screen.getByRole('button', {name: 'Inspect range'}))
  await screen.findByText(/Inspection unavailable/)
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', {name: 'Inspect range'}))
  expect(await screen.findByRole('status')).toHaveTextContent('1 unavailable')
  expect(screen.queryByText(/Inspection unavailable/)).not.toBeInTheDocument()
  expect(screen.getByText(/Availability unavailable/)).toBeInTheDocument()
})

test('malformed catalogue row fails closed instead of crashing', async () => {
  vi.mocked(fetchVenues).mockResolvedValue([null] as unknown as typeof venues)
  render(<VenueCalendarPage user={user} />)
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Unable to load venues',
  )
  expect(fetchCalendar).not.toHaveBeenCalled()
})

test('late catalogue success/failure and late availability failure ignored after unmount', async () => {
  let resolve!: (rows: typeof venues) => void
  vi.mocked(fetchVenues).mockImplementationOnce(
    () =>
      new Promise((r) => {
        resolve = r
      }),
  )
  const first = render(<VenueCalendarPage user={user} />)
  first.unmount()
  await act(async () => resolve(venues))
  let reject!: (e: Error) => void
  vi.mocked(fetchVenues).mockImplementationOnce(
    () =>
      new Promise((_r, j) => {
        reject = j
      }),
  )
  const second = render(<VenueCalendarPage user={user} />)
  second.unmount()
  await act(async () => reject(new Error('late catalogue')))
  vi.mocked(fetchVenues).mockResolvedValue(venues)
  vi.mocked(fetchCalendar).mockImplementationOnce(
    () =>
      new Promise((_r, j) => {
        reject = j
      }),
  )
  const third = render(<VenueCalendarPage user={user} />)
  await waitFor(() => expect(fetchCalendar).toHaveBeenCalled())
  third.unmount()
  await act(async () => reject(new Error('late calendar')))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})
test('month approved marker is unavailable and clearing anchor does not navigate', async () => {
  vi.mocked(fetchCalendar).mockResolvedValue([approved])
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('Unavailable · 09:00–10:00 SGT')
  fireEvent.change(screen.getByLabelText('Anchor date'), {
    target: { value: '' },
  })
  expect(screen.getByLabelText('Anchor date')).toHaveValue('2026-10-01')
  fireEvent.click(screen.getByRole('button', { name: 'Month' }))
  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: 'Open 2026-10-01' }),
    ).toHaveTextContent('Unavailable · 09:00–10:00 SGT'),
  )
})

test('keyboard activates month date drilldown and native range controls are labelled',async()=>{
 const keyboard=userEvent.setup()
 render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
 await screen.findByText('No bookings in this window.')
 screen.getByRole('button',{name:'Month'}).focus()
 await keyboard.keyboard('{Enter}')
 const date=await screen.findByRole('button',{name:'Open 2026-10-15'})
 date.focus();await keyboard.keyboard('{Enter}')
 expect(screen.getByRole('button',{name:'Day'})).toHaveAttribute('aria-pressed','true')
 openInspector()
 expect(screen.getByLabelText('Start (SGT)')).toHaveAttribute('step','1')
 expect(screen.getByLabelText('End (SGT)')).toHaveAttribute('step','1')
})


test('range inspector opens over month and successful inspection replaces it', async () => {
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  expect(screen.queryByLabelText('Start (SGT)')).not.toBeInTheDocument()
  const toggle = screen.getByRole('button', { name: 'Inspect time range' })
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(toggle)
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByLabelText('Start (SGT)')).toBeEnabled()
  range('2026-10-01T10:00', '2026-10-01T11:00')
  fireEvent.click(screen.getByRole('button', { name: 'Inspect range' }))
  expect(await screen.findByRole('status')).toHaveTextContent('not a reservation')
  expect(screen.queryByLabelText('Start (SGT)')).not.toBeInTheDocument()
  expect(screen.getByRole('region', {name: 'Inspected range · Week'})).toBeInTheDocument()
  openInspector()
  fireEvent.click(screen.getByRole('button', { name: 'Close inspector' }))
  expect(screen.queryByLabelText('Start (SGT)')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /^Open / })).not.toBeInTheDocument()
})

test('inspection replaces browsing with only selected dates in week format', async () => {
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  range('2027-02-10T09:00', '2027-02-12T00:00')
  fireEvent.click(screen.getByRole('button', {name: 'Inspect range'}))
  const result = await screen.findByRole('region', {name: 'Inspected range · Week'})
  expect([...result.querySelectorAll('[data-inspected-date]')].map(e => e.getAttribute('data-inspected-date'))).toEqual(['2027-02-10', '2027-02-11'])
  expect(screen.queryByRole('button', {name: /^Open /})).not.toBeInTheDocument()
  expect(result).toHaveTextContent('2027-02-10 09:00')
  expect(result.querySelector('.calendar-result-week')).toHaveStyle({gridTemplateColumns: 'repeat(2, minmax(140px, 1fr))'})
  expect(screen.getByRole('button', {name: 'Month'})).toHaveAttribute('aria-pressed', 'false')
  expect(fetchCalendar).toHaveBeenLastCalledWith(venues[0].id, {start: '2027-02-10', end: '2027-02-12'}, user, expect.any(AbortSignal))
  fireEvent.click(screen.getByRole('button', {name: 'Back to calendar'}))
  expect(screen.getAllByRole('button', {name: /^Open /})).toHaveLength(42)
  expect(screen.getByRole('button', {name: 'Month'})).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByRole('checkbox', {name: 'Hall'})).toBeChecked()
})

test.each([
  ['2027-01-29T09:00', '2027-02-05T09:00', 'Week', 8],
  ['2027-01-29T09:00', '2027-02-05T09:00:01', 'Month', 8],
  ['2027-01-29T00:00', '2027-02-07T00:00', 'Month', 9],
])('inspection %s to %s uses %s and preserves every intersecting date', async (start, end, format, count) => {
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('No bookings in this window.')
  range(start, end)
  fireEvent.click(screen.getByRole('button', {name: 'Inspect range'}))
  const result = await screen.findByRole('region', {name: `Inspected range · ${format}`})
  expect(result.querySelectorAll('[data-inspected-date]')).toHaveLength(count)
  expect(result.querySelector('[data-inspected-date="2027-01-28"]')).toBeNull()
  expect(result.querySelector('[data-inspected-date="2027-02-07"]')).toBeNull()
  if (format === 'Month') {
    expect(screen.getByRole('heading', {name: 'January 2027'})).toBeInTheDocument()
    expect(screen.getByRole('heading', {name: 'February 2027'})).toBeInTheDocument()
    expect(result.querySelectorAll('.calendar-alignment-spacer')).toHaveLength(4)
  }
})

test('result clips occupied intervals to the selected range with exact microseconds and closes drawer', async () => {
  vi.mocked(fetchCalendar).mockResolvedValue([approved, {...approved, id: 'pending', status: 'Pending', blocksSelection: false, requestedEndTime: '2026-10-01T09:45:00.000001+08:00'}])
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('Unavailable · 09:00–10:00 SGT')
  range('2026-10-01T09:30', '2026-10-01T09:50')
  fireEvent.click(screen.getByRole('button', {name: 'Inspect range'}))
  const result = await screen.findByRole('region', {name: 'Inspected range · Week'})
  expect(result).toHaveTextContent('Unavailable · 2026-10-01 09:30:00 – 2026-10-01 09:50:00 SGT')
  expect(result).toHaveTextContent('Pending confirmation · 2026-10-01 09:30:00 – 2026-10-01 09:45:00.000001 SGT')
  expect(result).toHaveTextContent('Clipped to selected range/day')
  expect(screen.queryByLabelText('Start (SGT)')).not.toBeInTheDocument()
})

test('busy month cell shows one pill and exact overflow with day drilldown', async () => {
  vi.mocked(fetchCalendar).mockResolvedValue(Array.from({length: 5}, (_, i) => ({...approved, id: `booking-${i}`})))
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  const cell = await screen.findByRole('button', {name: 'Open 2026-10-01'})
  await waitFor(() => expect(cell).toHaveTextContent('+4 more'))
  expect(screen.getAllByText('Unavailable · 09:00–10:00 SGT')).toHaveLength(1)
  fireEvent.click(cell)
  expect(await screen.findAllByText('Unavailable · 09:00–10:00 SGT')).toHaveLength(5)
})

test('week agenda retains all seven days and pending semantics', async () => {
  vi.mocked(fetchCalendar).mockResolvedValue([{...approved, status: 'Pending', blocksSelection: false}])
  render(<VenueCalendarPage user={user} initialDate="2026-10-01" />)
  await screen.findByText('Pending confirmation · 09:00–10:00 SGT')
  fireEvent.click(screen.getByRole('button', {name: 'Week'}))
  await screen.findByText('Pending confirmation · 09:00–10:00 SGT')
  expect(screen.getAllByRole('article')).toHaveLength(7)
  expect([...document.querySelectorAll('.calendar-days .calendar-weekdays span')].map(h => h.textContent)).toEqual(['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'])
  expect(screen.getByText('2026-10-01 09:00:00 – 2026-10-01 10:00:00 SGT')).toBeInTheDocument()
})
