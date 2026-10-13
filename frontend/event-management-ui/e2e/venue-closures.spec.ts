import { allUsers, asUser, json, mock, test, expect, users, venues } from './fixtures'

test.use({ timezoneId: 'America/Los_Angeles' })
const closure = { closureId: '00000000-0000-0000-0000-0000000000c1', venueId: venues[0].id, startDateTime: '2020-01-01T09:00:00+08:00', endDateTime: '2099-01-01T10:00:00+08:00', reason: 'Air-conditioning maintenance', createdBy: users.venueStaff.user_id, createdAt: '2026-10-13T09:00:00+08:00' }
test.beforeEach(async ({ page, mockApi }) => {
 await mockApi(page)
 await asUser(page, users.venueStaff.user_id)
 await mock(page, 'user', '/users', route => json(route, { users: allUsers }))
 await mock(page, 'venue', '/venues', route => json(route, { venues }))
 await mock(page, 'venue', `/venues/${venues[0].id}`, route => json(route, { venue: { ...venues[0], status: 'Maintenance' } }))
 await mock(page, 'availability', '/venue-holds', route => json(route, { holds: [] }))
})
test('SCRUM-170 record inline, read persisted pages, retain SGT in non-Singapore browser', async ({ page }, testInfo) => {
 let stored = false
 let posts = 0
 const reads: (string | null)[] = []
 await mock(page, 'venueBooking', '/venue-closures', route => {
  const request = route.request()
  expect(request.headers()['x-dev-user-id']).toBe(users.venueStaff.user_id)
  expect(request.headers()['x-dev-role']).toBe('Venue Staff')
  if (request.method() === 'POST') {
   posts++
   expect(request.postDataJSON()).toEqual({ venueId: venues[0].id, startDateTime: closure.startDateTime, endDateTime: closure.endDateTime, reason: closure.reason })
   stored = true
   return json(route, { closure }, 201)
  }
  const cursor = new URL(request.url()).searchParams.get('cursor')
  reads.push(cursor)
  return json(route, { closures: stored ? [cursor ? { ...closure, closureId: 'c2', reason: 'Later page closure' } : closure] : [], nextCursor: stored && !cursor ? 'next+/' : null })
 })
 await page.goto('/venues')
 await page.getByRole('button', { name: 'View details for Grand Hall' }).click()
 await expect(page.getByText('No recorded closures.')).toBeVisible()
 // React StrictMode may deliver the aborted first mount read before its replay.
 const initialReads = reads.length
 expect(reads.every(cursor => cursor === null)).toBe(true)
 await page.getByRole('button', { name: 'Record temporary closure' }).click()
 await expect(page.getByLabel('Closure venue')).toHaveValue('Grand Hall')
 await page.getByLabel('Closure start (SGT)').fill('2020-01-01T09:00')
 await page.getByLabel('Closure end (SGT)').fill('2099-01-01T10:00')
 await page.getByLabel('Reason', { exact: true }).fill('  Air-conditioning maintenance  ')
 const reasonBounds = await page.getByLabel('Reason', { exact: true }).boundingBox()
 const saveBounds = await page.getByRole('button', { name: 'Save closure' }).boundingBox()
 expect(saveBounds!.y).toBeGreaterThanOrEqual(reasonBounds!.y + reasonBounds!.height)
 await page.screenshot({ path: testInfo.outputPath('closure-form.png'), fullPage: true })
 await page.getByRole('button', { name: 'Save closure' }).click()
 await expect(page.getByText('Closure recorded.', { exact: true })).toBeVisible()
 await expect(page.getByText('1 Jan 2020, 09:00 SGT – 1 Jan 2099, 10:00 SGT')).toBeVisible()
 await page.getByRole('button', { name: 'Load more closures' }).click()
 await expect(page.getByText('Later page closure', { exact: true })).toBeVisible()
 expect(posts).toBe(1)
 expect(reads.slice(initialReads)).toEqual([null, 'next+/'])
 await page.screenshot({ path: testInfo.outputPath('closure-persisted.png'), fullPage: true })
 await page.getByLabel('Select active user').selectOption(users.coordinator.user_id)
 await expect(page.getByRole('region', { name: 'Temporary venue closures' })).toHaveCount(0)
 expect(reads).toHaveLength(initialReads + 2)
})
test('SCRUM-170 lost save response preserves draft, warns instead of automatic retry', async ({ page }) => {
 let posts = 0
 await mock(page, 'venueBooking', '/venue-closures', route => {
  if (route.request().method() === 'POST') { posts++; return route.abort() }
  return json(route, { closures: [], nextCursor: null })
 })
 await page.goto('/venues')
 await page.getByRole('button', { name: 'View details for Grand Hall' }).click()
 await page.getByRole('button', { name: 'Record temporary closure' }).click()
 await page.getByLabel('Closure start (SGT)').fill('2020-01-01T09:00')
 await page.getByLabel('Closure end (SGT)').fill('2099-01-01T10:00')
 await page.getByLabel('Reason', { exact: true }).fill('Repairs')
 await page.getByRole('button', { name: 'Save closure' }).click()
 await expect(page.getByRole('alert')).toContainText('may have been recorded')
 await expect(page.getByLabel('Reason', { exact: true })).toHaveValue('Repairs')
 expect(posts).toBe(1)
 await page.getByRole('button', { name: 'Refresh closures' }).click()
 await expect(page.getByText('No recorded closures.')).toBeVisible()
 expect(posts).toBe(1)
})
