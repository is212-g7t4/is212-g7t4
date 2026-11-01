import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { deleteFixtureEvents } from '../../../helpers/cleanup'
import { openAs, users } from '../../../helpers/stack'
import { createConfirmedEvent } from './helpers/seed'

/**
 * J6b — Coordinator edits a Confirmed event directly (High; brief demo,
 * detailed cases at integration level).
 *
 * Requires the real stack (`npm run dev`) and the seeded database.
 *
 * Journey ticket: SCRUM-260 (E2E Testing J6)
 *
 * Stories this journey exercises (a change to any of these can break it):
 *   - SCRUM-20  Event Details Editing (impact validation and arrangement conflicts)
 *   - SCRUM-153 Withdraw Safety Approval When Confirmed Event Details Change
 *
 * Stories the fixture setup relies on:
 *   - SCRUM-11  Event Submission Form (event creation)
 *   - SCRUM-159 Assign Coordinator to an Event
 *   - SCRUM-19  Update Event Status
 *   - SCRUM-28/29 Venue Booking Request and Review (approved venue arrangement)
 *   - SCRUM-149/150 Safety Review and Approval (Confirmed event with approval history)
 *
 * J1 covers the Safety Officer's reapproval decision after this journey returns
 * the event to the safety queue. Fixture data is created through service APIs.
 */
test.describe.configure({ mode: 'serial' })

test.describe('J6b Coordinator edits a Confirmed event', () => {
  const runId = randomUUID()
  const eventName = `J6b Event confirmed ${runId}`
  const scope = { eventNames: [eventName], venueNames: [] }
  let fixture: Awaited<ReturnType<typeof createConfirmedEvent>>

  test.beforeAll(async ({ playwright }) => {
    const api = await playwright.request.newContext()
    try {
      fixture = await createConfirmedEvent(api, eventName, runId)
    } finally {
      await api.dispose()
    }
  })

  test.afterAll(async () => { await deleteFixtureEvents(scope) })

  test('low-impact edit stays Confirmed; contradiction is blocked; safe high-impact edit enters safety review', async ({ browser }) => {
    const coordinator = await openAs(browser, users.coordinator)
    const officer = await openAs(browser, users.safetyOfficer)
    const coordinatorEvent = `/events/${fixture.eventId}`

    await test.step('A low-impact edit saves without changing Confirmed status', async () => {
      await coordinator.goto(coordinatorEvent)
      await coordinator.getByRole('button', { name: 'Edit details' }).click()
      const editor = coordinator.getByRole('dialog', { name: 'Edit event details' })
      await editor.getByLabel('Description *').fill('Low-impact J6 description update.')
      await editor.getByRole('button', { name: 'Save details' }).click()
      await expect(coordinator.getByText('Event details saved.', { exact: true })).toBeVisible()
      await expect(coordinator.locator('.status-badge.confirmed')).toBeVisible()
    })

    await test.step('An attendance increase beyond venue capacity is blocked without changing the event', async () => {
      await coordinator.getByRole('button', { name: 'Edit details' }).click()
      const editor = coordinator.getByRole('dialog', { name: 'Edit event details' })
      await editor.getByLabel('Expected Attendance *').fill('501')
      await editor.getByRole('button', { name: 'Save details' }).click()
      await expect(editor.getByRole('alert')).toContainText('contradicts arrangements already made')
      await expect(editor.getByRole('alert')).toContainText('holds up to 500 people')
      await expect(coordinator.locator('.status-badge.confirmed')).toBeVisible()
      await coordinator.reload()
      await expect(coordinator.getByText('Expected attendance').locator('..')).toContainText('50')
      await coordinator.getByRole('button', { name: 'Edit details' }).click()
    })

    await test.step('A non-conflicting date change withdraws the earlier safety approval', async () => {
      await coordinator.getByLabel('Preferred End Date & Time *').fill(`${fixture.window.end.slice(0, 10)}T18:00`)
      await coordinator.getByRole('button', { name: 'Save details' }).click()
      const confirm = coordinator.getByRole('dialog', { name: 'Withdraw safety approval?' })
      await expect(confirm).toBeVisible()
      await confirm.getByRole('button', { name: 'Save and withdraw approval' }).click()
      await expect(coordinator.getByText(/Saved\. Safety approval withdrawn because/)).toContainText('back to Pending Safety Check')
      await expect(coordinator.locator('.status-badge.pending-safety-check')).toBeVisible()
      await expect(coordinator.getByText('Safety approval withdrawn', { exact: true })).toBeVisible()
    })

    await test.step('Safety Officer sees the event queued and the prior decision retained in history', async () => {
      await officer.goto('/safety-checks')
      const eventRow = officer.getByRole('button', { name: new RegExp(eventName) })
      await expect(eventRow).toBeVisible()
      await eventRow.click()
      await expect(officer.getByRole('heading', { name: 'Safety review information' })).toBeVisible()
      await expect(officer.getByRole('heading', { name: 'Round 1 · Approval Withdrawn' })).toBeVisible()
      // The review shows the withdrawal reason in place of the original approval remarks.
      await expect(officer.getByText('Date/time changed')).toBeVisible()
    })
  })
})
