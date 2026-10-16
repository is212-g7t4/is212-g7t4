import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { Sidebar } from './Navigation'

test('Event Coordinators get one Events entry instead of separate event pages', () => {
  render(<Sidebar route="dashboard" role="Event Coordinator" onNavigate={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Events' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'My events' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Request review' })).not.toBeInTheDocument()
})

test('Events opens My events for a coordinator and the unassigned queue for the Lead', () => {
  const onNavigate = vi.fn()
  const { rerender } = render(<Sidebar route="dashboard" role="Event Coordinator" onNavigate={onNavigate} />)
  screen.getByRole('button', { name: 'Events' }).click()
  expect(onNavigate).toHaveBeenLastCalledWith('myEvents')
  rerender(<Sidebar route="dashboard" role="Event Coordinator Lead" onNavigate={onNavigate} />)
  screen.getByRole('button', { name: 'Events' }).click()
  expect(onNavigate).toHaveBeenLastCalledWith('queue')
})

test('shows My events to Event Organisers', () => {
  render(<Sidebar route="dashboard" role="Event Organiser" onNavigate={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'My events' })).toBeInTheDocument()
})

test.each(['Venue Staff', 'Technical Support'] as const)('shows My events to %s', (role) => {
  render(<Sidebar route="dashboard" role={role} onNavigate={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'My events' })).toBeInTheDocument()
})

test('hides My events from attendees', () => {
  render(<Sidebar route="dashboard" role="Attendee" onNavigate={vi.fn()} />)
  expect(screen.queryByRole('button', { name: 'My events' })).not.toBeInTheDocument()
})

test('shows Browse events only to attendees', () => {
  const view = render(<Sidebar route="browseEvents" role="Attendee" onNavigate={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Browse events' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'My registrations' })).toBeInTheDocument()

  view.rerender(<Sidebar route="dashboard" role="Event Coordinator" onNavigate={vi.fn()} />)
  expect(screen.queryByRole('button', { name: 'Browse events' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'My registrations' })).not.toBeInTheDocument()
})

test('Request review tab is hidden from Event Organisers', () => {
  render(<Sidebar route="myEvents" role="Event Organiser" onNavigate={vi.fn()} />)
  expect(screen.queryByRole('button', { name: 'Request review' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'My events' })).toBeInTheDocument()
})

test('Request review is still its own entry for Venue Staff', () => {
  render(<Sidebar route="review" role="Venue Staff" onNavigate={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Request review' })).toBeInTheDocument()
})

test('Safety checks tab is shown only to Safety Officers', () => {
  render(<Sidebar route="dashboard" role="Safety Officer" onNavigate={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Safety checks' })).toBeInTheDocument()
})

test.each(['Event Coordinator', 'Venue Staff', 'Technical Support', 'Attendee'] as const)(
  'Safety checks tab is hidden from %s',
  (role) => {
    render(<Sidebar route="dashboard" role={role} onNavigate={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Safety checks' })).not.toBeInTheDocument()
  },
)
