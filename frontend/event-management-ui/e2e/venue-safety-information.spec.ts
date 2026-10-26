/**
 * # SCRUM-167 — Record Venue Safety Information
 *
 * As a Venue Staff member, I want to record a venue's emergency access details and known operational restrictions, so that the Safety Officer can take them into account when reviewing events at that venue.
 * AC1: Given authorised Venue Staff edit a venue, when they enter emergency access details (e.g. exits, assembly point, emergency vehicle access) and known restrictions (e.g. noise curfew, no open flames, floor load limit), then the details are saved with the venue and shown on its details page.
 * AC2: Given a venue has no safety information recorded, when it is viewed, then the fields show "Not provided" rather than appearing blank.
 * AC3: Given safety information is updated, when it is saved, then the editor and timestamp are recorded.
 * AC4: Given a user who is not Venue Staff, when they attempt to edit venue safety information through the UI or API, then the change is rejected and the existing values are unchanged.
 *
 * Mocked APIs: proves the UI flow and the request it sends. Persistence, the
 * stamp and the API's role refusal are proven by Venue Service's tests.
 */
import { allUsers, asUser, json, mock, mockVenueSafetyInfo, test, expect, users, venues } from './fixtures'

const EMERGENCY = 'Exits on north and south walls\nAssembly point at the front lawn'
const RESTRICTIONS = 'Noise curfew 10pm; no open flames'

test('Venue Staff record safety information and an Event Coordinator can read it', async ({ page, mockApi }) => {
  await mockApi(page)
  await asUser(page, users.venueStaff.user_id)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await mock(page, 'availability', '/venue-holds', (route) => json(route, { holds: [] }))
  await mock(page, 'venueBooking', '/venue-closures', (route) => json(route, { closures: [], nextCursor: null }))
  let venue = { ...venues[0] }
  await mock(page, 'venue', `/venues/${venue.id}`, (route) => json(route, { venue }))
  await mock(page, 'venueBooking', `/venues/${venue.id}`, (route) => json(route, { venue, legacyConflicts: { conflicts: [] } }))
  const safetySaves: { body: unknown; role: string | undefined; userId: string | undefined }[] = []
  await mockVenueSafetyInfo(page, venue.id, (route) => {
    const request = route.request()
    const body = request.postDataJSON()
    safetySaves.push({ body, role: request.headers()['x-dev-role'], userId: request.headers()['x-dev-user-id'] })
    venue = {
      ...venue, ...body,
      safetyInfoUpdatedBy: users.venueStaff.user_id, safetyInfoUpdatedAt: '2026-10-26T10:30:00+08:00',
    }
    return json(route, { venue })
  })
  const safety = page.getByRole('region', { name: 'Safety information' })

  await test.step('AC2: a venue with nothing recorded reads "Not provided"', async () => {
    await page.goto(`/venues/${venue.id}`)
    await expect(safety.getByText('Not provided')).toHaveCount(2)
    await expect(safety.getByText(/Last updated/)).toHaveCount(0)
  })

  await test.step('AC1/AC3: Venue Staff enter both fields and save', async () => {
    await page.getByRole('button', { name: /Edit Venue/ }).click()
    await page.getByLabel('Emergency Access Details').fill(EMERGENCY)
    await page.getByLabel('Known Restrictions').fill(RESTRICTIONS)
    await page.getByRole('button', { name: 'Save Changes' }).click()

    await expect(safety.getByText(RESTRICTIONS)).toBeVisible()
    expect(safetySaves).toEqual([{
      body: { emergencyAccessDetails: EMERGENCY, knownRestrictions: RESTRICTIONS },
      role: 'Venue Staff',
      userId: users.venueStaff.user_id,
    }])
    await expect(safety.getByText(/Exits on north and south walls/)).toBeVisible()
    await expect(safety.getByText(/Last updated .*26 Oct 2026.* by Vera Koh/)).toBeVisible()
  })

  await test.step('AC4: an Event Coordinator sees the values but has no Edit Venue button', async () => {
    await page.getByLabel('Select active user').selectOption({ label: 'Carl Ng — Event Coordinator' })
    await expect(safety.getByText(RESTRICTIONS)).toBeVisible()
    await expect(page.getByRole('button', { name: /Edit Venue/ })).toHaveCount(0)
  })
})
