import { allUsers, asUser, json, mock, test, expect, users } from './fixtures'

const item = (overrides: Record<string, unknown> = {}) => ({
  id: 'eq-1', type: 'Projector', description: '4K laser projector', totalQuantity: 5, location: 'Tech Store',
  status: 'Available', setupRequirements: 'Mount and connect HDMI.', ...overrides,
})

test.beforeEach(async ({ page, mockApi }) => {
  await mockApi(page)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
})

test('technical support lists available equipment and filters by status', async ({ page }) => {
  const statuses: (string | null)[] = []
  await asUser(page, users.techSupport.user_id)
  await mock(page, 'equipment', '/equipment', (route) => {
    const status = new URL(route.request().url()).searchParams.get('status')
    statuses.push(status)
    return json(route, { equipment: status === 'Available' ? [item()] : [item(), item({ id: 'eq-2', type: 'Chair', description: 'Banquet chair', status: 'Unavailable' })] })
  })
  await page.goto('/equipment')

  await expect(page.getByRole('table')).toContainText('4K laser projector')
  await expect(page.getByRole('table')).not.toContainText('Banquet chair')
  expect(statuses[0]).toBe('Available')

  await page.getByLabel('Filter by status').selectOption('All')
  await expect(page.getByRole('table')).toContainText('Banquet chair')
  expect(statuses.at(-1)).toBeNull()
})

test('technical support adds equipment and the list refreshes', async ({ page }) => {
  let created: Record<string, unknown> | null = null
  let headers: Record<string, string> = {}
  await asUser(page, users.techSupport.user_id)
  await mock(page, 'equipment', '/equipment', async (route) => {
    if (route.request().method() === 'POST') {
      created = route.request().postDataJSON()
      headers = route.request().headers()
      return json(route, { equipment: item({ id: 'eq-3', type: 'Laptop', description: 'Presentation laptop' }) }, 201)
    }
    return json(route, { equipment: created ? [item({ id: 'eq-3', type: 'Laptop', description: 'Presentation laptop' })] : [] })
  })
  await page.goto('/equipment')
  await expect(page.getByText('No equipment found.')).toBeVisible()

  const form = page.getByRole('form', { name: 'Add equipment' })
  await form.getByLabel('Type').selectOption('Laptop')
  await form.getByLabel('Description').fill('Presentation laptop')
  await form.getByLabel('Total quantity').fill('8')
  await form.getByLabel('Location').fill('Tech Store')
  await form.getByRole('button', { name: 'Add equipment' }).click()

  await expect(page.getByRole('status').filter({ hasText: 'Added Laptop' })).toBeVisible()
  await expect(page.getByRole('table')).toContainText('Presentation laptop')
  expect(created).toEqual({ equipmentType: 'Laptop', description: 'Presentation laptop', totalQuantity: 8, location: 'Tech Store', status: 'Available' })
  expect(headers['authorization']).toBe(`Bearer e2e-${users.techSupport.user_id}`)
})

test('technical support adds a type that is not in the list', async ({ page }) => {
  let created: Record<string, unknown> | null = null
  await asUser(page, users.techSupport.user_id)
  await mock(page, 'equipment', '/equipment', (route) => {
    if (route.request().method() === 'POST') {
      created = route.request().postDataJSON()
      return json(route, { equipment: item({ id: 'eq-9', type: 'Drone', description: 'Camera drone' }) }, 201)
    }
    return json(route, { equipment: [] })
  })
  await page.goto('/equipment')
  const form = page.getByRole('form', { name: 'Add equipment' })
  await form.getByLabel(/^Type/).selectOption('Add new…')
  await form.getByLabel('New equipment type').fill('Drone')
  await form.getByLabel('Description').fill('Camera drone')
  await form.getByLabel('Total quantity').fill('2')
  await form.getByLabel('Location').fill('Tech Store')
  await form.getByRole('button', { name: 'Add equipment' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Added Drone' })).toBeVisible()
  expect(created).toMatchObject({ equipmentType: 'Drone' })
})

test('invalid quantity is rejected before any request is sent', async ({ page }) => {
  await asUser(page, users.techSupport.user_id)
  await mock(page, 'equipment', '/equipment', (route) => {
    if (route.request().method() === 'POST') throw new Error('POST must not be sent')
    return json(route, { equipment: [] })
  })
  await page.goto('/equipment')
  const form = page.getByRole('form', { name: 'Add equipment' })
  await form.getByLabel('Description').fill('Thing')
  await form.getByLabel('Location').fill('Store')
  await form.getByLabel('Total quantity').fill('-2')
  await form.getByRole('button', { name: 'Add equipment' }).click()
  await expect(form.getByRole('alert')).toContainText('whole number')
})

test('other roles do not get the equipment page or nav item', async ({ page }) => {
  await asUser(page, users.coordinator.user_id)
  await mock(page, 'venue', '/venues', (route) => json(route, { venues: [] }))
  await page.goto('/equipment')
  await expect(page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name: 'Equipment', exact: true })).toHaveCount(0)
  await expect(page.getByText('visible to Technical Support staff')).toBeVisible()
})

// Safety revision AC3/AC4 (mocked browser): staff can re-review a flagged Pending request;
// the unaffected Approved line stays reviewed and has no decision controls.
// Review AC2/AC3: rejection requires a reason, which is returned and shown with the updated request.
for (const decision of ['Approved', 'Rejected'] as const) {
  test(`technical support can mark safety-flagged equipment ${decision}`, async ({ page }, testInfo) => {
    await page.setViewportSize(decision === 'Approved' ? { width: 1440, height: 1000 } : { width: 390, height: 844 })
    await asUser(page, users.techSupport.user_id)
    let status = 'Pending'
    const reason = 'Projector cables cannot be safely rerouted.'
    const flagged = () => ({
      id: 'flagged-request', eventId: 'fair', equipmentId: 'projector', quantityRequested: 1,
      technicalRequirements: 'Keep the accessible route clear.', status, reviewedBy: null,
      rejectionReason: status === 'Rejected' ? reason : null,
      equipment: { description: 'Flagged projector', type: 'Projector', status: 'Available' },
      availability: { reservedQuantity: 0, availableStock: 5, isInsufficient: false },
      safetyFeedback: { reason: 'Trip hazards affect the accessible route.', requestedChanges: ['Move projector cables away from the walkway.'] },
    })
    await mock(page, 'equipmentReservation', '/equipment-reservations', (route) => json(route, { events: [{
      eventId: 'fair', eventName: 'Community Wellbeing Fair', eventStatus: 'Safety Changes Requested',
      startTime: '2026-11-07T10:00:00', endTime: '2026-11-07T16:00:00', coordinatorId: users.coordinator.user_id,
      requests: [flagged(), { ...flagged(), id: 'unaffected-request', equipmentId: 'chairs', status: 'Approved',
        equipment: { description: 'Unaffected chairs', type: 'Chair', status: 'Available' }, availability: null, safetyFeedback: null }],
    }] }))
    await mock(page, 'equipmentReservation', '/equipment-reservations/requests/flagged-request', (route) => {
      expect(route.request().postDataJSON()).toEqual({
        status: decision, ...(decision === 'Rejected' ? { rejectionReason: reason } : {}),
      })
      status = decision
      return json(route, { request: { ...flagged(), reviewedBy: users.techSupport.user_id } })
    })
    await page.goto('/equipment-requests')
    const flaggedRow = page.getByRole('row').filter({ hasText: 'Flagged projector' })
    const unaffectedRow = page.getByRole('row').filter({ hasText: 'Unaffected chairs' })
    await expect(flaggedRow.getByRole('button', { name: 'Approve', exact: true })).toBeVisible()
    await expect(flaggedRow.getByRole('button', { name: 'Reject', exact: true })).toBeVisible()
    await expect(unaffectedRow.getByRole('button')).toHaveCount(0)
    await expect(page.getByRole('columnheader').last()).toHaveText('Safety change reason')
    await expect(flaggedRow.getByRole('cell').last()).toContainText('Move projector cables away from the walkway.')
    await expect(flaggedRow.getByRole('cell').last()).toContainText('Reason: Trip hazards affect the accessible route.')
    await expect(unaffectedRow.getByRole('cell').last()).toHaveText('Not flagged')
    const scrollRegion = page.getByRole('region', { name: 'Community Wellbeing Fair equipment requests' })
    expect(await scrollRegion.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true)
    await scrollRegion.evaluate((element) => { element.scrollLeft = element.scrollWidth })
    expect(await scrollRegion.evaluate((element) => element.scrollLeft > 0)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`equipment-safety-review-${decision}.png`), fullPage: true })
    await flaggedRow.getByRole('button', { name: decision === 'Approved' ? 'Approve' : 'Reject', exact: true }).click()
    if (decision === 'Rejected') {
      const dialog = page.getByRole('dialog', { name: 'Reject equipment request?' })
      await expect(dialog.getByRole('button', { name: 'Confirm rejection' })).toBeDisabled()
      await dialog.getByRole('textbox', { name: /Reason for rejection/ }).fill(reason)
      await dialog.getByRole('button', { name: 'Confirm rejection' }).click()
      await expect(dialog).not.toBeVisible()
      await expect(page.getByRole('columnheader', { name: 'Reject Reason' })).toBeVisible()
      await expect(flaggedRow.getByRole('cell', { name: reason, exact: true })).toBeVisible()
    }
    await expect(flaggedRow.locator('.status-badge')).toHaveText(decision)
    await expect(unaffectedRow.locator('.status-badge')).toHaveText('Approved')
    await expect(flaggedRow.getByRole('cell').last()).toContainText('Move projector cables away from the walkway.')
  })
}
