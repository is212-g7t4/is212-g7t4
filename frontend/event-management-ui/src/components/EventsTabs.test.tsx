import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { EventsTabs } from './EventsTabs'
import { coordinatorEventTabs } from '../features/event/permissions'

test('coordinators get My events and Request review tabs', () => {
  render(<EventsTabs tabs={coordinatorEventTabs('Event Coordinator')} route="myEvents" onNavigate={vi.fn()} />)
  expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual(['My events', 'Request review'])
  expect(screen.getByRole('tab', { name: 'My events' })).toHaveAttribute('aria-selected', 'true')
})

test('the Lead also gets the Unassigned requests tab, first', () => {
  const onNavigate = vi.fn()
  render(<EventsTabs tabs={coordinatorEventTabs('Event Coordinator Lead')} route="queue" onNavigate={onNavigate} />)
  expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual(['Unassigned requests', 'My events', 'Request review'])
  screen.getByRole('tab', { name: 'Request review' }).click()
  expect(onNavigate).toHaveBeenCalledWith('review')
})
