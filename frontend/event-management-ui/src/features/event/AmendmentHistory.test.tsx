import { render, screen, within } from '@testing-library/react'
import { expect, test } from 'vitest'
import { AmendmentHistory } from './AmendmentHistory'
import type { EventAmendment } from './submission'

// SCRUM-16 AC2/AC4/AC5: each round's fields, reason, requester and outcome.

const coordinatorId = '11111111-1111-4111-8111-111111111111'
const open: EventAmendment = {
  id: 'amendment-2',
  fields: ['venueRequirements'],
  reason: 'Pick a larger room.',
  requestedBy: coordinatorId,
  requestedAt: '2026-10-22T01:00:00+00:00',
  resubmittedBy: null,
  resubmittedAt: null,
  changes: null,
  note: null,
}
const closed: EventAmendment = {
  id: 'amendment-1',
  fields: ['preferredStartDate', 'preferredEndDate', 'expectedAttendance'],
  reason: 'The hall is booked that week.',
  requestedBy: coordinatorId,
  requestedAt: '2026-10-20T01:00:00+00:00',
  resubmittedBy: '33333333-3333-4333-8333-333333333333',
  resubmittedAt: '2026-10-21T02:00:00+00:00',
  changes: {
    preferredEndDate: { from: '2030-03-01T17:00:00+08:00', to: '2030-03-01T15:00:00+08:00' },
    expectedAttendance: { from: '25', to: '18' },
    accessibilityNeeds: { from: '', to: 'Ramp' },
  },
  note: 'Shortened the day.',
}

test('renders nothing when there is no amendment history', () => {
  const { container } = render(<AmendmentHistory amendments={[]} />)
  expect(container).toBeEmptyDOMElement()
})

test('lists rounds newest first, open and resubmitted', () => {
  render(<AmendmentHistory amendments={[closed, open]} resolveUserName={() => 'Alicia Tan'} />)

  const [first, second] = screen.getAllByRole('article')
  expect(first).toHaveTextContent('Fields to amend: Venue requirements')
  expect(first).toHaveTextContent('Pick a larger room.')
  expect(first).toHaveTextContent('Requested by Alicia Tan on')
  expect(first).toHaveTextContent("Awaiting the Event Organiser's amendment.")

  expect(second).toHaveTextContent('Fields to amend: Date/time and Expected attendance')
  expect(second).toHaveTextContent('Resubmitted on')
  expect(second).toHaveTextContent('Organiser note: Shortened the day.')
})

test('a resubmitted round lists each change from → to', () => {
  render(<AmendmentHistory amendments={[closed]} />)

  const changes = within(screen.getByRole('list', { name: 'Amended fields' })).getAllByRole('listitem')
  expect(changes.map((item) => item.textContent)).toEqual([
    'Preferred End Date & Time: 1 Mar 2030, 05:00 pm → 1 Mar 2030, 03:00 pm',
    'Expected Attendance: 25 → 18',
    'Accessibility Needs: (blank) → Ramp',
  ])
  // Without a name lookup the raw id is shown.
  expect(screen.getByText(new RegExp(`Requested by ${coordinatorId}`))).toBeInTheDocument()
})

test('a resubmitted round without changes or a note shows neither', () => {
  render(<AmendmentHistory amendments={[{ ...closed, changes: null, note: null }]} />)
  expect(screen.queryByRole('list')).not.toBeInTheDocument()
  expect(screen.queryByText(/Organiser note/)).not.toBeInTheDocument()
})

test('an unknown field name is shown as it is', () => {
  render(<AmendmentHistory amendments={[{ ...closed, changes: { legacyField: { from: 'a', to: 'b' } } }]} />)
  expect(screen.getByRole('listitem')).toHaveTextContent('legacyField: a → b')
})
