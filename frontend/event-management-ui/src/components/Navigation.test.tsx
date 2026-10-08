import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { Sidebar } from './Navigation'

test('shows My events to Event Coordinators', () => {
  render(<Sidebar route="dashboard" role="Event Coordinator" onNavigate={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'My events' })).toBeInTheDocument()
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

test('Request review tab is still shown to Event Coordinators', () => {
  render(<Sidebar route="review" role="Event Coordinator" onNavigate={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Request review' })).toBeInTheDocument()
})
