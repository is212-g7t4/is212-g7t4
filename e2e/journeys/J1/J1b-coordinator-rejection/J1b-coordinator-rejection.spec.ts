import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { deleteFixtureEvents } from '../../../helpers/cleanup'
import { authHeaders, openAs, randomWindow, serviceUrl, users } from '../../../helpers/stack'

type Decision = { status: string; coordinatorId: string; reason: string | null; decidedAt: string }
type RecordedEvent = { status: string; decision: Decision | null; decisionHistory: Decision[]; actionHistory: { status: string }[] }

/**
 * J1 Path B — Coordinator rejects an assigned event.
 * Journey ticket: SCRUM-255.
 * Exercised stories: SCRUM-13, 19, 44–48, 166, 168 (provisional J1 keys;
 * exact rejection/notification attribution awaits confirmation).
 * Fixture dependencies: SCRUM-8 seeded accounts, SCRUM-11 event submission,
 * SCRUM-159 coordinator assignment.
 * Requires the real stack and local E2E credentials; no API responses are mocked.
 */
test.describe.configure({ mode: 'serial', timeout: 240_000 })

test.describe('J1b Coordinator rejects an assigned event', () => {
  const eventName = `J1b Event ${randomUUID()}`
  const scope = { eventNames: [eventName], venueNames: [] }
  const reason = 'The event proposal does not include a feasible programme or sufficient staffing.'
  let eventId: string

  test.beforeAll(async ({ request }) => {
    const window = randomWindow()
    const created = await request.post(serviceUrl('event', '/events'), {
      headers: await authHeaders(users.organiser),
      data: {
        eventName, description: 'J1 Path B rejection fixture.', purpose: 'Verify rejection visibility.',
        preferredStartDate: window.start, preferredEndDate: window.end, expectedAttendance: '50',
      },
    })
    expect(created.ok(), `Create event: ${created.status()} ${await created.text()}`).toBe(true)
    eventId = (await created.json() as { id: string }).id
    const assigned = await request.post(serviceUrl('assignment', `/events/${eventId}/assign-coordinator/${users.coordinator.id}`), {
      headers: await authHeaders(users.lead),
    })
    expect(assigned.ok(), `Assign coordinator: ${assigned.status()} ${await assigned.text()}`).toBe(true)
  })

  test.afterAll(async () => { await deleteFixtureEvents(scope) })

  test('rejection reason and notification reach the organiser, with no approval recorded', async ({ browser, request }) => {
    const coordinator = await openAs(browser, users.coordinator)
    const organiser = await openAs(browser, users.organiser)

    await test.step('1. Coordinator rejects the assigned event with a reason', async () => {
      await coordinator.goto('/requests/review')
      const card = coordinator.locator('article').filter({ has: coordinator.getByRole('heading', { name: eventName, exact: true }) })
      await expect(card).toHaveCount(1)
      await card.getByRole('button', { name: 'Reject Request', exact: true }).click()
      const dialog = coordinator.getByRole('dialog', { name: 'Reject event request?' })
      await expect(dialog.getByRole('button', { name: 'Confirm rejection' })).toBeDisabled()
      await dialog.getByLabel(/Reason for rejection/).fill(reason)
      await dialog.getByRole('button', { name: 'Confirm rejection' }).click()
      await expect(coordinator.getByRole('heading', { name: 'Event Request Rejected', exact: true })).toBeVisible()
      await expect(coordinator.getByRole('dialog')).toContainText(reason)
      await expect(card).toHaveCount(0)
    })

    await test.step('2. Organiser sees the persisted rejection, reason and rejection notification; no approval exists', async () => {
      await organiser.goto('/my-events')
      const card = organiser.getByRole('button').filter({ hasText: eventName })
      await expect(card).toContainText('Rejected')
      await card.click()
      await expect(organiser.locator('.event-card-header .status-badge').first()).toHaveText('Rejected')
      await expect(organiser.getByRole('heading', { name: 'Rejection reason', exact: true })).toBeVisible()
      await expect(organiser.getByText(reason, { exact: true })).toBeVisible()
      await organiser.reload()
      await expect(organiser.locator('.event-card-header .status-badge').first()).toHaveText('Rejected')
      await expect(organiser.getByText(reason, { exact: true })).toBeVisible()

      const response = await request.get(serviceUrl('event', `/events/${eventId}?organiserId=${users.organiser.id}`), {
        headers: await authHeaders(users.organiser),
      })
      expect(response.ok(), `Read decision: ${response.status()} ${await response.text()}`).toBe(true)
      const event = await response.json() as RecordedEvent
      expect(event.status).toBe('Rejected')
      expect(event.decision).toMatchObject({ status: 'Rejected', coordinatorId: users.coordinator.id, reason })
      expect(event.decision?.decidedAt).toBeTruthy()
      expect(event.decisionHistory).toHaveLength(1)
      expect(event.decisionHistory[0]).toMatchObject({ status: 'Rejected', reason })
      expect(event.actionHistory.filter((action) => action.status === 'Approved' || action.status === 'Confirmed')).toEqual([])

      await organiser.goto('/notifications')
      await expect(async () => {
        await organiser.getByRole('button', { name: 'Refresh notifications' }).click()
        const notification = organiser.locator('.notification-list li').filter({ hasText: eventName }).filter({ hasText: /reject/i })
        await expect(notification.first()).toBeVisible({ timeout: 2_000 })
        await expect(notification.first()).toContainText(reason)
      }).toPass({ timeout: 120_000, intervals: [1_000, 3_000, 5_000] })
    })
  })
})
