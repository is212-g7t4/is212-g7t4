/**
 * SCRUM-28 Venue Booking Request Submission (mocked browser).
 *
 * As an Event Coordinator, I want to submit a venue booking request for an event,
 * so that Venue Staff can assess whether the requested venue arrangement can be accepted.
 *
 * Every backend call is mocked: these prove the UI sends and shows the right
 * things, not the backend rules (those are in each service's tests).
 */
import { allUsers, asUser, json, makeEvent, mock, test, expect, users, venues } from './fixtures'

const event = makeEvent({ id: 'evt-028', eventName: 'Harbour Lights Gala', status: 'Under Review', expectedAttendance: '150' })

test('AC1/AC2: the coordinator enters the booking timing and requirements and submits it for review', async ({ page, mockApi }) => {
  const submitted: Record<string, unknown>[] = []
  await mockApi(page)
  await asUser(page, users.coordinator.user_id)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await mock(page, 'event', '/events', (route) => json(route, { events: [event] }))
  await mock(page, 'event', `/events/${event.id}`, (route) => json(route, event))
  await mock(page, 'venue', '/venues', (route) => json(route, { venues }))
  await mock(page, 'venueBooking', `/events/${event.id}/booking-requests`, (route) => json(route, { bookings: [] }))
  await mock(page, 'venueBooking', '/booking-requests', (route) => {
    const body = route.request().postDataJSON()
    submitted.push(body)
    return json(route, { ...body, id: 'booking-028', status: 'Pending Review', requestedBy: users.coordinator.user_id,
      reviewedBy: null, requestedAt: '2026-11-02T02:00:00+00:00' }, 201)
  })

  await page.goto('/my-events')
  await page.getByRole('button', { name: /Harbour Lights Gala/ }).click()
  await page.getByLabel(/Venue \*/).selectOption(venues[0].id)
  await page.getByLabel('Booking start *').fill('2026-12-01T18:00')
  await page.getByLabel('Booking end *').fill('2026-12-01T22:00')
  await page.getByLabel('Expected attendance / required capacity *').fill('150')
  await page.getByLabel('Venue requirements').fill('Stage and dance floor')
  await page.getByRole('button', { name: 'Submit venue booking' }).click()

  await expect(page.getByText('Grand Hall booking request submitted. Status: Pending Review.')).toBeVisible()
  expect(submitted).toEqual([{
    eventId: event.id,
    venueId: venues[0].id,
    coordinatorId: users.coordinator.user_id,
    requestedStartTime: '2026-12-01T18:00',
    requestedEndTime: '2026-12-01T22:00',
    requiredCapacity: 150,
    venueRequirements: 'Stage and dance floor',
  }])
})

test('AC2: an event whose safety check has started shows why no new request can be made', async ({ page, mockApi }) => {
  const pending = { ...event, status: 'Pending Safety Check' }
  await mockApi(page)
  await asUser(page, users.coordinator.user_id)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await mock(page, 'event', '/events', (route) => json(route, { events: [pending] }))
  await mock(page, 'event', `/events/${pending.id}`, (route) => json(route, pending))
  await mock(page, 'venue', '/venues', (route) => json(route, { venues }))
  await mock(page, 'venueBooking', `/events/${pending.id}/booking-requests`, (route) => json(route, { bookings: [] }))

  await page.goto('/my-events')
  await page.getByRole('button', { name: /Harbour Lights Gala/ }).click()

  await expect(page.getByText(
    'New venue requests can be submitted while the event is Submitted, Under Review, Approved or Safety Changes Requested.',
  )).toBeVisible()
  await expect(page.getByRole('button', { name: 'Submit venue booking' })).toHaveCount(0)
})

test('AC3/AC4/AC5: Venue Staff see the request under its event, with the event dates, awaiting review', async ({ page, mockApi }) => {
  await mockApi(page)
  await asUser(page, users.venueStaff.user_id)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await mock(page, 'venueBooking', '/booking-requests', (route) => json(route, { events: [{
    eventId: event.id, eventName: 'Harbour Lights Gala', eventStatus: 'Under Review', coordinatorId: users.coordinator.user_id,
    eventStart: '2026-12-01T09:00:00', eventEnd: '2026-12-01T23:00:00', awaitingReviewCount: 1,
    bookings: [{ id: 'booking-028', eventId: event.id, venueId: venues[0].id, venueName: 'Grand Hall',
      requestedStartTime: '2026-12-01T18:00:00', requestedEndTime: '2026-12-01T22:00:00', requiredCapacity: 150,
      venueRequirements: 'Stage and dance floor', status: 'Pending Review', requestedBy: users.coordinator.user_id,
      reviewedBy: null, requestedAt: '2026-11-02T02:00:00+00:00', awaitingReview: true, safetyFeedback: null }],
  }] }))

  await page.goto('/venue-requests')

  const card = page.locator('article').filter({ hasText: 'Harbour Lights Gala' })
  await expect(card.getByText(/Event: Tue, 1 Dec · 9:00 am – 11:00 pm/)).toBeVisible()
  await expect(card.getByText('1 awaiting review')).toBeVisible()
  const row = card.getByRole('row').filter({ hasText: 'Grand Hall' })
  await expect(row.locator('.status-badge')).toHaveText('Awaiting review')
  await expect(row.getByText('Stage and dance floor')).toBeVisible()
  await expect(row.getByText('Submitted 2 Nov 2026, 10:00 am')).toBeVisible()
  // SCRUM-29: the decision is made in a review dialog opened from this button.
  await expect(row.getByRole('button', { name: 'Review', exact: true })).toBeVisible()
})
