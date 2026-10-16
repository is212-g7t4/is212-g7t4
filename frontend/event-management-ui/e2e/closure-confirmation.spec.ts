/**
 * # Test scope and acceptance mapping — SCRUM-171 integration
 *
 * - **SCRUM-171 AC4 — confirmation UI:** desktop/mobile cases assert closure details, affected count and complete named request list; back/discard sends no save; changed impact is reviewed before a second explicit confirmation. API mocks do not prove AC1/AC2 persistence or AC5 transactions.
 *
 * ## Case/group traceability
 *
 * The named test functions/cases below implement the groups above; their existing
 * names and assertions specify the scenario. No group is credited with all five ACs.
 */
import { allUsers, asUser, json, mock, test, expect, users, venues } from './fixtures'
for (const mobile of [false, true]) {
 test(`SCRUM171 ${mobile ? 'mobile' : 'desktop'} complete preview, cancel and changed-impact explicit reconfirmation`, async ({ page, mockApi }, info) => {
  await page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 1440, height: 1100 })
  await mockApi(page); await asUser(page, users.venueStaff.user_id)
  await mock(page, 'user', '/users', r => json(r, { users: allUsers }))
  await mock(page, 'venue', `/venues/${venues[0].id}`, r => json(r, { venue: venues[0] }))
  await mock(page, 'availability', '/venue-holds', r => json(r, { holds: [] }))
  let posts = 0, previews = 0
  await mock(page, 'venueBooking', '/venue-closures', r => {
   if (r.request().method() === 'POST') { posts++; return json(r, { code: 'CLOSURE_PREVIEW_CHANGED', message: 'Changed' }, 409) }
   return json(r, { closures: [], nextCursor: null })
  })
  await mock(page, 'venueBooking', '/venue-closures/preview', r => {
   previews++
   const closure = r.request().postDataJSON()
   const affectedRequests = Array.from({ length: previews > 2 ? 0 : 105 }, (_, i) => ({ id: `b${i}`, eventId: `e${i}`, venueId: venues[0].id, eventName: `Event ${i}`, venueName: venues[0].name, status: 'Approved', requestedStartTime: '2099-01-01T02:00:00Z', requestedEndTime: '2099-01-01T04:00:00Z' }))
   return json(r, { closure, venueName: venues[0].name, affectedCount: affectedRequests.length, affectedRequests, confirmationToken: `signed-${previews}` })
  })
  await page.goto(`/venues/${venues[0].id}`)
  await page.getByRole('button', { name: 'Record temporary closure' }).click()
  await page.getByLabel('Closure start (SGT)').fill('2099-01-01T10:00')
  await page.getByLabel('Closure end (SGT)').fill('2099-01-01T12:00')
  await page.getByLabel('Reason', { exact: true }).fill('Maintenance <script>plain text</script>')
  await page.getByRole('button', { name: 'Preview affected requests' }).click()
  const list = page.getByRole('list', { name: 'Affected booking requests' })
  await expect(list.locator('li')).toHaveCount(105)
  await expect(page.getByText('105 booking requests will be rejected.')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Confirm temporary closure' })).toBeFocused()
  await list.evaluate(el => { el.scrollTop = el.scrollHeight })
  await expect(page.getByText('Event 104', { exact: true })).toBeVisible()
  expect(posts).toBe(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: info.outputPath(`preview-${mobile ? 'mobile' : 'desktop'}.png`), fullPage: true })
  await page.getByRole('button', { name: 'Back to edit' }).click()
  expect(posts).toBe(0)
  await page.getByRole('button', { name: 'Preview affected requests' }).click()
  await page.getByRole('button', { name: 'Confirm closure and reject requests' }).click()
  await expect(page.getByText('0 booking requests will be rejected.')).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('confirm again')
  expect(posts).toBe(1)
  await page.getByRole('button', { name: 'Discard closure draft' }).click()
  expect(posts).toBe(1)
 })
}
test.use({ timezoneId: 'America/Los_Angeles' })
