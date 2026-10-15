import { allUsers, asUser, json, mock, test, expect, users, venues } from './fixtures'

const reason = 'Maintenance <img src=x onerror=alert(1)>\nKeep the original reason.'
const closure = {
  closureId: '00000000-0000-0000-0000-0000000000c1', venueId: venues[0].id,
  startDateTime: '2030-01-31T23:00:00.123456+08:00', endDateTime: '2030-02-02T02:00:00+08:00', reason,
}
test.beforeEach(async ({page, mockApi}) => {
  await mockApi(page)
  await asUser(page, users.venueStaff.user_id)
  await mock(page, 'user', '/users', route => json(route, {users: allUsers}))
  await mock(page, 'venue', '/venues', route => json(route, {venues}))
})

test('SCRUM174 keyboard details keep cross-month microseconds and render reason as plain text', async ({page}) => {
  await mock(page, 'availability', '/venue-bookings', route => json(route, {
    bookings: [], closures: new URL(route.request().url()).searchParams.get('venueId') === venues[0].id ? [closure] : [],
  }))
  await page.goto('/venue-availability')
  await page.getByText('Jump to date').click()
  await page.getByLabel('Anchor date').fill('2030-02-01')
  await page.getByRole('button', {name:'Day',exact:true}).click()
  const summary=page.locator('.calendar-closure-details > summary')
  await summary.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByText('2030-01-31 23:00:00.123456 SGT',{exact:true})).toBeVisible()
  await expect(page.getByText('2030-02-02 02:00:00 SGT',{exact:true})).toBeVisible()
  await expect(page.locator('.calendar-closure-reason')).toHaveText(reason)
  await expect(page.locator('.calendar-closure-reason img')).toHaveCount(0)
})

test('SCRUM174 missing closures on refresh clears stale calendar instead of implying free time', async ({page}) => {
  let malformed=false
  await mock(page, 'availability', '/venue-bookings', route => json(route, malformed ? {bookings: []} : {bookings: [], closures: []}))
  await page.goto('/venue-availability')
  await expect(page.getByText('No bookings or closures in this window.')).toBeVisible()
  malformed=true
  await page.getByRole('button',{name:'Refresh',exact:true}).click()
  await expect(page.getByRole('alert')).toContainText('Availability unavailable. Refresh to retry; no availability can be inferred.')
  await expect(page.getByText('No bookings or closures in this window.')).toHaveCount(0)
  await expect(page.getByRole('button',{name:'Inspect time range',exact:true})).toBeEnabled()
})
