import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { VenueSearchPage } from './VenueSearchPage'
import * as venues from '../features/venue/venues'
import * as venueSearch from '../features/venue/venueSearch'
import type { VenueSearchResult } from '../features/venue/venueSearch'

const CATALOGUE: venues.Venue[] = [
  {
    id: 'v1', name: 'Grand Ballroom', location: 'Level 3, Main Tower', capacity: 500,
    facilities: ['stage', 'wifi'], accessibility: 'Wheelchair accessible',
    supportedLayouts: ['banquet', 'theatre'], status: 'Available',
  },
  {
    id: 'v2', name: 'Rooftop Garden', location: 'Level 12, Main Tower', capacity: 150,
    facilities: ['outdoor', 'wifi'], accessibility: 'Elevator access, no stairs',
    supportedLayouts: ['standing'], status: 'Available',
  },
]

const RESULT: VenueSearchResult = { ...CATALOGUE[1], availability: 'Available' }
const PENDING: VenueSearchResult = { ...CATALOGUE[0], availability: 'Pending request' }

let searchSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  window.history.replaceState({}, '', '/venue-search')
  vi.spyOn(venues, 'fetchVenues').mockResolvedValue(CATALOGUE)
  searchSpy = vi.spyOn(venueSearch, 'searchVenues').mockResolvedValue([RESULT])
})
afterEach(() => vi.restoreAllMocks())

const show = (role: venues.Venue extends never ? never : string = 'Event Coordinator') =>
  render(<VenueSearchPage role={role as never} onViewVenue={vi.fn()} />)

const fillRequired = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.type(screen.getByLabelText(/^Date/), '2026-11-10')
  await user.type(screen.getByLabelText(/^Start time/), '09:00')
  await user.type(screen.getByLabelText(/^End time/), '12:00')
  await user.type(screen.getByLabelText(/^Expected attendance/), '120')
}

const searchButton = () => screen.getByRole('button', { name: /Search/ })

describe('role rule', () => {
  test.each(['Venue Staff', 'Event Organiser', 'Technical Support', 'Attendee'])(
    '%s sees the notice and no form', (role) => {
      show(role)
      expect(screen.getByText('Venue search is available to Event Coordinators.')).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /Search/ })).not.toBeInTheDocument()
    })

  test('an Event Coordinator gets the form', async () => {
    show()
    expect(searchButton()).toBeInTheDocument()
    await waitFor(() => expect(venues.fetchVenues).toHaveBeenCalled())
  })
})

describe('AC1 — the criteria', () => {
  test('the four required fields are marked required', () => {
    show()
    for (const label of [/^Date/, /^Start time/, /^End time/, /^Expected attendance/]) {
      expect(screen.getByLabelText(label)).toBeRequired()
    }
  })

  test('layout and facility options come from the live catalogue', async () => {
    show()
    // A facility added under SCRUM-22 should appear without a code change.
    await screen.findByRole('checkbox', { name: 'outdoor' })
    expect(screen.getByRole('checkbox', { name: 'stage' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'banquet' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Any layout' })).toBeInTheDocument()
  })

  test('the form still works when the catalogue cannot be loaded', async () => {
    vi.spyOn(venues, 'fetchVenues').mockRejectedValue(new Error('down'))
    const user = userEvent.setup()
    show()

    expect(await screen.findByText(/Filter options could not be loaded/)).toBeInTheDocument()
    await fillRequired(user)
    await user.click(searchButton())
    await waitFor(() => expect(searchSpy).toHaveBeenCalled())
  })
})

describe('AC2 — required criteria', () => {
  test('an empty search names the missing fields and sends nothing', async () => {
    const user = userEvent.setup()
    show()

    await user.click(searchButton())

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Please fill in the required fields: Date, Start time, End time, Expected attendance')
    expect(searchSpy).not.toHaveBeenCalled()
  })

  test('the message narrows as fields are filled', async () => {
    const user = userEvent.setup()
    show()
    await user.type(screen.getByLabelText(/^Date/), '2026-11-10')

    await user.click(searchButton())

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Start time, End time, Expected attendance')
    expect(alert).not.toHaveTextContent('Date,')
    expect(searchSpy).not.toHaveBeenCalled()
  })
})

describe('AC3/AC4 — results', () => {
  test('a complete search sends the criteria and lists what comes back', async () => {
    const user = userEvent.setup()
    show()
    await fillRequired(user)

    await user.click(searchButton())

    expect(await screen.findByText('Rooftop Garden')).toBeInTheDocument()
    expect(searchSpy.mock.calls[0][0]).toMatchObject({
      date: '2026-11-10', startTime: '09:00', endTime: '12:00', expectedAttendance: '120',
    })
  })

  test('a card shows the details AC4 asks for, with layouts and facilities labelled', async () => {
    const user = userEvent.setup()
    show()
    await fillRequired(user)
    await user.click(searchButton())

    const card = await screen.findByRole('button', { name: /View details for Rooftop Garden/ })
    expect(within(card).getByText('Level 12, Main Tower')).toBeInTheDocument()
    expect(within(card).getByText('150 people')).toBeInTheDocument()
    expect(within(card).getByText('Elevator access, no stairs')).toBeInTheDocument()
    expect(within(card).getByText('Layouts')).toBeInTheDocument()
    expect(within(card).getByText('Facilities')).toBeInTheDocument()
    expect(within(card).getByText('Available')).toBeInTheDocument()
  })

  test('a pending venue is badged and explained rather than hidden', async () => {
    searchSpy.mockResolvedValue([PENDING])
    const user = userEvent.setup()
    show()
    await fillRequired(user)
    await user.click(searchButton())

    const badge = await screen.findByText('Pending request')
    expect(badge).toHaveAttribute('title', expect.stringContaining('waiting for review'))
  })

  test('clicking a card opens that venue', async () => {
    const onViewVenue = vi.fn()
    const user = userEvent.setup()
    render(<VenueSearchPage role="Event Coordinator" onViewVenue={onViewVenue} />)
    await fillRequired(user)
    await user.click(searchButton())

    await user.click(await screen.findByRole('button', { name: /View details for Rooftop Garden/ }))

    expect(onViewVenue).toHaveBeenCalledWith('v2')
  })

  test('the search is mirrored into the URL so Back can restore it', async () => {
    const user = userEvent.setup()
    show()
    await fillRequired(user)
    await user.click(searchButton())

    await waitFor(() => expect(window.location.search).toContain('start=2026-11-10T09%3A00%3A00'))
    expect(window.location.pathname).toBe('/venue-search')
  })

  test('a search already in the URL is re-run on mount', async () => {
    window.history.replaceState({}, '',
      '/venue-search?start=2026-11-10T09:00:00&end=2026-11-10T12:00:00&expectedAttendance=120&facility=wifi')
    show()

    expect(await screen.findByText('Rooftop Garden')).toBeInTheDocument()
    expect(searchSpy.mock.calls[0][0]).toMatchObject({
      date: '2026-11-10', startTime: '09:00', endTime: '12:00',
      expectedAttendance: '120', facilities: ['wifi'],
    })
  })
})

describe('AC5 — no matches', () => {
  test('an empty result is a message, not an error', async () => {
    searchSpy.mockResolvedValue([])
    const user = userEvent.setup()
    show()
    await fillRequired(user)

    await user.click(searchButton())

    expect(await screen.findByText(
      'No venues are available for the selected date, time and requirements.')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

describe('AC6 — Clear all', () => {
  test('one click empties the fields, the results and the URL', async () => {
    const user = userEvent.setup()
    show()
    await fillRequired(user)
    await user.click(await screen.findByRole('checkbox', { name: 'outdoor' }))
    await user.click(screen.getByRole('checkbox', { name: 'Hearing loop' }))
    await user.click(searchButton())
    await screen.findByText('Rooftop Garden')

    await user.click(screen.getByRole('button', { name: 'Clear all' }))

    expect(screen.getByLabelText(/^Date/)).toHaveValue('')
    expect(screen.getByLabelText(/^Expected attendance/)).toHaveValue(null)
    expect(screen.getByRole('checkbox', { name: 'outdoor' })).not.toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Hearing loop' })).not.toBeChecked()
    expect(screen.queryByText('Rooftop Garden')).not.toBeInTheDocument()
    expect(window.location.search).toBe('')
  })
})

describe('failures', () => {
  test('a server error is shown and clears stale results', async () => {
    const user = userEvent.setup()
    show()
    await fillRequired(user)
    await user.click(searchButton())
    await screen.findByText('Rooftop Garden')

    searchSpy.mockRejectedValue(new Error('Unable to search venues right now.'))
    await user.click(searchButton())

    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to search venues right now.')
    expect(screen.queryByText('Rooftop Garden')).not.toBeInTheDocument()
  })

  test('Search is disabled while a search is in flight', async () => {
    const user = userEvent.setup()
    searchSpy.mockReturnValue(new Promise(() => {}))
    show()
    await fillRequired(user)

    await user.click(searchButton())

    await waitFor(() => expect(searchButton()).toBeDisabled())
    expect(searchSpy).toHaveBeenCalledTimes(1)
  })

  test('a response that lands after Clear all does not repopulate the page', async () => {
    const user = userEvent.setup()
    let resolveSearch: (v: VenueSearchResult[]) => void = () => {}
    searchSpy.mockReturnValue(new Promise((resolve) => { resolveSearch = resolve }))
    show()
    await fillRequired(user)
    await user.click(searchButton())

    await user.click(screen.getByRole('button', { name: 'Clear all' }))
    resolveSearch([RESULT])

    // The in-flight search was abandoned, so its results must not come back.
    await waitFor(() => expect(screen.getByLabelText(/^Date/)).toHaveValue(''))
    expect(screen.queryByText('Rooftop Garden')).not.toBeInTheDocument()
  })
})
