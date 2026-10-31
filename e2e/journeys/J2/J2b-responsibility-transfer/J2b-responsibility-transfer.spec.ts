import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { deleteFixtureEvents } from '../../../helpers/cleanup'
import { authHeaders, openAs, randomWindow, serviceUrl, users } from '../../../helpers/stack'
import { createJ2Event } from '../helpers/seed'

/**
 * J2B — Reassign an event and transfer its management rights.
 *
 * Requires the real stack (`npm run dev`), the seeded Supabase accounts and
 * `E2E_PASSWORD` (or per-role password variables) set.
 *
 * Journey ticket: SCRUM-256 (E2E Testing J2).
 *
 * Stories this journey exercises:
 *   - SCRUM-8   User Authentication and Authorization
 *   - SCRUM-9   Role-Based Access Control for Events
 *   - SCRUM-10  Role-Based Modification Control for Events
 *   - SCRUM-159 Assign Coordinator to an Event
 *   - SCRUM-160 Reassign an Event
 *   - SCRUM-166 Receive assignment notifications
 *
 * Stories the fixture setup relies on:
 *   - SCRUM-8   seeded user accounts for role-based sign-in
 *   - SCRUM-11  Event Submission Form (event creation through the service API)
 */
test.describe.configure({ mode: 'serial', timeout: 360_000 })

test.describe('J2B responsibility transfers to the newly assigned Coordinator', () => {
  const runId = randomUUID()
  const eventName = `J2b Event ${runId}`
  const scope = { eventNames: [eventName], venueNames: [] }
  const window = randomWindow()
  let eventId = ''
  let canCleanup = false

  test.beforeAll(async ({ playwright }) => {
    await deleteFixtureEvents(scope)
    canCleanup = true
    const api = await playwright.request.newContext()
    try {
      eventId = await createJ2Event(api, eventName, window)
    } finally {
      await api.dispose()
    }
  })

  test.afterAll(async () => {
    if (canCleanup) await deleteFixtureEvents(scope)
  })

  test('Lead assigns Coordinator A, reassigns to B, and only B retains management access', async ({ browser, request }) => {
    const lead = await openAs(browser, users.lead)
    const coordinatorA = await openAs(browser, users.coordinator)
    const coordinatorB = await openAs(browser, users.coordinatorB)

    await test.step('The Lead assigns the submitted event to Coordinator A, who manages it', async () => {
      await lead.goto('/requests/queue')
      const row = lead.getByRole('row').filter({ hasText: eventName })
      await expect(row).toContainText('Unassigned')
      await row.getByRole('combobox').selectOption(users.coordinator.id)
      await row.getByRole('button', { name: 'Assign', exact: true }).click()
      await expect(row).toContainText('Assigned')

      await coordinatorA.goto(`/events/${eventId}`)
      await expect(coordinatorA.getByRole('heading', { name: eventName })).toBeVisible()
      await coordinatorA.getByLabel('Action details').fill('Coordinator A started the event review.')
      await coordinatorA.getByRole('button', { name: 'Save progress' }).click()
      await expect(coordinatorA.getByText('Event progress updated successfully.')).toBeVisible()
      await expect(coordinatorA.locator('.event-card-header .status-badge').first()).toHaveText('Under Review')
    })

    await test.step('The Lead reassigns the event to Coordinator B and the transfer is recorded', async () => {
      await lead.goto(`/events/${eventId}`)
      await expect(lead.getByRole('heading', { name: eventName })).toBeVisible()
      await lead.getByRole('button', { name: 'Reassign Coordinator' }).click()
      await lead.getByLabel('New coordinator').selectOption(users.coordinatorB.id)
      await lead.getByRole('button', { name: 'Confirm Reassignment' }).click()

      const assignmentHistory = lead.locator('.event-footnote')
      await expect(assignmentHistory).toContainText('Reassigned from Marcus Lim to Priya Nair by Alice Tan')
      await expect(assignmentHistory).toContainText('on')

      const current = await request.get(
        serviceUrl('event', `/events/${eventId}?coordinatorId=${users.coordinatorB.id}`),
        { headers: await authHeaders(users.coordinatorB) },
      )
      expect(current.status()).toBe(200)
      const assigned = await current.json()
      expect(assigned).toMatchObject({
        coordinatorId: users.coordinatorB.id,
        previousCoordinatorId: users.coordinator.id,
        assignedBy: users.lead.id,
      })
      expect(assigned.assignedAt).toBeTruthy()
    })

    await test.step('Coordinator B manages the event after the handover', async () => {
      await coordinatorB.goto(`/events/${eventId}`)
      await expect(coordinatorB.getByRole('heading', { name: eventName })).toBeVisible()
      await coordinatorB.getByLabel('Status').selectOption('Approved')
      await coordinatorB.getByLabel('Action details').fill('Coordinator B completed the event review.')
      await coordinatorB.getByRole('button', { name: 'Save progress' }).click()
      await expect(coordinatorB.getByText('Event progress updated successfully.')).toBeVisible()
      await expect(coordinatorB.locator('.event-card-header .status-badge').first()).toHaveText('Approved')
    })

    await test.step('Coordinator A cannot save from the stale page or reopen the old link', async () => {
      await coordinatorA.getByLabel('Status').selectOption('Approved')
      await coordinatorA.getByLabel('Action details').fill('Stale Coordinator A change attempt.')
      await coordinatorA.getByRole('button', { name: 'Save progress' }).click()
      await expect(coordinatorA.getByRole('alert')).toContainText('not assigned to the current coordinator')

      const staleWrite = await request.patch(serviceUrl('event', `/events/${eventId}/progress`), {
        headers: await authHeaders(users.coordinator),
        data: { status: 'Approved', actionDetails: 'Direct stale Coordinator A change attempt.' },
      })
      expect(staleWrite.status()).toBe(403)
      expect(await staleWrite.text()).not.toContain('Direct stale Coordinator A change attempt.')

      await coordinatorA.goto(`/events/${eventId}`)
      await expect(coordinatorA.getByRole('alert')).toContainText('You no longer have access to this event')
      await expect(coordinatorA.getByRole('heading', { name: eventName })).toHaveCount(0)

      const afterRefusal = await request.get(
        serviceUrl('event', `/events/${eventId}?coordinatorId=${users.coordinatorB.id}`),
        { headers: await authHeaders(users.coordinatorB) },
      )
      expect(afterRefusal.status()).toBe(200)
      expect(await afterRefusal.json()).toMatchObject({
        coordinatorId: users.coordinatorB.id,
        status: 'Approved',
        actionDetails: 'Coordinator B completed the event review.',
      })
    })

    await test.step('Coordinator B receives the assignment notification and A receives the removal notification', async () => {
      const assigned = coordinatorB.getByRole('listitem')
        .filter({ hasText: eventName })
        .filter({ hasText: 'You have been assigned to' })
      await coordinatorB.goto('/notifications')
      await expect(async () => {
        await coordinatorB.getByRole('button', { name: 'Refresh notifications' }).click()
        await expect(assigned).toHaveCount(1, { timeout: 2_000 })
      }).toPass({ timeout: 120_000, intervals: [1_000, 3_000, 5_000] })
      await expect(assigned).toContainText('Event Organiser: Michael Lee.')
      await expect(assigned).toContainText(/Proposed: .+SGT/)
      await expect(assigned.getByRole('link', { name: 'Open notification' }))
        .toHaveAttribute('href', `/events/${eventId}`)

      const removed = coordinatorA.getByRole('listitem')
        .filter({ hasText: eventName })
        .filter({ hasText: 'You are no longer assigned to' })
      await coordinatorA.goto('/notifications')
      await expect(async () => {
        await coordinatorA.getByRole('button', { name: 'Refresh notifications' }).click()
        await expect(removed).toHaveCount(1, { timeout: 2_000 })
      }).toPass({ timeout: 120_000, intervals: [1_000, 3_000, 5_000] })
      await expect(removed).toContainText('Event Organiser: Michael Lee.')
      await expect(removed).toContainText(/Proposed: .+SGT/)
      await expect(removed.getByRole('link', { name: 'Open notification' })).toHaveCount(0)
    })
  })
})
