import { allUsers, asUser, json, makeEvent, mock, mockApprovedVenue, test, expect, users, venues } from './fixtures'

test('attendee registers for an open confirmed event', async ({ page, mockApi }) => {
  const event = makeEvent({
    id: 'evt-registration', eventName: 'Community Workshop', status: 'Confirmed',
    expectedAttendance: '3', preferredStartDate: '2099-11-10T09:00:00+08:00',
    preferredEndDate: '2099-11-10T12:00:00+08:00',
  })
  const submitted: Record<string, unknown>[] = []
  await mockApi(page)
  await asUser(page, users.attendee.user_id)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await mock(page, 'user', `/users/${users.attendee.user_id}`, (route) => json(route, users.attendee))
  await mock(page, 'event', '/events/registration', (route) => json(route, { events: [event] }))
  await mock(page, 'registration', '/registrations/counts', (route) => json(route, {
    counts: { [event.id]: { total: 1, confirmed: 1 } },
  }))
  await mockApprovedVenue(page, event.id)
  await mock(page, 'venue', `/venues/${venues[0].id}`, (route) => json(route, { venue: venues[0] }))
  await mock(page, 'attendeeRegistration', '/registrations', (route) => {
    submitted.push(route.request().postDataJSON())
    return json(route, {
      message: 'Registration confirmed for Community Workshop.',
      registration: { registration_id: 'registration-1', status: 'Confirmed' },
    }, 201)
  })

  await page.goto('/events/browse')
  await page.getByRole('button', { name: /Community Workshop/ }).click()
  await page.getByRole('button', { name: 'Register' }).click()
  await expect(page.getByText(users.attendee.email)).toBeVisible()
  await page.getByRole('button', { name: 'Submit registration' }).click()

  await expect(page.getByText('Registration confirmed for Community Workshop.')).toBeVisible()
  expect(submitted).toEqual([{ eventId: event.id, attendeeId: users.attendee.user_id }])
})
