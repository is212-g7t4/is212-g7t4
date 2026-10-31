import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { deleteFixtureEvents } from '../../../helpers/cleanup'
import { openAs, users } from '../../../helpers/stack'
import { seedJ5b, TABLE_STOCK } from './helpers/seed'

/**
 * J5b — Prevent equipment over-allocation (High; brief demo, detailed cases at integration level)
 *
 * Requires the real stack (`npm run dev`) and the seeded database (6-foot folding table, stock 50).
 *
 * Journey ticket: SCRUM-259 (E2E Testing J5)
 *
 * Stories this journey exercises (a change to any of these can break it):
 *   - SCRUM-32  Create Event Equipment Request (coordinator "New request" form)
 *   - SCRUM-33  Equipment Request Review (Technical Support approve / reject, reason)
 *   - SCRUM-34  Equipment Availability Checking (remaining stock, Insufficient badge, approval disabled)
 *   - SCRUM-35  Equipment Reservation (approved quantity is deducted for overlapping events)
 *
 * Stories the fixture setup relies on:
 *   - SCRUM-31  Equipment Catalogue (seeded 6-foot folding table, stock 50)
 *   - SCRUM-11  Event Submission Form (event creation)
 *   - SCRUM-159 Assign Coordinator to an Event
 *   - SCRUM-19  Update Event Status (Under Review, required before equipment can be requested)
 *
 * Covers: equipment availability per overlapping window, Insufficient flag,
 * batch approval blocked, rejection with reason, valid lowered-quantity retry.
 */
test.describe.configure({ mode: 'serial' })

test.describe('J5b Prevent equipment over-allocation', () => {
  const runId = randomUUID()
  const eventA = `J5b Event A ${runId}`
  const eventB = `J5b Event B ${runId}`
  const scope = { eventNames: [eventA, eventB], venueNames: [] }

  test.beforeAll(async ({ playwright }) => {
    const api = await playwright.request.newContext()
    try {
      await seedJ5b(api, runId)
    } finally {
      await api.dispose()
    }
  })

  test.afterAll(async () => { await deleteFixtureEvents(scope) })

  test('over-allocated request is blocked, rejected, then revised and approved', async ({ browser }) => {
    const support = await openAs(browser, users.techSupport)
    const coordinator = await openAs(browser, users.coordinator)
    const cardB = support.getByRole('region', { name: `${eventB} equipment requests` })
    const tableRow = (status: string) => cardB.getByRole('row').filter({ hasText: '6-foot folding table' }).filter({ hasText: status })

    await test.step('Technical Support sees remaining stock and the Insufficient badge', async () => {
      await support.goto('/equipment-requests')
      await expect(cardB).toBeVisible()
      const pending = tableRow('Pending')
      await expect(pending).toContainText('Insufficient')
      await expect(pending).toContainText(String(TABLE_STOCK - 40))
    })

    await test.step('Approval is blocked for the line and for the whole batch', async () => {
      await expect(tableRow('Pending').getByRole('button', { name: 'Approve', exact: true })).toBeDisabled()
      await expect(support.getByRole('article').filter({ hasText: eventB }).getByRole('button', { name: 'Approve All' })).toBeDisabled()
    })

    await test.step('Technical Support rejects the request with a reason', async () => {
      await tableRow('Pending').getByRole('button', { name: 'Reject', exact: true }).click()
      const dialog = support.getByRole('dialog')
      await dialog.getByLabel('Reason for rejection').fill('Only 10 tables remain for this window.')
      await dialog.getByRole('button', { name: 'Confirm rejection' }).click()
      await expect(tableRow('Rejected')).toContainText('Only 10 tables remain')
    })

    await test.step('Coordinator submits a new request with a valid quantity (10)', async () => {
      await coordinator.goto('/equipment-requests/new')
      const eventOption = coordinator.locator('select option', { hasText: eventB }).first()
      await coordinator.getByLabel(/^Event/).selectOption(await eventOption.getAttribute('value') ?? '')
      const group = coordinator.getByRole('group', { name: 'Equipment row' })
      await group.getByLabel(/^Equipment/).selectOption({ label: '6-foot folding table (Table)' })
      await group.getByLabel(/^Quantity/).fill('10')
      await group.getByRole('button', { name: 'Add this equipment' }).click()
      await coordinator.getByRole('button', { name: 'Submit request' }).click()
      await expect(coordinator.getByText(`Requested 1 equipment item for ${eventB}.`)).toBeVisible()
    })

    await test.step('Technical Support approves the revised request', async () => {
      await support.getByRole('button', { name: 'Refresh requests' }).click()
      const revised = tableRow('Pending')
      await expect(revised).not.toContainText('Insufficient')
      await revised.getByRole('button', { name: 'Approve', exact: true }).click()
      await expect(tableRow('Approved')).toBeVisible()
    })
  })
})