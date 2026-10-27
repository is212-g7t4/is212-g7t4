import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { EventDetailPage } from './EventDetailPage'

afterEach(() => vi.unstubAllGlobals())

/**
 * SCRUM-47 supporting design rule (not a new acceptance criterion): keep the
 * original submitter's booking-decision destination after reassignment, but
 * explain lost event access instead of granting access or changing recipients.
 * Exercises the page and eventApi together; only HTTP is doubled. The 403 body
 * matches Event Service app/__init__.py:get_event_details (EventNotAssignedError).
 * This checks presentation and the scoped request, not reassignment persistence,
 * inbox delivery/immutability or backend permission enforcement. A subsequent
 * 503 must remain a service error rather than being labelled lost access.
 */
test('an original submitter opening an old booking link sees lost access only for a forbidden event', async () => {
  const eventId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
  const originalSubmitterId = '11111111-1111-4111-8111-111111111111'
  const bookingId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({
      message: 'This event request is not assigned to the current coordinator.',
    }), { status: 403 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      message: 'DATABASE_URL is not configured for Event Service.',
    }), { status: 503 }))
  vi.stubGlobal('fetch', fetchMock)

  render(<EventDetailPage eventId={eventId} targetBookingId={bookingId}
    role="Event Coordinator" currentCoordinatorId={originalSubmitterId}
    backLabel="notifications" onBack={vi.fn()} />)

  expect(await screen.findByRole('alert')).toHaveTextContent('You no longer have access to this event')
  expect(screen.queryByRole('button', { name: 'Save progress' })).not.toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(fetchMock).toHaveBeenLastCalledWith(
    expect.stringMatching(new RegExp(`/events/${eventId}\\?coordinatorId=${originalSubmitterId}$`)),
    { method: 'GET', headers: {} },
  )

  fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('DATABASE_URL is not configured for Event Service.')
  expect(screen.queryByText('You no longer have access to this event')).not.toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledTimes(2)
})
