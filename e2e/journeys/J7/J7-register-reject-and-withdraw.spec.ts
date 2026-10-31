import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import type { Page } from '@playwright/test'
import { deleteFixtureEvents } from '../../helpers/cleanup'
import { authHeaders, openAs, serviceUrl, users } from '../../helpers/stack'
import { seedJ7 } from './helpers/seed'

/**
 * J7 — Register, reject invalid repeat registration, and withdraw.
 *
 * Requires the real stack (`npm run dev`) and seeded Supabase accounts.
 *
 * Journey ticket: SCRUM-261 (E2E Testing J7).
 * Stories this journey exercises: SCRUM-44–48; SCRUM-46 attendee notifications.
 * Stories the fixture setup relies on: SCRUM-8 seeded role accounts, SCRUM-11 event submission,
 * SCRUM-19 event progress, SCRUM-28/29 venue booking and review, SCRUM-149/150 safety review.
 *
 * Fixture data is created through service APIs. The past Confirmed event used for the closed
 * case is read-only seeded data; the browse page intentionally excludes events that have started.
 */
test.describe.configure({ mode: 'serial', timeout: 360_000 })

test.describe('J7 Register, reject invalid repeat registration, and withdraw', () => {
  const runId = randomUUID()
  const eventNames = [
    `J7 Event register and withdraw ${runId}`,
    `J7 Event duplicate ${runId}`,
    `J7 Event full ${runId}`,
    `J7 Event deadline ${runId}`,
    `J7 Event not confirmed ${runId}`,
  ]
  const scope = { eventNames, venueNames: [] }
  let fixture: Awaited<ReturnType<typeof seedJ7>>
  let canCleanup = false

  test.beforeAll(async ({ playwright }) => {
    canCleanup = true
    const api = await playwright.request.newContext()
    try {
      fixture = await seedJ7(api, runId)
    } finally {
      await api.dispose()
    }
  })

  test.afterAll(async () => { if (canCleanup) await deleteFixtureEvents(scope) })

  async function registerThroughBrowse(page: Page, eventName: string) {
    await page.goto('/events/browse')
    const card = page.getByRole('button').filter({ hasText: eventName })
    await expect(card).toHaveCount(1)
    await card.click()
    await page.getByRole('button', { name: 'Register', exact: true }).click()
    await page.getByRole('button', { name: 'Submit registration' }).click()
  }

  async function expectNotification(page: Page, eventName: string, message: RegExp) {
    await page.goto('/notifications')
    const refresh = page.getByRole('button', { name: 'Refresh notifications' })
    await expect(async () => {
      await refresh.click()
      const item = page.locator('.notification-list li')
        .filter({ hasText: eventName }).filter({ hasText: message })
      await expect(item.first()).toBeVisible({ timeout: 2_000 })
    }).toPass({ timeout: 120_000, intervals: [1_000, 3_000, 5_000] })
  }

  async function expectStaffRegistration(
    page: Page,
    eventId: string,
    email: string,
    status: string,
    total: number,
  ) {
    await page.goto(`/events/${eventId}`)
    await expect(page.locator('.event-detail').filter({ hasText: 'Total registrations' }).locator('dd')).toHaveText(String(total))
    await expect(page.getByRole('row').filter({ hasText: email })).toContainText(status)
  }

  test('keeps attendee and staff registration state aligned and refuses invalid registration and withdrawal', async ({ browser, request }) => {
    const attendee = await openAs(browser, users.attendee)
    const otherAttendee = await openAs(browser, users.attendeeTwo)
    const organiser = await openAs(browser, users.organiser)
    const coordinator = await openAs(browser, users.coordinator)

    await test.step('Path A: Attendee registers and sees the persisted registration', async () => {
      await registerThroughBrowse(attendee, fixture.main.eventName)
      await expect(attendee.getByRole('status')).toContainText(/registration confirmed/i)
      await attendee.goto('/registrations')
      await attendee.reload()
      const registration = attendee.getByRole('button').filter({ hasText: fixture.main.eventName })
      await expect(registration).toHaveCount(1)
      await expect(registration).toContainText('Confirmed')
      await registration.click()
      await expect(attendee.locator('.event-detail').filter({ hasText: 'Email' })).toContainText(users.attendee.email)
    })

    await test.step('Coordinator and Organiser see the same attendee and total', async () => {
      await expectStaffRegistration(coordinator, fixture.main.eventId, users.attendee.email, 'Confirmed', 1)
      await expectStaffRegistration(organiser, fixture.main.eventId, users.attendee.email, 'Confirmed', 1)
    })

    await test.step('Attendee withdraws before the deadline and the status persists', async () => {
      await attendee.goto('/registrations')
      const registration = attendee.getByRole('button').filter({ hasText: fixture.main.eventName })
      await registration.click()
      await attendee.getByRole('button', { name: 'Withdraw registration' }).click()
      const confirmation = attendee.getByRole('dialog', { name: 'Confirm withdrawal' })
      await confirmation.getByRole('button', { name: 'Confirm withdrawal' }).click()
      await expect(attendee.getByRole('status')).toContainText(/registration withdrawn/i)
      await expect(attendee.locator('.event-card-header .status-badge')).toHaveText('Withdrawn')
      await attendee.goto('/registrations')
      await attendee.reload()
      const persisted = attendee.getByRole('button').filter({ hasText: fixture.main.eventName })
      await expect(persisted).toContainText('Withdrawn')
    })

    await test.step('Staff see the withdrawal and zero active places; the attendee receives a notification', async () => {
      await expectStaffRegistration(coordinator, fixture.main.eventId, users.attendee.email, 'Withdrawn', 1)
      await expectStaffRegistration(organiser, fixture.main.eventId, users.attendee.email, 'Withdrawn', 1)
      await expectNotification(attendee, fixture.main.eventName, /withdraw/i)
    })

    await test.step('A second Attendee takes the place released by withdrawal', async () => {
      await registerThroughBrowse(otherAttendee, fixture.main.eventName)
      await expect(otherAttendee.getByRole('status')).toContainText(/registration confirmed/i)
      await expect(otherAttendee.locator('.event-facts')).toContainText('1 / 1')
      await expectStaffRegistration(coordinator, fixture.main.eventId, users.attendeeTwo.email, 'Confirmed', 2)
      await expectStaffRegistration(organiser, fixture.main.eventId, users.attendeeTwo.email, 'Confirmed', 2)
      await expect(coordinator.getByRole('row').filter({ hasText: users.attendee.email })).toContainText('Withdrawn')
      await expect(organiser.getByRole('row').filter({ hasText: users.attendee.email })).toContainText('Withdrawn')
    })

    await test.step('Path B: A repeat registration with the same account email is refused without a second row', async () => {
      await registerThroughBrowse(attendee, fixture.duplicate.eventName)
      await expect(attendee.getByRole('status')).toContainText(/registration confirmed/i)
      await registerThroughBrowse(attendee, fixture.duplicate.eventName)
      await expect(attendee.getByRole('alert')).toContainText('You are already registered for this event.')
      await attendee.goto('/registrations')
      await expect(attendee.getByRole('button').filter({ hasText: fixture.duplicate.eventName })).toHaveCount(1)
      await expectStaffRegistration(coordinator, fixture.duplicate.eventId, users.attendee.email, 'Confirmed', 1)
    })

    await test.step('Full, closed, and not-Confirmed events reject registration with clear reasons', async () => {
      await attendee.goto('/events/browse')
      const fullCard = attendee.getByRole('button').filter({ hasText: fixture.full.eventName })
      await expect(fullCard).toContainText('Full')
      await fullCard.click()
      await expect(attendee.getByRole('alert')).toContainText('This event has reached maximum capacity.')
      const fullAttempt = await request.post(serviceUrl('attendeeRegistration', '/registrations'), {
        headers: await authHeaders(users.attendee), data: { eventId: fixture.full.eventId },
      })
      expect(fullAttempt.status()).toBe(409)
      expect(await fullAttempt.json()).toMatchObject({
        code: 'EVENT_FULL', message: 'This event has reached maximum capacity.',
      })

      const closedAttempt = await request.post(serviceUrl('attendeeRegistration', '/registrations'), {
        headers: await authHeaders(users.attendee), data: { eventId: fixture.closed.eventId },
      })
      expect(closedAttempt.status()).toBe(409)
      expect(await closedAttempt.json()).toMatchObject({
        code: 'REGISTRATION_CLOSED', message: 'Registration has closed because this event has started.',
      })

      const unconfirmedAttempt = await request.post(serviceUrl('attendeeRegistration', '/registrations'), {
        headers: await authHeaders(users.attendee), data: { eventId: fixture.notConfirmed.eventId },
      })
      expect(unconfirmedAttempt.status()).toBe(409)
      expect(await unconfirmedAttempt.json()).toMatchObject({
        code: 'REGISTRATION_CLOSED', message: 'Registration is available only for confirmed events.',
      })
      const unconfirmedRows = await request.get(
        serviceUrl('attendeeRegistration', `/events/${fixture.notConfirmed.eventId}/registrations`),
        { headers: await authHeaders(users.coordinator) },
      )
      expect((await unconfirmedRows.json()).registrations).toHaveLength(0)
    })

    await test.step('Path C: Withdrawal after the configured deadline is refused with organiser guidance', async () => {
      await attendee.goto('/registrations')
      const registration = attendee.getByRole('button').filter({ hasText: fixture.deadline.eventName })
      await expect(registration).toContainText('Confirmed')
      await registration.click()
      await attendee.getByRole('button', { name: 'Withdraw registration' }).click()
      const confirmation = attendee.getByRole('dialog', { name: 'Confirm withdrawal' })
      await confirmation.getByRole('button', { name: 'Confirm withdrawal' }).click()
      await expect(confirmation.getByRole('alert')).toContainText(
        'The withdrawal deadline has passed. Please contact the event organisers.',
      )
      await expect(attendee.locator('.event-card-header .status-badge')).toHaveText('Confirmed')
    })
  })
})