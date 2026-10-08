import { allUsers, asUser, json, makeEvent, mock, test, expect, users, venues } from './fixtures'

test('attendee opens a registered event and views submitted registration details', async ({ page, mockApi }) => {
  const event = makeEvent({
    id: 'evt-registration-status', eventName: 'Community Workshop', status: 'Confirmed',
    preferredStartDate: '2099-11-10T09:00:00+08:00', preferredEndDate: '2099-11-10T12:00:00+08:00',
    description: 'A practical community workshop.',
  })
  await mockApi(page)
  await asUser(page, users.attendee.user_id)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await mock(page, 'attendeeRegistration', '/registrations', (route) => {
    expect(new URL(route.request().url()).searchParams.get('attendeeId')).toBe(users.attendee.user_id)
    return json(route, { registrations: [{
      registration: {
        registration_id: 'registration-1', event_id: event.id, attendee_id: users.attendee.user_id,
        registration_date: '2026-10-08T10:00:00+08:00', status: 'Confirmed',
        attendee_name: 'Adam Yeo', attendee_email: 'adam@example.com', attendee_organization: 'External',
      },
      event,
    }] })
  })
  await mock(page, 'venue', `/venues/${event.venueId}`, (route) => json(route, { venue: venues[0] }))

  await page.goto('/registrations')
  await expect(page.getByRole('button', { name: /Community Workshop/ })).toContainText('Confirmed')
  await page.getByRole('button', { name: /Community Workshop/ }).click()

  await expect(page.getByRole('heading', { name: 'Registration details' })).toBeVisible()
  await expect(page.getByText('Adam Yeo')).toBeVisible()
  await expect(page.getByText('adam@example.com')).toBeVisible()
  await expect(page.getByText('External')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Event details' })).toBeVisible()
  await expect(page.getByText('Grand Hall')).toBeVisible()
  await expect(page.getByText('A practical community workshop.')).toBeVisible()
})
