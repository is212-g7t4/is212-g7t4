import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { InspectionCalendar } from './InspectionCalendar'

test('selected week separates ordered weekday strip from exact date bodies', () => {
  const {container} = render(<InspectionCalendar start="2026-10-01T09:00:00+08:00" end="2026-10-03T00:00:00+08:00" rows={[]} summary="Selected range" onBack={() => {}} />)
  expect([...container.querySelectorAll('.calendar-weekdays span')].map(e => e.textContent)).toEqual(['Thu', 'Fri'])
  expect([...container.querySelectorAll('.calendar-result-day h4')].map(e => e.textContent)).toEqual(['2026-10-01', '2026-10-02'])
})

test('eight intersecting week dates wrap with their own matching heading strip', () => {
  const {container} = render(<InspectionCalendar start="2026-10-01T09:00:00+08:00" end="2026-10-08T09:00:00+08:00" rows={[]} summary="Selected range" onBack={() => {}} />)
  expect(container.querySelectorAll('.calendar-weekdays')).toHaveLength(2)
  expect([...container.querySelectorAll('.calendar-weekdays span')].map(e => e.textContent)).toEqual(['Thu','Fri','Sat','Sun','Mon','Tue','Wed','Thu'])
  expect(container.querySelectorAll('[data-inspected-date]')).toHaveLength(8)
})

test('large results render bounded twelve-month pages with every remaining month reachable', () => {
  const {container} = render(<InspectionCalendar start="2026-01-30T09:00:00+08:00" end="2028-02-02T00:00:00+08:00" rows={[]} summary="Selected range" onBack={() => {}} />)
  expect(container.querySelectorAll('.calendar-result-section')).toHaveLength(12)
  expect(screen.getByText('Months 1–12 of 26')).toBeInTheDocument()
  expect(screen.getByRole('button', {name: 'Earlier selected months'})).toBeDisabled()
  fireEvent.click(screen.getByRole('button', {name: 'Later selected months'}))
  expect(screen.getByText('Months 13–24 of 26')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', {name: 'Later selected months'}))
  expect(screen.getByText('Months 25–26 of 26')).toBeInTheDocument()
  expect(container.querySelectorAll('.calendar-result-section')).toHaveLength(2)
  expect(container.querySelector('[data-inspected-date="2028-02-01"]')).not.toBeNull()
  expect(container.querySelector('[data-inspected-date="2028-02-02"]')).toBeNull()
  expect(screen.getByRole('button', {name: 'Later selected months'})).toBeDisabled()
  fireEvent.click(screen.getByRole('button', {name: 'Earlier selected months'}))
  expect(screen.getByText('Months 13–24 of 26')).toBeInTheDocument()
})
