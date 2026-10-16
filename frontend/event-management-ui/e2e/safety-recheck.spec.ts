import type { Page } from '@playwright/test'
import { allUsers, asUser, json, makeEvent, mock, mockApprovedVenue, test, expect, users, venues } from './fixtures'

// SCRUM-153: a high-impact change to a Confirmed event withdraws its safety
// approval. Every backend call is mocked (see fixtures.ts), so this needs no
// running services.
//
// AC1 a high-impact change sends the event back to Pending Safety Check, and
//     the coordinator is told why.
// AC2 a low-impact change (the name) leaves it Confirmed.
// AC3 the withdrawal stays visible in the event's history.

const WITHDRAWN_ROUND = 'record-053'
const NEW_ROUND = 'record-054'

const confirmed = makeEvent({
  id: 'evt-053',
  eventName: 'Safety Recheck Expo',
  status: 'Confirmed',
  expectedAttendance: '120',
  actionHistory: [
    {
      status: 'Pending Safety Check',
      details: 'Submitted for Operational Safety Check (round 1).',
      coordinatorId: users.coordinator.user_id,
      safetyCheckId: WITHDRAWN_ROUND,
      recordedAt: '2026-11-01T02:30:00+00:00',
    },
    {
      status: 'Confirmed',
      details: 'Operational Safety Check approved (round 1).',
      decidedBy: users.safetyOfficer.user_id,
      safetyCheckId: WITHDRAWN_ROUND,
      remarks: 'Looks safe.',
      recordedAt: '2026-11-02T03:00:00+00:00',
    },
  ],
})

// What the event looks like once the approval has been withdrawn: back to
// Pending Safety Check, with the reason in its history (AC1, AC3).
const afterRecheck = {
  ...confirmed,
  status: 'Pending Safety Check',
  expectedAttendance: '400',
  actionHistory: [
    ...(confirmed.actionHistory as Record<string, unknown>[]),
    {
      status: 'Pending Safety Check',
      details:
        'Safety approval withdrawn because Expected attendance changed after approval. '
        + 'The event needs a new Operational Safety Check (round 2) before it can proceed to preparation.',
      changedFields: ['expectedAttendance'],
      highImpactFields: ['expectedAttendance'],
      coordinatorId: users.coordinator.user_id,
      withdrawnSafetyCheckId: WITHDRAWN_ROUND,
      safetyCheckId: NEW_ROUND,
      recordedAt: '2026-11-03T04:00:00+00:00',
    },
  ],
}

type MockApi = (page: Page) => Promise<void>

/** The event page as its assigned coordinator, with the event at `Confirmed`. */
async function openAsCoordinator(page: Page, mockApi: MockApi, read: () => Record<string, unknown>) {
  await mockApi(page)
  await asUser(page, users.coordinator.user_id)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await mock(page, 'event', '/events', (route) => json(route, { events: [read()] }))
  await mock(page, 'event', `/events/${confirmed.id}`, (route) => json(route, read()))
  await mockApprovedVenue(page, confirmed.id as string)
  // The venue bookings panel the coordinator also sees on this page.
  await mock(page, 'venueBooking', `/events/${confirmed.id}/booking-requests`, (route) => json(route, { bookings: [] }))
  await mock(page, 'venue', '/venues', (route) => json(route, { venues }))
}

test('AC2: renaming a Confirmed event leaves it Confirmed', async ({ page, mockApi }) => {
  const edits: Record<string, unknown>[] = []
  let current: Record<string, unknown> = confirmed
  await openAsCoordinator(page, mockApi, () => current)
  await mock(page, 'event', `/events/${confirmed.id}/details`, (route) => {
    const body = route.request().postDataJSON()
    edits.push(body)
    current = { ...confirmed, eventName: 'Safety Recheck Expo (Autumn)' }
    return json(route, current)
  })

  await page.goto(`/events/${confirmed.id}`)
  await expect(page.getByRole('heading', { name: 'Safety Recheck Expo' })).toBeVisible()

  await page.getByRole('button', { name: 'Edit details' }).click()
  await page.getByLabel('Event Name *').fill('Safety Recheck Expo (Autumn)')
  await page.getByRole('button', { name: 'Save details' }).click()

  await expect(page.getByText('Event details saved.')).toBeVisible()
  // AC2: still Confirmed, and no safety call was made at all.
  await expect(page.locator('.status-badge').first()).toContainText('Confirmed')
  expect(edits.at(-1)).toMatchObject({
    coordinatorId: users.coordinator.user_id,
    changes: { eventName: 'Safety Recheck Expo (Autumn)' },
  })
})

test('AC1, AC3: changing expected attendance withdraws the approval after a confirm step', async ({ page, mockApi }) => {
  const rechecks: Record<string, unknown>[] = []
  let current: Record<string, unknown> = confirmed
  await openAsCoordinator(page, mockApi, () => current)
  // The gate: Event Service refuses the high-impact edit and says what it costs.
  await mock(page, 'event', `/events/${confirmed.id}/details`, (route) => json(route, {
    code: 'SAFETY_RECHECK_REQUIRED',
    message: 'Changing Expected attendance will withdraw this event\'s safety approval. It will return to Pending Safety Check.',
    changedFields: ['expectedAttendance'],
    highImpactFields: ['expectedAttendance'],
    labels: ['Expected attendance'],
  }, 409))
  await mock(page, 'safetyCheck', '/safety-checks/recheck', (route) => {
    rechecks.push(route.request().postDataJSON())
    current = afterRecheck
    return json(route, {
      event: afterRecheck,
      safetyCheck: { id: NEW_ROUND, roundNumber: 2, status: 'Pending' },
      withdrawnSafetyCheck: {
        id: WITHDRAWN_ROUND,
        roundNumber: 1,
        status: 'Approval Withdrawn',
        decidedBy: users.safetyOfficer.user_id,
        decidedAt: '2026-11-02T03:00:00+00:00',
        remarks: 'Looks safe.',
        withdrawnAt: '2026-11-03T04:00:00+00:00',
        withdrawnBy: users.coordinator.user_id,
        withdrawalReason: 'Expected attendance changed after safety approval.',
      },
      changedFields: ['expectedAttendance'],
      reason: 'Expected attendance changed after safety approval.',
    })
  })

  await page.goto(`/events/${confirmed.id}`)
  await expect(page.locator('.status-badge').first()).toContainText('Confirmed')

  await page.getByRole('button', { name: 'Edit details' }).click()
  await page.getByLabel('Expected Attendance *').fill('400')
  await page.getByRole('button', { name: 'Save details' }).click()

  // The confirm step, naming the change and its consequence — nothing has
  // been withdrawn yet.
  await expect(page.getByRole('heading', { name: 'Withdraw safety approval?' })).toBeVisible()
  await expect(page.getByText(/Expected attendance/).first()).toBeVisible()
  await expect(page.getByText(/New attendee registrations close until then/)).toBeVisible()
  expect(rechecks).toEqual([])

  await page.getByRole('button', { name: 'Save and withdraw approval' }).click()

  // AC1: back to Pending Safety Check, with the reason shown.
  await expect(page.locator('.status-badge').first()).toContainText('Pending Safety Check')
  await expect(page.getByText(/Safety approval withdrawn because Expected attendance changed/).first()).toBeVisible()
  // AC3: the withdrawal is in the event's history, tagged and itemised.
  await expect(page.getByText('Safety approval withdrawn').first()).toBeVisible()
  await expect(page.getByText('Changed: Expected attendance')).toBeVisible()
  // The original approval entry is still there.
  await expect(page.getByText('Operational Safety Check approved (round 1).')).toBeVisible()
  expect(rechecks.at(-1)).toMatchObject({
    eventId: confirmed.id,
    coordinatorId: users.coordinator.user_id,
    changes: { expectedAttendance: '400' },
  })
})

test('AC1: "Go back" leaves the approval in place', async ({ page, mockApi }) => {
  const rechecks: Record<string, unknown>[] = []
  await openAsCoordinator(page, mockApi, () => confirmed)
  await mock(page, 'event', `/events/${confirmed.id}/details`, (route) => json(route, {
    code: 'SAFETY_RECHECK_REQUIRED',
    message: 'Changing Expected attendance will withdraw this event\'s safety approval.',
    changedFields: ['expectedAttendance'],
    highImpactFields: ['expectedAttendance'],
    labels: ['Expected attendance'],
  }, 409))
  await mock(page, 'safetyCheck', '/safety-checks/recheck', (route) => {
    rechecks.push(route.request().postDataJSON())
    return json(route, {}, 500)
  })

  await page.goto(`/events/${confirmed.id}`)
  await page.getByRole('button', { name: 'Edit details' }).click()
  await page.getByLabel('Expected Attendance *').fill('400')
  await page.getByRole('button', { name: 'Save details' }).click()

  await expect(page.getByRole('heading', { name: 'Withdraw safety approval?' })).toBeVisible()
  await page.getByRole('button', { name: 'Go back' }).click()

  // Back on the form, the event untouched, and nothing withdrawn.
  await expect(page.getByLabel('Expected Attendance *')).toHaveValue('400')
  await expect(page.locator('.status-badge').first()).toContainText('Confirmed')
  expect(rechecks).toEqual([])
})
