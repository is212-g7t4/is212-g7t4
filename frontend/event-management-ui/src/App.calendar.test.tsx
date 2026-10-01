import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import App from './App'
import { fetchUsers } from './features/user/users'
import type { Role } from './types'
vi.mock('./features/user/users', () => ({ fetchUsers: vi.fn() }))
vi.mock('./features/venue/venues', () => ({
  fetchVenues: vi.fn().mockResolvedValue([]),
}))
beforeEach(() => {
  vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => {} })
  window.history.replaceState({}, '', '/venue-availability')
})
test.each([
  'Event Coordinator',
  'Venue Staff',
  'Technical Support',
  'Event Organiser',
  'Attendee',
] as Role[])('calendar direct route and nav reflect %s', async (role) => {
  vi.mocked(fetchUsers).mockResolvedValue([
    {
      id: 'id',
      username: 'test',
      email: '',
      organization: '',
      managerId: null,
      role,
    },
  ])
  render(<App />)
  expect(screen.getByRole('heading', { name: 'Venue availability calendar' })).toBeInTheDocument()
  await screen.findByRole('option', { name: `test — ${role}` })
  expect(document.title).toBe('Venue availability calendar · ConnectSphere')
  if (['Event Organiser', 'Attendee'].includes(role)) {
    expect(screen.getByRole('alert')).toHaveTextContent('Permission denied')
    expect(
      screen.queryByRole('button', { name: /Venue availability calendar/ }),
    ).not.toBeInTheDocument()
  } else {
    expect(
      screen.getByRole('region', { name: 'Venue availability calendar' }),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Venue availability calendar/ }))
    expect(window.location.pathname).toBe('/venue-availability')
  }
})
