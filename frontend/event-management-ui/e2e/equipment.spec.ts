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
  expect(headers['x-dev-role']).toBe('Technical Support')
  expect(headers['x-dev-user-id']).toBe(users.techSupport.user_id)
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
  await expect(page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name: 'Equipment' })).toHaveCount(0)
  await expect(page.getByText('visible to Technical Support staff')).toBeVisible()
})
