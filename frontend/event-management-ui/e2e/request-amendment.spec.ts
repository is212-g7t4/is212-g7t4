/**
 * # SCRUM-16 — Request Amendment on Event Submission
 *
 * As an Event Coordinator, I want to request an amendment on a submitted event request assigned to me, so that the Event Organiser can update specific details before I decide.
 * AC1: Given an Event Request has status 'Submitted' and is assigned to the current Event Coordinator, when they request an amendment, then the status changes to 'Amendment Requested', and the Coordinator must specify which field(s) require changes.
 * AC2: The reason/details for the amendment are stored with the request.
 * AC3: The Event Organiser can edit only the fields flagged by the Event Coordinator; all other submitted fields remain locked.
 * AC4: Given the Event Organiser resubmits after amending, the status changes back to 'Submitted', the amendment timestamp is recorded, and the request remains assigned to the same Event Coordinator.
 * AC5: The requesting Event Coordinator's identity and timestamp are recorded for auditability.
 *
 * Mocked APIs: proves the UI flow and the requests it sends. The status
 * change, the server-side field lock and the audit record are proven by
 * Event Service's unit and integration tests.
 */
import { allUsers, asUser, json, makeEvent, mock, test, expect, users } from './fixtures'

const coordinators = [users.lead, users.coordinator].map((user) => ({ ...user, contact_details: '+65 0000 0000' }))
const REASON = 'The hall is booked that week and 100 is over its limit.'
const openRound = {
  id: 'amendment-1',
  fields: ['preferredStartDate', 'preferredEndDate', 'expectedAttendance'],
  reason: REASON,
  requestedBy: users.coordinator.user_id,
  requestedAt: '2026-11-02T01:00:00+00:00',
  resubmittedBy: null,
  resubmittedAt: null,
  changes: null,
  note: null,
}
const underReview = makeEvent({ status: 'Under Review', organiserId: users.organiser.user_id })
const amending = makeEvent({ status: 'Amendment Requested', organiserId: users.organiser.user_id, amendmentHistory: [openRound] })

test.beforeEach(async ({ page, mockApi }) => {
  await mockApi(page)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
})

test('AC1/AC2: the coordinator flags Date/time and attendance with a reason', async ({ page }) => {
  let body: unknown
  await asUser(page, users.coordinator.user_id)
  await mock(page, 'assignment', '/coordinators', (route) => json(route, { coordinators }))
  await mock(page, 'event', '/events/submitted', (route) => json(route, { events: [underReview] }))
  await mock(page, 'event', '/events/evt-001/amendment-request', (route) => {
    body = route.request().postDataJSON()
    return json(route, amending)
  })
  await page.goto('/requests/review')

  await test.step('open the dialog; nothing can be sent until a field and a reason are given', async () => {
    await page.getByRole('button', { name: 'Request amendment' }).click()
    const dialog = page.getByRole('dialog', { name: 'Request amendment' })
    const send = dialog.getByRole('button', { name: 'Send amendment request' })
    await expect(send).toBeDisabled()
    await dialog.getByRole('checkbox', { name: 'Date/time' }).check()
    await dialog.getByRole('checkbox', { name: 'Expected attendance' }).check()
    await expect(send).toBeDisabled()
    await dialog.getByLabel(/Reason or details/).fill(REASON)
    await send.click()
  })

  await test.step('the request is sent and the event leaves the review list', async () => {
    await expect(page.getByRole('dialog', { name: 'Amendment Requested' })).toContainText('sent back to its organiser')
    expect(body).toEqual({
      coordinatorId: users.coordinator.user_id,
      fields: ['preferredStartDate', 'preferredEndDate', 'expectedAttendance'],
      reason: REASON,
    })
    await page.getByRole('button', { name: 'OK' }).click()
    await expect(page.getByText('No submitted event requests yet.')).toBeVisible()
  })
})

test('AC3/AC4: the organiser edits only the flagged fields and resubmits', async ({ page }) => {
  let body: unknown
  await asUser(page, users.organiser.user_id)
  await mock(page, 'event', '/events/evt-001', (route) => json(route, amending))
  await mock(page, 'event', '/events/evt-001/amendment-response', (route) => {
    body = route.request().postDataJSON()
    return json(route, makeEvent({
      status: 'Submitted',
      organiserId: users.organiser.user_id,
      expectedAttendance: '60',
      amendmentHistory: [{
        ...openRound,
        resubmittedBy: users.organiser.user_id,
        resubmittedAt: '2026-11-03T01:00:00+00:00',
        changes: { expectedAttendance: { from: '100', to: '60' } },
      }],
    }))
  })
  await page.goto('/events/evt-001')

  await test.step('only the flagged fields have inputs', async () => {
    await expect(page.getByRole('heading', { name: 'Amendment required' })).toBeVisible()
    await expect(page.getByText(REASON).first()).toBeVisible()
    await expect(page.getByLabel('Preferred Start Date & Time')).toBeVisible()
    await expect(page.getByLabel('Preferred End Date & Time')).toBeVisible()
    await expect(page.getByLabel('Expected Attendance')).toHaveValue('100')
    await expect(page.getByLabel('Event Name')).toHaveCount(0)
    await expect(page.getByLabel('Venue Requirements')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Resubmit' })).toBeDisabled()
  })

  await test.step('change attendance and resubmit; the event is Submitted again', async () => {
    await page.getByLabel('Expected Attendance').fill('60')
    await page.getByRole('button', { name: 'Resubmit' }).click()
    await expect(page.getByRole('status').filter({ hasText: 'back with the same Event Coordinator' })).toBeVisible()
    await expect(page.locator('.status-badge')).toHaveText('Submitted')
    expect(body).toEqual({ organiserId: users.organiser.user_id, changes: { expectedAttendance: '60' } })
    await expect(page.getByText('Expected Attendance: 100 → 60')).toBeVisible()
  })
})

test('AC3: a locked-field refusal from the API is shown to the organiser', async ({ page }) => {
  await asUser(page, users.organiser.user_id)
  await mock(page, 'event', '/events/evt-001', (route) => json(route, amending))
  await mock(page, 'event', '/events/evt-001/amendment-response', (route) => json(route, {
    code: 'AMENDMENT_FIELD_LOCKED',
    message: 'Only the fields the Event Coordinator flagged can be changed.',
    lockedFields: ['venueRequirements'],
  }, 400))
  await page.goto('/events/evt-001')

  await page.getByLabel('Expected Attendance').fill('60')
  await page.getByRole('button', { name: 'Resubmit' }).click()

  await expect(page.getByRole('alert')).toHaveText('Only the fields the Event Coordinator flagged can be changed.')
  await expect(page.locator('.status-badge')).toHaveText('Amendment Requested')
})
