import { allUsers, asUser, json, mock, test, expect, users, venues } from './fixtures'

const booking = {
  id: '00000000-0000-0000-0000-0000000000b1',
  eventId: '00000000-0000-0000-0000-0000000000e1',
  venueId: venues[0].id,
  requestedBy: null,
  reviewedBy: null,
  status: 'Approved',
  blocksSelection: true,
  requestedStartTime: '2026-10-01T09:00:00+08:00',
  requestedEndTime: '2026-10-01T10:00:00+08:00',
}

test.beforeEach(async ({ page, mockApi }) => {
  await mockApi(page)
  await asUser(page, users.venueStaff.user_id)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await mock(page, 'venue', '/venues', (route) => json(route, { venues }))
  await mock(page, 'availability', '/venue-holds', (route) => json(route, { holds: [] }))
})

test('venue staff browses the catalogue and opens a venue', async ({ page }) => {
  await mock(page, 'venue', `/venues/${venues[0].id}`, (route) => json(route, { venue: venues[0] }))
  await page.goto('/venues')

  await expect(page.getByRole('button', { name: 'View details for Meeting Room' })).toBeVisible()
  await page.getByRole('button', { name: 'View details for Grand Hall' }).click()

  await expect(page.getByRole('heading', { name: 'Grand Hall' })).toBeVisible()
  await expect(page.getByText('Location').locator('..')).toContainText('Level 1')
  await expect(page.getByText('Capacity').locator('..')).toContainText('200')

  await page.getByRole('button', { name: 'Back to venue catalogue' }).click()
  await expect(page.getByRole('button', { name: 'View details for Grand Hall' })).toBeVisible()
})

test('calendar shows a blocking booking for the selected venue', async ({ page }) => {
  const headers: Record<string, string>[] = []
  await mock(page, 'availability', '/venue-bookings', (route) => {
    const request = route.request()
    headers.push(request.headers())
    const venueId = new URL(request.url()).searchParams.get('venueId')
    return json(route, { bookings: venueId === booking.venueId ? [booking] : [] })
  })
  await page.goto('/venue-availability')

  const calendar = page.getByRole('region', { name: 'Venue availability calendar' })
  await calendar.getByText('Jump to date').click()
  await calendar.getByLabel('Anchor date').fill('2026-10-01')

  await expect(calendar.getByText('Unavailable · 09:00–10:00 SGT')).toBeVisible()
  expect(headers[0]['x-dev-user-id']).toBe(users.venueStaff.user_id)
  expect(headers[0]['x-dev-role']).toBe('Venue Staff')

  await calendar.getByRole('button', { name: 'Week' }).click()
  await expect(calendar.getByRole('button', { name: 'Week' })).toHaveAttribute('aria-pressed', 'true')
  await expect(calendar.getByText('Unavailable · 09:00–10:00 SGT')).toBeVisible()
})

test('calendar fails closed when availability cannot be loaded', async ({ page }) => {
  await mock(page, 'availability', '/venue-bookings', (route) => json(route, { error: 'boom' }, 500))
  await page.goto('/venue-availability')
  await expect(page.getByText(/Availability unavailable/)).toBeVisible()
})
