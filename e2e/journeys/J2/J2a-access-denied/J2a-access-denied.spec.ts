import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { deleteFixtureEvents } from '../../../helpers/cleanup'
import { authHeaders, openAs, randomWindow, serviceUrl, users } from '../../../helpers/stack'
import { assignJ2Coordinator, createJ2Event } from '../helpers/seed'

/**
 * J2A — Refuse protected event access and preserve the legitimate owner's access.
 *
 * Requires the real stack (`npm run dev`), the seeded Supabase accounts and
 * `E2E_PASSWORD` (or per-role password variables) set.
 *
 * Journey ticket: SCRUM-256 (E2E Testing J2).
 *
 * Stories this journey exercises:
 *   - SCRUM-8  User Authentication and Authorization
 *   - SCRUM-9  Role-Based Access Control for Events
 *   - SCRUM-10 Role-Based Modification Control for Events
 *
 * Stories the fixture setup relies on:
 *   - SCRUM-8   seeded user accounts for role-based sign-in
 *   - SCRUM-11  Event Submission Form (event creation through the service API)
 *   - SCRUM-159 Assign Coordinator to an Event
 */
test.describe.configure({ mode: 'serial', timeout: 180_000 })

test.describe('J2A access is denied to unauthorised users', () => {
  const runId = randomUUID()
  const eventName = `J2a Event ${runId}`
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
      await assignJ2Coordinator(api, eventId, users.coordinator.id)
    } finally {
      await api.dispose()
    }
  })

  test.afterAll(async () => {
    if (canCleanup) await deleteFixtureEvents(scope)
  })

  test('rejects anonymous, wrong-role, non-owner and unassigned access without changing the event', async ({ browser, request }) => {
    const eventUrl = serviceUrl('event', `/events/${eventId}`)

    await test.step('An unauthenticated browser and direct requests cannot open or change the event', async () => {
      const anonymous = await browser.newPage()
      try {
        await anonymous.goto(`/events/${eventId}`)
        await expect(anonymous.getByLabel(/email/i)).toBeVisible()
        await expect(anonymous.getByText(eventName, { exact: true })).toHaveCount(0)
      } finally {
        await anonymous.close()
      }

      const read = await request.get(eventUrl)
      expect(read.status()).toBe(401)
      expect(await read.text()).not.toContain(eventName)

      const write = await request.patch(`${eventUrl}/progress`, {
        data: { status: 'Approved', actionDetails: 'Unauthenticated change attempt.' },
      })
      expect(write.status()).toBe(401)
      expect(await write.text()).not.toContain(eventName)
    })

    await test.step('A user with the wrong role is refused in the browser and by Event Service', async () => {
      const attendee = await openAs(browser, users.attendee)
      await attendee.goto(`/events/${eventId}`)
      await expect(attendee.getByText(/Event information is visible to Event Coordinators/)).toBeVisible()
      await expect(attendee.getByText(eventName, { exact: true })).toHaveCount(0)

      const headers = await authHeaders(users.attendee)
      const read = await request.get(eventUrl, { headers })
      expect(read.status()).toBe(403)
      expect(await read.text()).not.toContain(eventName)

      const write = await request.patch(`${eventUrl}/progress`, {
        headers,
        data: { status: 'Approved', actionDetails: 'Wrong-role change attempt.' },
      })
      expect(write.status()).toBe(403)
      expect(await write.text()).not.toContain(eventName)
    })

    await test.step('A different Organiser cannot see the event through its own-event page or API', async () => {
      const otherOrganiser = await openAs(browser, users.otherOrganiser)
      await otherOrganiser.goto(`/events/${eventId}`)
      await expect(otherOrganiser.getByRole('alert')).toBeVisible()
      await expect(otherOrganiser.getByText(eventName, { exact: true })).toHaveCount(0)

      const response = await request.get(`${eventUrl}?organiserId=${users.otherOrganiser.id}`, {
        headers: await authHeaders(users.otherOrganiser),
      })
      expect(response.status()).toBe(403)
      expect(await response.text()).not.toContain(eventName)
    })

    await test.step('A Coordinator who is not assigned cannot open or modify the event', async () => {
      const unassignedCoordinator = await openAs(browser, users.coordinatorB)
      await unassignedCoordinator.goto(`/events/${eventId}`)
      await expect(unassignedCoordinator.getByRole('alert')).toContainText('You no longer have access to this event')
      await expect(unassignedCoordinator.getByText(eventName, { exact: true })).toHaveCount(0)

      const headers = await authHeaders(users.coordinatorB)
      const read = await request.get(`${eventUrl}?coordinatorId=${users.coordinatorB.id}`, { headers })
      expect(read.status()).toBe(403)
      expect(await read.text()).not.toContain(eventName)

      const write = await request.patch(`${eventUrl}/progress`, {
        headers,
        data: { status: 'Approved', actionDetails: 'Unassigned coordinator change attempt.' },
      })
      expect(write.status()).toBe(403)
      expect(await write.text()).not.toContain(eventName)
    })

    await test.step('The legitimate Organiser retains access and rejected writes leave the event unchanged', async () => {
      const owner = await openAs(browser, users.organiser)
      await owner.goto(`/events/${eventId}`)
      await expect(owner.getByRole('heading', { name: eventName })).toBeVisible()

      const ownerRead = await request.get(`${eventUrl}?organiserId=${users.organiser.id}`, {
        headers: await authHeaders(users.organiser),
      })
      expect(ownerRead.status()).toBe(200)
      expect(await ownerRead.json()).toMatchObject({ id: eventId, eventName })

      const coordinatorRead = await request.get(`${eventUrl}?coordinatorId=${users.coordinator.id}`, {
        headers: await authHeaders(users.coordinator),
      })
      expect(coordinatorRead.status()).toBe(200)
      expect(await coordinatorRead.json()).toMatchObject({
        eventName,
        status: 'Under Review',
        actionDetails: '',
        actionHistory: [],
        coordinatorId: users.coordinator.id,
      })
    })
  })
})
