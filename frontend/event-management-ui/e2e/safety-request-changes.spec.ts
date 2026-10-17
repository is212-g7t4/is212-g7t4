import type { Page } from '@playwright/test'
import { allUsers, asUser, json, makeEvent, mock, test, expect, users } from './fixtures'

// SCRUM-151: a Safety Officer requests changes to an event's safety
// arrangements. Every backend call is mocked (see fixtures.ts), so this
// needs no running services.

const pending = makeEvent({
  id: 'evt-040',
  eventName: 'Safety Changes Expo',
  status: 'Pending Safety Check',
  actionHistory: [{
    status: 'Pending Safety Check',
    details: 'Submitted for Operational Safety Check (round 1).',
    coordinatorId: users.coordinator.user_id,
    safetyCheckId: 'record-040',
    recordedAt: '2026-11-01T02:30:00+00:00',
  }],
})

type MockApi = (page: Page) => Promise<void>

async function openAsSafetyOfficer(page: Page, mockApi: MockApi, events: Record<string, unknown>[]) {
  await mockApi(page)
  await asUser(page, users.safetyOfficer.user_id)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await mock(page, 'event', '/events', (route) => json(route, { events }))
  for (const event of events) {
    await mock(page, 'event', `/events/${event.id}`, (route) => json(route, event))
  }
}

test('AC1, AC2: requesting changes on two areas moves the event to Safety Changes Requested', async ({ page, mockApi }) => {
  const requests: Record<string, unknown>[] = []
  await openAsSafetyOfficer(page, mockApi, [pending])
  await mock(page, 'event', `/events/${pending.id}`, (route) => json(
    route,
    requests.length === 0
      ? pending
      : { ...pending, status: 'Safety Changes Requested' },
  ))
  await mock(page, 'safetyCheck', '/safety-checks/request-changes', (route) => {
    requests.push(route.request().postDataJSON())
    return json(route, {
      safetyCheck: { id: 'record-040', roundNumber: 1, status: 'Changes Requested', decidedBy: users.safetyOfficer.user_id, decidedAt: '2026-11-02T03:00:00+00:00', remarks: 'Needs another look.' },
      event: { ...pending, status: 'Safety Changes Requested' },
    })
  })

  await page.goto(`/events/${pending.id}`)
  await expect(page.getByRole('heading', { name: 'Safety Changes Expo' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Operational Safety Check' })).toBeVisible()

  await page.getByRole('button', { name: 'Request changes' }).click()
  await page.getByRole('checkbox', { name: /Venue arrangement/ }).check()
  await page.getByLabel('Change needed for Venue arrangement').fill('Move the stage left of centre.')
  await page.getByRole('checkbox', { name: /Event details/ }).check()
  await page.getByLabel('Change needed for Event details').fill('Fix the clashing start time.')
  await page.getByLabel('Reason').fill('Needs another look.')
  await page.getByRole('button', { name: 'Request changes' }).click()

  await expect(page.locator('.status-badge').first()).toContainText('Safety Changes Requested')
  expect(requests.at(-1)).toMatchObject({
    eventId: pending.id,
    safetyOfficerId: users.safetyOfficer.user_id,
    reason: 'Needs another look.',
    flags: [
      { area: 'venue arrangement', changeRequired: 'Move the stage left of centre.' },
      { area: 'event details', changeRequired: 'Fix the clashing start time.' },
    ],
  })
})

test('AC1: the submit button stays disabled until an area, its change text and a reason are filled', async ({ page, mockApi }) => {
  await openAsSafetyOfficer(page, mockApi, [pending])

  await page.goto(`/events/${pending.id}`)
  await expect(page.getByRole('heading', { name: 'Operational Safety Check' })).toBeVisible()

  await page.getByRole('button', { name: 'Request changes' }).click()
  await expect(page.getByRole('button', { name: 'Request changes' })).toBeDisabled()

  await page.getByRole('checkbox', { name: /Venue arrangement/ }).check()
  await expect(page.getByRole('button', { name: 'Request changes' })).toBeDisabled()

  await page.getByLabel('Change needed for Venue arrangement').fill('Move the stage.')
  await expect(page.getByRole('button', { name: 'Request changes' })).toBeDisabled()

  await page.getByLabel('Reason').fill('Needs another look.')
  await expect(page.getByRole('button', { name: 'Request changes' })).toBeEnabled()
})

// Safety revision AC1/AC2/AC3/AC5: feedback is visible, either pending area blocks,
// and both ready areas enable resubmission to Pending Safety Check on desktop/mobile.
// APIs are mocked: this journey does not prove actual staff decisions or database round persistence.
for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  test(`revision AC1: coordinator reads safety feedback at ${viewport.width}px`, async ({ page, mockApi }, testInfo) => {
    await page.setViewportSize(viewport)
    await mockApi(page)
    await asUser(page, users.coordinator.user_id)
    const changesRequested = { ...pending, status: 'Safety Changes Requested' }
    let equipmentPending = true
    let venuePending = true
    let resubmitted = false
    await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
    await mock(page, 'venue', '/venues', (route) => json(route, { venues: [] }))
    await mock(page, 'event', '/events', (route) => json(route, { events: [changesRequested] }))
    await mock(page, 'event', `/events/${pending.id}`, (route) => json(route,
      resubmitted ? { ...pending, status: 'Pending Safety Check' } : changesRequested))
    await mock(page, 'venueBooking', `/events/${pending.id}/booking-requests`, (route) => json(route, { bookings: [] }))
    await mock(page, 'safetyCheck', '/safety-checks/resubmit/readiness', (route) => json(route, {
      ready: !equipmentPending && !venuePending, eventStatus: 'Safety Changes Requested',
      outstanding: [
        ...(equipmentPending ? [{ type: 'equipment', id: 'request-1', status: 'Pending', label: 'Microphone', reason: 'Waiting for review.' }] : []),
        ...(venuePending ? [{ type: 'venue', id: 'booking-1', status: 'Pending Review', label: 'Grand Hall', reason: 'Waiting for Venue Staff approval.' }] : []),
      ],
    }))
    await mock(page, 'safetyCheck', '/safety-checks/resubmit', (route) => {
      expect(route.request().postDataJSON()).toEqual({ eventId: pending.id, coordinatorId: users.coordinator.user_id })
      resubmitted = true
      return json(route, { safetyCheck: { id: 'record-041', roundNumber: 3, status: 'Pending' }, event: { ...pending, status: 'Pending Safety Check' } }, 201)
    })
    await mock(page, 'safetyCheck', '/safety-checks/feedback', (route) => {
      expect(new URL(route.request().url()).searchParams.get('coordinatorId')).toBe(users.coordinator.user_id)
      return json(route, { safetyChecks: [{
        id: 'record-040', eventId: pending.id, roundNumber: 2, status: 'Changes Requested',
        decidedAt: '2026-11-02T03:00:00Z', remarks: 'Emergency exits must remain accessible.',
        flags: [
          { id: 'flag-venue', area: 'venue arrangement', changeRequired: 'Move the stage away from the exit.', bookingId: null, equipmentRequestId: null },
          { id: 'flag-tech', area: 'technical arrangement', changeRequired: 'Reroute cables around the accessible walkway.', bookingId: null, equipmentRequestId: null },
        ],
      }] })
    })

    await page.goto(`/events/${pending.id}`)
    const feedback = page.getByRole('region', { name: 'Safety Officer feedback' })
    await expect(feedback.getByText('Changes Requested', { exact: true })).toBeVisible()
    await expect(feedback.getByText('Emergency exits must remain accessible.')).toBeVisible()
    await expect(feedback.getByText('Venue arrangement', { exact: true }).locator('..')).toContainText('Move the stage away from the exit.')
    await expect(feedback.getByText('Technical / equipment arrangement').locator('..')).toContainText('Reroute cables around the accessible walkway.')
    expect(await feedback.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
    await feedback.screenshot({ path: testInfo.outputPath(`safety-feedback-${viewport.width}.png`) })
    const resubmit = feedback.getByRole('button', { name: 'Resubmit Safety Check' })
    await expect(resubmit).toBeDisabled()
    equipmentPending = false
    // Safety revision AC2: equipment ready alone is insufficient while the venue is still pending.
    await page.getByRole('button', { name: 'Refresh', exact: true }).click()
    await expect(resubmit).toBeDisabled()
    await expect(feedback.getByText('Waiting for Venue Staff approval.')).toBeVisible()
    venuePending = false
    // Safety revision AC5 (browser): both areas ready permits the separate resubmission action.
    await page.getByRole('button', { name: 'Refresh', exact: true }).click()
    await expect(resubmit).toBeEnabled()
    await feedback.screenshot({ path: testInfo.outputPath(`safety-resubmit-${viewport.width}.png`) })
    await resubmit.click()
    await expect(page.locator('.status-badge').first()).toHaveText('Pending Safety Check')
    await expect(page.getByRole('button', { name: 'Resubmit Safety Check' })).toHaveCount(0)
    expect(resubmitted).toBe(true)
  })
}
