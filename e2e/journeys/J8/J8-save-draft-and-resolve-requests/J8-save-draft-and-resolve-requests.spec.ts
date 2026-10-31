import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import type { APIRequestContext, Page } from '@playwright/test'
import { deleteFixtureEvents } from '../../../helpers/cleanup'
import { authHeaders, openAs, randomWindow, serviceUrl, users } from '../../../helpers/stack'

/**
 * J8 — Save a draft and resolve clarification and amendment requests (Medium; optional presentation opening)
 *
 * Requires the real stack (`npm run dev`) and the seeded database.
 *
 * Journey ticket: SCRUM-262 (E2E Testing J8)
 *
 * Stories this journey exercises (a change to any of these can break it):
 *   - SCRUM-11  Event Submission Form (complete and submit a reopened draft)
 *   - SCRUM-12  Save Event Request as Draft (private draft survives reopening)
 *   - SCRUM-15  Request Clarification on Event Submission (locked fields, reply and history)
 *   - SCRUM-16  Request Amendment on Event Submission (field-level lock, resubmission and history)
 *   - SCRUM-44  Event Submission Notifications (Lead-facing submission alert in the bell panel)
 *   - SCRUM-158 View Unassigned Event Queue (one submitted event appears for the Lead)
 *   - SCRUM-159 Assign Coordinator to an Event (assign the Coordinator used in later paths)
 *
 * Stories the fixture setup relies on:
 *   - SCRUM-8   User Authentication (seeded role accounts)
 *
 * The same run-owned event moves through all three paths so status, assignment and
 * both request histories can be checked together after every resubmission.
 */
test.describe.configure({ mode: 'serial', timeout: 300_000 })

test.describe('J8 Save a draft and resolve clarification and amendment requests', () => {
  const runId = randomUUID()
  const eventName = `J8 Event ${runId}`
  const amendedEventName = `J8 Event amended ${runId}`
  const scope = { eventNames: [eventName, amendedEventName], venueNames: [] }

  test.afterAll(async () => { await deleteFixtureEvents(scope) })

  async function openLeadQueue(page: Page) {
    const loaded = page.waitForResponse((response) =>
      new URL(response.url()).pathname === '/queue' && response.request().method() === 'GET')
    await page.goto('/requests/queue')
    await loaded
  }

  async function expectSubmissionNotification(page: Page) {
    await page.goto('/notifications')
    const refresh = page.getByRole('button', { name: 'Refresh notifications' })
    const inboxItem = page.locator('.notification-list li').filter({ hasText: eventName })
    await expect(async () => {
      await refresh.click()
      await expect(inboxItem.first()).toContainText(`${eventName}. Review required.`, { timeout: 2_000 })
    }).toPass({ timeout: 120_000, intervals: [1_000, 3_000, 5_000] })

    await page.getByRole('button', { name: /^Notifications,/ }).click()
    const recent = page.getByRole('region', { name: 'Recent notifications' })
    await expect(recent).toBeVisible()
    await expect(recent.locator('.notification-list li').filter({ hasText: eventName }).first())
      .toContainText(`${eventName}. Review required.`)
  }

  async function readEvent(api: APIRequestContext, actor: typeof users.organiser | typeof users.coordinator, eventId: string) {
    const identity = actor.id === users.organiser.id
      ? `organiserId=${actor.id}`
      : `coordinatorId=${actor.id}`
    const response = await api.get(serviceUrl('event', `/events/${eventId}?${identity}`), {
      headers: await authHeaders(actor),
    })
    expect(response.ok(), `read event: ${response.status()} ${await response.text()}`).toBe(true)
    return response.json() as Promise<{
      id: string
      eventName: string
      description: string
      purpose: string
      preferredStartDate: string
      preferredEndDate: string
      expectedAttendance: string
      status: string
      coordinatorId: string | null
      clarificationHistory: { question: string; response: string | null }[]
      amendmentHistory: {
        fields: string[]
        requestedBy: string
        resubmittedBy: string | null
        resubmittedAt: string | null
        changes: Record<string, { from: string; to: string }> | null
      }[]
      actionHistory: { status: string }[]
    }>
  }

  test('draft stays private, clarification stays locked, and amendment unlocks only flagged fields', async ({ browser, request }) => {
    const window = randomWindow()
    const organiser = await openAs(browser, users.organiser)
    const otherOrganiserHeaders = await authHeaders(users.otherOrganiser)
    const lead = await openAs(browser, users.lead)

    await test.step('Organiser saves an incomplete draft; only that organiser can see it', async () => {
      await organiser.goto('/events/new')
      await organiser.getByLabel('Event Name').fill(eventName)
      const savedResponse = organiser.waitForResponse((response) =>
        new URL(response.url()).pathname === '/events/drafts' && response.request().method() === 'POST')
      await organiser.getByRole('button', { name: 'Save as Draft' }).click()
      await expect(organiser.getByRole('status')).toContainText('Draft saved.')
      const draftResponse = await savedResponse
      expect(draftResponse.ok(), `save draft: ${draftResponse.status()} ${await draftResponse.text()}`).toBe(true)
      const draftId = (await draftResponse.json()).id as string

      await organiser.goto('/my-events')
      await expect(organiser.getByRole('button', { name: `Open draft ${eventName}` })).toBeVisible()
      const otherDrafts = await request.get(serviceUrl('event', '/events/drafts'), { headers: otherOrganiserHeaders })
      expect(otherDrafts.ok(), `other organiser drafts: ${otherDrafts.status()}`).toBe(true)
      const otherNames = ((await otherDrafts.json()) as { events: { eventName: string }[] }).events.map((event) => event.eventName)
      expect(otherNames).not.toContain(eventName)

      await openLeadQueue(lead)
      await expect(lead.getByRole('row').filter({ hasText: eventName })).toHaveCount(0)
      await organiser.getByRole('button', { name: `Open draft ${eventName}` }).click()
      await expect(organiser.getByRole('heading', { name: 'Edit Draft Event Request' })).toBeVisible()
      await expect(organiser.getByLabel('Event Name')).toHaveValue(eventName)
      expect(draftId).toMatch(/^[0-9a-f-]{36}$/i)
    })

    let eventId = ''
    await test.step('Organiser submits the reopened draft; Lead sees one unassigned row and opens its submission notification', async () => {
      await organiser.getByLabel('Description').fill('A practical workshop for the community.')
      await organiser.getByLabel('Purpose').fill('Share skills and build local connections.')
      await organiser.getByLabel('Preferred Start Date & Time').fill(window.start)
      await organiser.getByLabel('Preferred End Date & Time').fill(window.end)
      await organiser.getByLabel('Expected Attendance').fill('40')
      const submitResponse = organiser.waitForResponse((response) =>
        new URL(response.url()).pathname.endsWith('/submit') && response.request().method() === 'POST')
      await organiser.getByRole('button', { name: 'Submit Request' }).click()
      const submitted = await submitResponse
      expect(submitted.ok(), `submit draft: ${submitted.status()} ${await submitted.text()}`).toBe(true)
      eventId = (await submitted.json()).id as string
      await expect(organiser.getByRole('status')).toContainText('Status: Submitted')

      await openLeadQueue(lead)
      const row = lead.getByRole('row').filter({ hasText: eventName })
      await expect(row).toHaveCount(1)
      await expect(row).toContainText('Unassigned')

      await expectSubmissionNotification(lead)
      await openLeadQueue(lead)
      await expect(lead.getByRole('row').filter({ hasText: eventName })).toHaveCount(1)

      const currentRow = lead.getByRole('row').filter({ hasText: eventName })
      await currentRow.getByLabel('Coordinator').selectOption(users.coordinator.id)
      await currentRow.getByRole('button', { name: 'Assign', exact: true }).click()
      await expect(currentRow).toContainText('Assigned')
    })

    const coordinator = await openAs(browser, users.coordinator)
    await test.step('Assigned Coordinator asks a clarification; organiser sees the question but no submitted-field controls', async () => {
      await coordinator.goto('/requests/review')
      const card = coordinator.getByRole('article').filter({ hasText: eventName })
      await expect(card).toBeVisible()
      await card.getByRole('button', { name: 'Request clarification' }).click()
      const question = 'Which audience is this workshop intended for?'
      const dialog = coordinator.getByRole('dialog', { name: 'Request clarification' })
      await dialog.locator('#clarification-question').fill(question)
      await dialog.getByRole('button', { name: 'Send request' }).click()
      await expect(coordinator.getByRole('heading', { name: 'Clarification Requested' })).toBeVisible()

      const awaitingClarification = await readEvent(request, users.organiser, eventId)
      expect(awaitingClarification.status).toBe('Clarification Requested')
      expect(awaitingClarification.coordinatorId).toBe(users.coordinator.id)
      expect(awaitingClarification.clarificationHistory.at(-1)?.question).toBe(question)

      await organiser.goto(`/events/${eventId}`)
      await expect(organiser.getByText(question)).toBeVisible()
      await expect(organiser.getByLabel('Clarification response')).toBeVisible()
      await expect(organiser.getByLabel('Event Name')).toHaveCount(0)
      const lockedEdit = await request.patch(serviceUrl('event', `/events/${eventId}/details`), {
        headers: await authHeaders(users.organiser),
        data: { changes: { eventName: amendedEventName } },
      })
      expect(lockedEdit.status()).toBe(403)

      await organiser.getByLabel('Clarification response').fill('The workshop is for local community volunteers.')
      await organiser.getByRole('button', { name: 'Submit response' }).click()
      await expect(organiser.getByRole('status')).toContainText('same Event Coordinator')
      const clarified = await readEvent(request, users.organiser, eventId)
      expect(clarified.status).toBe('Submitted')
      expect(clarified.coordinatorId).toBe(users.coordinator.id)
      expect(clarified.eventName).toBe(eventName)
      expect(clarified.description).toBe('A practical workshop for the community.')
      expect(clarified.clarificationHistory).toHaveLength(1)
      expect(clarified.clarificationHistory[0].response).toBe('The workshop is for local community volunteers.')
    })

    await test.step('Coordinator flags Event Name; only that field is editable and an unflagged server write is rejected', async () => {
      await coordinator.goto('/requests/review')
      const card = coordinator.getByRole('article').filter({ hasText: eventName })
      await expect(card).toBeVisible()
      await card.getByRole('button', { name: 'Request amendment' }).click()
      const dialog = coordinator.getByRole('dialog', { name: 'Request amendment' })
      await dialog.getByRole('checkbox', { name: 'Event name' }).check()
      await dialog.locator('#amendment-reason').fill('Use the approved public-facing event name.')
      await dialog.getByRole('button', { name: 'Send amendment request' }).click()
      await expect(coordinator.getByRole('heading', { name: 'Amendment Requested' })).toBeVisible()

      await organiser.goto(`/events/${eventId}`)
      const amendment = organiser.getByRole('heading', { name: 'Amendment required' }).locator('..')
      const form = amendment.locator('form')
      await expect(form.getByLabel('Event Name')).toBeVisible()
      await expect(form.getByLabel('Description')).toHaveCount(0)
      const forbiddenChange = await request.patch(serviceUrl('event', `/events/${eventId}/amendment-response`), {
        headers: await authHeaders(users.organiser),
        data: { changes: { description: 'This unflagged change must be rejected.' } },
      })
      expect(forbiddenChange.status()).toBe(400)
      expect((await forbiddenChange.json()).code).toBe('AMENDMENT_FIELD_LOCKED')

      const stillOpen = await readEvent(request, users.organiser, eventId)
      expect(stillOpen.status).toBe('Amendment Requested')
      expect(stillOpen.eventName).toBe(eventName)
      expect(stillOpen.description).toBe('A practical workshop for the community.')
      expect(stillOpen.coordinatorId).toBe(users.coordinator.id)

      await form.getByLabel('Event Name').fill(amendedEventName)
      await form.getByRole('button', { name: 'Resubmit' }).click()
      await expect(organiser.getByRole('status')).toContainText('same Event Coordinator')
      const resubmitted = await readEvent(request, users.organiser, eventId)
      expect(resubmitted.status).toBe('Submitted')
      expect(resubmitted.coordinatorId).toBe(users.coordinator.id)
      expect(resubmitted.eventName).toBe(amendedEventName)
      expect(resubmitted.description).toBe('A practical workshop for the community.')
      expect(resubmitted.clarificationHistory).toHaveLength(1)
      expect(resubmitted.amendmentHistory).toHaveLength(1)
      expect(resubmitted.amendmentHistory[0]).toMatchObject({
        fields: ['eventName'],
        requestedBy: users.coordinator.id,
        resubmittedBy: users.organiser.id,
        changes: { eventName: { from: eventName, to: amendedEventName } },
      })
      expect(resubmitted.amendmentHistory[0].resubmittedAt).toBeTruthy()
      expect(resubmitted.actionHistory.map((action) => action.status)).toEqual([
        'Clarification Requested', 'Submitted', 'Amendment Requested', 'Submitted',
      ])

      await coordinator.goto('/requests/review')
      const returnedCard = coordinator.getByRole('article').filter({ hasText: amendedEventName })
      await expect(returnedCard).toBeVisible()
      await expect(returnedCard).toContainText('Submitted')
    })
  })
})