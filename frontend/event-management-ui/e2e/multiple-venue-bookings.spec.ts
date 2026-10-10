import { allUsers, asUser, json, makeEvent, mock, test, expect, users, venues } from './fixtures'

test('assigned coordinator creates and views independent venue bookings for one event', async ({ page, mockApi }) => {
  const event = makeEvent({ expectedAttendance: '500' })
  const testVenues = [{ ...venues[0], capacity: 500 }, venues[1]]
  const submitted: Record<string, unknown>[] = []
  const existing = {
    id: 'booking-a', eventId: event.id, venueId: venues[0].id, venueName: 'Grand Hall',
    requestedStartTime: '2026-12-01T09:00', requestedEndTime: '2026-12-01T17:00',
    requiredCapacity: 500, venueRequirements: 'Main programme', status: 'Approved',
    requestedBy: users.coordinator.user_id, reviewedBy: null,
  }

  await mockApi(page)
  await asUser(page, users.coordinator.user_id)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await mock(page, 'event', '/events', (route) => json(route, { events: [event] }))
  await mock(page, 'event', `/events/${event.id}`, (route) => json(route, event))
  await mock(page, 'venue', '/venues', (route) => json(route, { venues: testVenues }))
  await mock(page, 'venueBooking', `/events/${event.id}/booking-requests`, (route) => json(route, { bookings: [existing] }))
  await mock(page, 'venueBooking', '/booking-requests', (route) => {
    const body = route.request().postDataJSON()
    submitted.push(body)
    return json(route, {
      ...body,
      id: 'booking-b',
      status: 'Pending Review',
      requestedBy: users.coordinator.user_id,
      reviewedBy: null,
    }, 201)
  })
  await mock(page, 'venueBooking', '/booking-requests/booking-a', (route) => {
    const body = route.request().postDataJSON()
    return json(route, {
      ...existing,
      ...body,
      status: 'Pending Review',
      reviewedBy: null,
    })
  })
  await mock(page, 'venueBooking', '/booking-requests/booking-b/cancel', (route) => json(route, {
    ...submitted[0],
    id: 'booking-b',
    status: 'Cancelled',
    requestedBy: users.coordinator.user_id,
    reviewedBy: null,
  }))

  await page.goto('/my-events')
  await page.getByRole('button', { name: /Tech Conference/ }).click()

  await expect(page.getByText('Grand Hall', { exact: true })).toBeVisible()
  await page.getByLabel(/Venue \*/).selectOption(testVenues[1].id)
  await page.getByLabel('Expected attendance / required capacity *').fill('10')
  await page.getByLabel('Venue requirements').fill('Breakout tables')
  await page.getByRole('button', { name: 'Submit venue booking' }).click()

  await expect(page.getByText('Meeting Room booking request submitted independently.')).toBeVisible()
  expect(submitted).toHaveLength(1)
  expect(submitted[0]).toMatchObject({
    eventId: event.id,
    venueId: testVenues[1].id,
    requiredCapacity: 10,
    venueRequirements: 'Breakout tables',
  })

  await page.getByRole('button', { name: 'Edit booking' }).first().click()
  await page.getByLabel('Expected attendance / required capacity *').fill('450')
  await page.getByRole('button', { name: 'Save venue booking' }).click()
  await expect(page.getByText('Grand Hall booking updated and returned to pending review.')).toBeVisible()
  await expect(page.getByText('450', { exact: true })).toBeVisible()

  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Cancel booking' }).last().click()
  await expect(page.getByText('Meeting Room booking cancelled. Other venue bookings were not changed.')).toBeVisible()
  await expect(page.getByText('Cancelled', { exact: true })).toBeVisible()
})
