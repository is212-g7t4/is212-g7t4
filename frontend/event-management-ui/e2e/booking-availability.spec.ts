import { allUsers, asUser, json, makeEvent, mock, test, expect, users, venues } from './fixtures'
import type { Page } from '@playwright/test'

async function openForm(page: Page, mockApi: (page: Page) => Promise<void>) {
  const event = makeEvent()
  await mockApi(page)
  await asUser(page, users.coordinator.user_id)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await mock(page, 'event', '/events', (route) => json(route, { events: [event] }))
  await mock(page, 'event', `/events/${event.id}`, (route) => json(route, event))
  await mock(page, 'venue', '/venues', (route) => json(route, { venues }))
  await mock(page, 'venueBooking', `/events/${event.id}/booking-requests`, (route) => json(route, { bookings: [] }))
  await page.goto('/my-events')
  await page.getByRole('button', { name: /Tech Conference/ }).click()
  await page.getByLabel(/Venue \*/).selectOption(venues[0].id)
  await page.getByLabel('Expected attendance / required capacity *').fill('10')
  await page.getByLabel('Venue requirements').fill('Retained draft')
}

// Mocked HTTP contract/UI evidence only; these tests cannot prove database rollback.
for (const [name, types, messages] of [
  ['approved', ['APPROVED_BOOKING'], ['An approved booking overlaps this time.']],
  ['hold', ['TENTATIVE_HOLD'], ['An active tentative hold overlaps this time.']],
  ['closure', ['VENUE_CLOSURE'], ['The venue is closed during this time.']],
  ['multiple', ['APPROVED_BOOKING', 'TENTATIVE_HOLD', 'VENUE_CLOSURE'], ['An approved booking overlaps this time.', 'An active tentative hold overlaps this time.', 'The venue is closed during this time.']],
] as const) {
  test(`SCRUM-30 mocked ${name} conflict retains draft, adds no UI record, then retries as Pending Review`, async ({ page, mockApi }, testInfo) => {
    await openForm(page, mockApi)
    let attempts = 0
    const mockSaved: unknown[] = []
    await mock(page, 'venueBooking', '/booking-requests', (route) => {
      attempts++
      if (attempts === 1) return json(route, { code: 'VENUE_UNAVAILABLE', conflictTypes: types, message: 'Unavailable' }, 409)
      const saved = { ...route.request().postDataJSON(), id: 'new', status: 'Pending Review', requestedBy: users.coordinator.user_id, reviewedBy: null }
      mockSaved.push(saved)
      return json(route, saved, 201)
    })
    await page.getByRole('button', { name: 'Submit venue booking' }).click()
    const alert = page.getByRole('alert')
    await expect(alert).toContainText('Request not submitted.')
    for (const message of messages) await expect(alert).toContainText(message)
    await expect(page.getByLabel(/Venue \*/)).toHaveValue(venues[0].id)
    await expect(page.getByLabel('Venue requirements')).toHaveValue('Retained draft')
    await expect(page.getByLabel('Booking start *')).toHaveValue('2026-12-01T09:00')
    await expect(page.getByLabel('Booking end *')).toHaveValue('2026-12-01T17:00')
    await expect(page.getByText('No venue booking requests yet.')).toBeVisible()
    expect(attempts).toBe(1)
    expect(mockSaved).toHaveLength(0)
    if (name === 'multiple') {
      await page.screenshot({ path: testInfo.outputPath('conflict-desktop.png'), fullPage: true })
      await page.setViewportSize({ width: 390, height: 844 })
      await expect(alert).toBeVisible()
      await page.screenshot({ path: testInfo.outputPath('conflict-mobile.png'), fullPage: true })
    }
    await page.getByLabel('Booking start *').fill('2026-12-01T08:00')
    await expect(alert).toHaveCount(0)
    await page.getByRole('button', { name: 'Submit venue booking' }).click()
    await expect(page.getByRole('status')).toContainText('Status: Pending Review.')
    await expect(page.getByText('Pending Review', { exact: true })).toBeVisible()
    expect(attempts).toBe(2)
    expect(mockSaved).toHaveLength(1)
  })
}

test('SCRUM-30 mocked pending request blocks duplicates; network loss never claims not submitted', async ({ page, mockApi }) => {
  await openForm(page, mockApi)
  let release!: () => void
  const held = new Promise<void>((resolve) => { release = resolve })
  let attempts = 0
  await mock(page, 'venueBooking', '/booking-requests', async (route) => {
    attempts++
    await held
    await route.abort('failed')
  })
  await page.getByRole('button', { name: 'Submit venue booking' }).click()
  await expect(page.getByRole('button', { name: 'Saving…' })).toBeDisabled()
  await page.locator('.venue-booking-form').evaluate((form) => (form as HTMLFormElement).requestSubmit())
  expect(attempts).toBe(1)
  release()
  await expect(page.getByRole('alert')).toContainText('Unable to confirm whether the booking request was saved.')
  await expect(page.getByRole('alert')).not.toContainText('Request not submitted')
  await expect(page.getByLabel('Venue requirements')).toHaveValue('Retained draft')
  expect(attempts).toBe(1)
})

test('SCRUM-30 mocked legacy and service failures remain failures, not availability results', async ({ page, mockApi }) => {
  await openForm(page, mockApi)
  for (const [status, message] of [[409, 'Legacy conflict'], [503, 'Service unavailable']] as const) {
    await mock(page, 'venueBooking', '/booking-requests', (route) => json(route, { message }, status))
    await page.getByRole('button', { name: 'Submit venue booking' }).click()
    await expect(page.getByRole('alert')).toHaveText(message)
    await expect(page.getByText('No venue booking requests yet.')).toBeVisible()
  }
})
