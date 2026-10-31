import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { deleteFixtureEvents } from '../../../helpers/cleanup'
import { openAs, users } from '../../../helpers/stack'
import { seedJ6a } from './helpers/seed'

/**
 * J6a — Organiser requests a change before confirmation (High; brief demo,
 * detailed cases at integration level).
 *
 * Requires the real stack (`npm run dev`) and the seeded database.
 *
 * Journey ticket: SCRUM-260 (E2E Testing J6)
 *
 * Stories this journey exercises (a change to any of these can break it):
 *   - SCRUM-42  Event Organiser Change Request (proposed values and reason)
 *   - SCRUM-43  Event Coordinator Change Request Review (compare, approve, reject)
 *   - SCRUM-49  Event Decision Notifications (organiser receives the decision)
 *
 * Stories the fixture setup relies on:
 *   - SCRUM-11  Event Submission Form (event creation)
 *   - SCRUM-159 Assign Coordinator to an Event
 *   - SCRUM-19  Update Event Status (Under Review before a change is requested)
 *
 * Fixture data is created through service APIs; organiser and coordinator
 * actions, including checking the organiser's inbox, use the UI.
 */
test.describe.configure({ mode: 'serial', timeout: 360_000 })

test.describe('J6a Organiser requests a change', () => {
  const runId = randomUUID()
  const approvedName = `J6a Event approved proposal ${runId}`
  const rejectedName = `J6a Event rejected proposal ${runId}`
  const scope = {
    eventNames: [`J6a Event approve ${runId}`, `J6a Event reject ${runId}`, approvedName, rejectedName],
    venueNames: [],
  }
  let fixture: Awaited<ReturnType<typeof seedJ6a>>

  test.beforeAll(async ({ playwright }) => {
    const api = await playwright.request.newContext()
    try {
      fixture = await seedJ6a(api, runId)
    } finally {
      await api.dispose()
    }
  })

  test.afterAll(async () => { await deleteFixtureEvents(scope) })

  async function requestChange(organiser: import('@playwright/test').Page, name: string, proposedName: string) {
    await organiser.goto('/my-events')
    await organiser.getByRole('button', { name: new RegExp(name) }).click()
    await organiser.getByRole('button', { name: 'Request changes' }).click()
    const dialog = organiser.getByRole('dialog', { name: 'Request event changes' })
    await dialog.getByLabel('Event Name').fill(proposedName)
    await dialog.getByRole('textbox', { name: 'Reason or justification *' }).fill('Updated details for the event plan.')
    await dialog.getByRole('button', { name: 'Submit change request' }).click()
    await expect(organiser.getByRole('status')).toContainText('pending review')
    await expect(organiser.getByRole('heading', { name })).toBeVisible()
  }

  test('pending request leaves event unchanged; approval applies values and rejection preserves them with a reason', async ({ browser }) => {
    const organiser = await openAs(browser, users.organiser)
    const coordinator = await openAs(browser, users.coordinator)

    await test.step('Organiser requests a change and the submitted event remains unchanged', async () => {
      await requestChange(organiser, fixture.approveName, approvedName)
    })

    await test.step('Coordinator compares original and proposed values and approves', async () => {
      await coordinator.goto('/change-requests')
      const card = coordinator.locator('.change-request-card').filter({ hasText: fixture.approveName })
      await expect(card).toContainText('Updated details for the event plan.')
      await expect(card.getByRole('columnheader', { name: 'Original value' })).toBeVisible()
      await expect(card.getByRole('columnheader', { name: 'Proposed value' })).toBeVisible()
      await expect(card).toContainText(fixture.approveName)
      await expect(card).toContainText(approvedName)
      await card.getByRole('button', { name: 'Approve changes' }).click()
      await expect(coordinator.getByRole('status')).toContainText('change request approved')
    })

    await test.step('Organiser sees the approval notification and the approved event values', async () => {
      await organiser.goto('/notifications')
      await expect(async () => {
        await organiser.getByRole('button', { name: 'Refresh notifications' }).click()
        const approval = organiser.getByRole('listitem').filter({ hasText: approvedName })
          .filter({ hasText: 'was approved.' })
        await expect(approval).toHaveCount(1, { timeout: 2_000 })
      }).toPass({ timeout: 120_000, intervals: [1_000, 3_000, 5_000] })

      await organiser.goto('/my-events')
      await organiser.getByRole('button', { name: new RegExp(approvedName) }).click()
      await expect(organiser.getByRole('heading', { name: approvedName })).toBeVisible()
    })

    await test.step('Rejection records a reason, keeps the original event values, and notifies the organiser', async () => {
      await requestChange(organiser, fixture.rejectName, rejectedName)
      await coordinator.goto('/change-requests')
      const card = coordinator.locator('.change-request-card').filter({ hasText: fixture.rejectName })
      await card.getByRole('button', { name: 'Reject changes' }).click()
      const dialog = coordinator.getByRole('dialog', { name: 'Reject change request?' })
      await dialog.getByLabel('Reason for rejection').fill('The proposed title is not approved.')
      await dialog.getByRole('button', { name: 'Confirm rejection' }).click()
      await expect(coordinator.getByRole('status')).toContainText('change request rejected')
      await organiser.goto('/my-events')
      await organiser.getByRole('button', { name: new RegExp(fixture.rejectName) }).click()
      await expect(organiser.getByRole('heading', { name: fixture.rejectName })).toBeVisible()
      await expect(organiser.getByRole('heading', { name: rejectedName })).toHaveCount(0)
      await organiser.goto('/notifications')
      await expect(async () => {
        await organiser.getByRole('button', { name: 'Refresh notifications' }).click()
        const rejection = organiser.getByRole('listitem')
          .filter({ hasText: fixture.rejectName })
          .filter({ hasText: 'was rejected:' })
        await expect(rejection).toHaveCount(1, { timeout: 2_000 })
        await expect(rejection.getByText('The proposed title is not approved.', { exact: true })).toBeVisible({ timeout: 2_000 })
      }).toPass({ timeout: 120_000, intervals: [1_000, 3_000, 5_000] })
    })
  })
})
