import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { Sidebar } from './Navigation'

test('shows My events to Event Coordinators', () => {
  render(<Sidebar route="dashboard" role="Event Coordinator" onNavigate={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'My events' })).toBeInTheDocument()
})

test('hides My events from other roles', () => {
  render(<Sidebar route="dashboard" role="Event Organiser" onNavigate={vi.fn()} />)
  expect(screen.queryByRole('button', { name: 'My events' })).not.toBeInTheDocument()
})
