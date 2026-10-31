import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import type { Page } from '@playwright/test'
import { deleteNamedFixtureEvents } from '../../../helpers/cleanup'
import { openAs, randomWindow, users } from '../../../helpers/stack'
import { createJ1Venue } from '../helpers/seed'

/**
 * J1 — Complete an event from submission to attendee registration.
 *
 * Requires the real stack (`npm run dev`), the seeded Supabase accounts and
 * `E2E_PASSWORD` set to their shared password.
 *
 * Journey ticket: SCRUM-255.
 * Story keys are provisional per the current J1 notes.
 *
 * Stories this journey exercises:
 *   - SCRUM-11, 13, 19, 158, 159
 *   - SCRUM-28–30, 32–38
 *   - SCRUM-40–41, 44–48, 149–150, 162–163, 166, 168
 *
 * Stories the fixture setup relies on:
 *   - SCRUM-8 seeded user accounts for role-based sign-in
 *   - SCRUM-31 seeded equipment catalogue (6-foot folding table)
 */
test.describe.configure({ mode: 'serial', timeout: 300_000 })

const TABLE_NAME = '6-foot folding table'

test.describe('J1 Complete an event from submission to attendee registration', () => {
  const runId = randomUUID()
  const eventName = `J1 Event ${runId}`
  const fixtureNames = { eventName, venueName: `J1 Venue ${runId}` }
  const window = randomWindow()
  let venue: Awaited<ReturnType<typeof createJ1Venue>>
  let canCleanup = false

  test.beforeAll(async ({ playwright }) => {
    await deleteNamedFixtureEvents(fixtureNames)
    canCleanup = true
    const api = await playwright.request.newContext()
    try {
      venue = await createJ1Venue(api, runId)
    } finally {
      await api.dispose()
    }
  })

  test.afterAll(async () => {
    if (canCleanup) await deleteNamedFixtureEvents(fixtureNames)
  })

  async function expectNotification(page: Page, expectedEventName: string, message: RegExp) {
    await page.goto('/notifications')
    const refresh = page.getByRole('button', { name: 'Refresh notifications' })
    await expect(async () => {
      await refresh.click()
      const item = page.locator('.notification-list li')
        .filter({ hasText: expectedEventName }).filter({ hasText: message })
      await expect(item.first()).toBeVisible({ timeout: 2_000 })
    }).toPass({ timeout: 120_000, intervals: [1_000, 3_000, 5_000] })
  }

  test('runs the complete J1 path across organiser, staff, coordinator, officer and attendee roles', async ({ browser }) => {
    const organiser = await openAs(browser, users.organiser)
    let eventId = ''

    await test.step('1. Organiser submits one event into the Lead queue', async () => {
      await organiser.goto('/events/new')
      await organiser.getByLabel('Event Name').fill(eventName)
      await organiser.getByLabel('Description').fill('A J1 end-to-end event.')
      await organiser.getByLabel('Purpose').fill('Validate the full event lifecycle.')
      await organiser.getByLabel('Preferred Start Date & Time').fill(window.start)
      await organiser.getByLabel('Preferred End Date & Time').fill(window.end)
      await organiser.getByLabel('Expected Attendance').fill('50')
      await organiser.getByLabel('Venue Requirements').fill('Theatre seating and projector.')
      await organiser.getByLabel('Equipment Requirements').fill('Two folding tables.')
      await organiser.getByLabel('Registration Needs').fill('Register with an attendee account.')
      await organiser.getByRole('button', { name: 'Submit Request' }).click()
      await expect(organiser.getByRole('status')).toContainText('Status: Submitted.')
    })

    const lead = await openAs(browser, users.lead)
    const coordinator = await openAs(browser, users.coordinator)

    await test.step('2. Lead assigns the Coordinator and the event is no longer unassigned', async () => {
      await lead.goto('/requests/queue')
      const queueRow = lead.getByRole('row').filter({ hasText: eventName })
      await expect(queueRow).toHaveCount(1)
      await expect(queueRow).toContainText('Unassigned')
      await queueRow.getByRole('combobox').selectOption(users.coordinator.id)
      await queueRow.getByRole('button', { name: 'Assign', exact: true }).click()
      await expect(queueRow).toContainText('Assigned')
      await expect(queueRow.getByText('Unassigned', { exact: true })).toHaveCount(0)
      await queueRow.getByRole('button', { name: 'View details' }).click()
      await expect(lead).toHaveURL(/\/events\/[0-9a-f-]+$/)
      eventId = new URL(lead.url()).pathname.split('/').pop() ?? ''
      expect(eventId).not.toBe('')

      await expectNotification(coordinator, eventName, /assigned/i)
    })

    await test.step('3. Coordinator moves the event Under Review, requests a venue, and Venue Staff approve it', async () => {
      await coordinator.goto(`/events/${eventId}`)
      await coordinator.getByLabel('Status').selectOption('Under Review')
      await coordinator.getByLabel('Action details').fill('J1 review started.')
      await coordinator.getByRole('button', { name: 'Save progress' }).click()
      await expect(coordinator.getByText('Event progress updated successfully.')).toBeVisible()

      const form = coordinator.locator('form.venue-booking-form')
      const option = form.locator('option').filter({ hasText: venue.venueName }).first()
      const venueId = await option.getAttribute('value')
      if (!venueId) throw new Error(`The fixture venue "${venue.venueName}" was not available.`)
      await form.getByRole('combobox', { name: /^Venue/ }).selectOption(venueId)
      await form.getByLabel('Booking start').fill(window.start)
      await form.getByLabel('Booking end').fill(window.end)
      await form.getByRole('button', { name: 'Submit venue booking' }).click()
      await expect(form.getByText(new RegExp(`${venue.venueName} booking request submitted`))).toBeVisible()

      const venueStaff = await openAs(browser, users.venueStaff)
      await venueStaff.goto('/venue-requests')
      const region = venueStaff.getByRole('region', { name: `${eventName} venue requests` })
      const row = region.getByRole('row').filter({ hasText: venue.venueName })
      await expect(async () => {
        await expect(venueStaff.getByText('Loading venue requests...', { exact: true })).toBeHidden({ timeout: 45_000 })
        if (await row.getByRole('button', { name: 'Review', exact: true }).isVisible()) return
        await venueStaff.getByRole('button', { name: 'Refresh requests' }).click()
        await expect(row.getByRole('button', { name: 'Review', exact: true })).toBeVisible({ timeout: 45_000 })
      }).toPass({ timeout: 90_000, intervals: [3_000, 5_000] })
      await row.getByRole('button', { name: 'Review' }).click()
      await venueStaff.getByRole('dialog').getByRole('button', { name: 'Approve', exact: true }).click()
      await expect(venueStaff.getByText('Venue request approved.')).toBeVisible()
      await expect(row).toContainText('Approved')
    })

    await test.step('4. Coordinator requests equipment and Technical Support approve and reserve it', async () => {
      await coordinator.goto('/equipment-requests/new')
      await coordinator.getByLabel(/^Event/).selectOption(eventId)
      const equipmentRow = coordinator.getByRole('group', { name: 'Equipment row' })
      await equipmentRow.getByLabel(/^Equipment/).selectOption({ label: `${TABLE_NAME} (Table)` })
      await equipmentRow.getByLabel(/^Quantity/).fill('2')
      await equipmentRow.getByRole('button', { name: 'Add this equipment' }).click()
      await coordinator.getByRole('button', { name: 'Submit request' }).click()
      await expect(coordinator.getByText(`Requested 1 equipment item for ${eventName}.`)).toBeVisible()

      const support = await openAs(browser, users.techSupport)
      await support.goto('/equipment-requests')
      const region = support.getByRole('region', { name: `${eventName} equipment requests` })
      const row = region.getByRole('row').filter({ hasText: TABLE_NAME })
      await expect(row).toContainText('2')
      await row.getByRole('button', { name: 'Approve', exact: true }).click()
      await expect(row).toContainText('Approved')
    })

    await test.step('5. Coordinator approves the event', async () => {
      await coordinator.goto(`/events/${eventId}`)
      await coordinator.getByLabel('Status').selectOption('Approved')
      await coordinator.getByLabel('Action details').fill('Venue and equipment are confirmed.')
      await coordinator.getByRole('button', { name: 'Save progress' }).click()
      await expect(coordinator.locator('.event-card-header .status-badge').first()).toHaveText('Approved')
    })

    const safetyOfficer = await openAs(browser, users.safetyOfficer)
    const placementNotes = 'Tables are placed clear of the emergency exits.'
    const crowdNotes = 'Attendees enter through the main doors and leave through the marked side exits.'
    const approvalRemarks = 'J1 safety arrangements reviewed and approved.'

    await test.step('6. Coordinator submits safety notes; the Officer sees one review with the approved arrangements', async () => {
      await coordinator.getByLabel('Equipment placement notes').fill(placementNotes)
      await coordinator.getByLabel('Expected crowd movement notes').fill(crowdNotes)
      await coordinator.getByRole('button', { name: 'Submit for safety check' }).click()
      await expect(coordinator.locator('.event-card-header .status-badge').first()).toHaveText('Pending Safety Check')

      for (let attempt = 0; attempt < 3; attempt++) {
        const [response] = await Promise.all([
          safetyOfficer.waitForResponse((response) =>
            new URL(response.url()).pathname === '/safety-checks/queue'
            && response.request().method() === 'GET'),
          attempt === 0
            ? safetyOfficer.goto('/safety-checks')
            : safetyOfficer.getByRole('button', { name: 'Refresh safety checks' }).click(),
        ])
        if (response.ok()) break
        const failure = `Safety queue returned HTTP ${response.status()}: ${await response.text()}`
        if (![502, 503, 504].includes(response.status()) || attempt === 2) throw new Error(failure)
        console.warn(`${failure} Retrying through Refresh safety checks.`)
        await expect(safetyOfficer.getByRole('button', { name: 'Refresh safety checks' })).toBeEnabled()
      }
      const reviewCard = safetyOfficer.getByRole('button').filter({ hasText: eventName })
      await expect(reviewCard).toHaveCount(1)
      await reviewCard.click()
      await expect(safetyOfficer.getByRole('heading', { name: 'Safety review information' })).toBeVisible()
      await expect(safetyOfficer.getByRole('heading', { name: venue.venueName })).toBeVisible()
      const equipment = safetyOfficer.locator('.safety-review .event-detail').filter({
        has: safetyOfficer.getByText('Table · quantity 2', { exact: true }),
      })
      await expect(equipment).toHaveCount(1)
      await expect(equipment).toContainText(TABLE_NAME)
      await expect(safetyOfficer.getByText(placementNotes, { exact: true })).toBeVisible()
      await expect(safetyOfficer.getByText(crowdNotes, { exact: true })).toBeVisible()
    })

    await test.step('7. Safety Officer approves; event is Confirmed and the safety decision is audited', async () => {
      await safetyOfficer.getByLabel('Remarks').fill(approvalRemarks)
      await safetyOfficer.getByRole('button', { name: 'Approve', exact: true }).click()
      await safetyOfficer.getByRole('button', { name: 'Yes, approve' }).click()
      await expect(safetyOfficer.locator('.event-card-header .status-badge').first()).toHaveText('Confirmed')

      const audit = await coordinator.evaluate(async (id) => {
        const storedSession = localStorage.getItem('session')
        if (!storedSession) throw new Error('The Coordinator session is missing.')
        const session = JSON.parse(storedSession) as { accessToken: string }
        const response = await fetch(
          `http://localhost:5012/safety-checks/feedback?eventId=${encodeURIComponent(id)}`,
          { headers: { Authorization: `Bearer ${session.accessToken}` } },
        )
        return {
          status: response.status,
          body: await response.json() as { safetyChecks: { status: string; remarks: string | null; decidedBy: string | null; decidedAt: string | null }[] },
        }
      }, eventId)
      expect(audit.status).toBe(200)
      expect(audit.body.safetyChecks).toHaveLength(1)
      expect(audit.body.safetyChecks[0]).toMatchObject({
        status: 'Safety Approved', remarks: approvalRemarks, decidedBy: users.safetyOfficer.id,
      })
      expect(audit.body.safetyChecks[0].decidedAt).toBeTruthy()
    })

    const attendee = await openAs(browser, users.attendee)

    await test.step('8. Attendee registers; registration persists after a page refresh', async () => {
      await attendee.goto('/events/browse')
      const eventCard = attendee.getByRole('button').filter({ hasText: eventName })
      await expect(eventCard).toHaveCount(1)
      await eventCard.click()
      await attendee.getByRole('button', { name: 'Register', exact: true }).click()
      await attendee.getByRole('button', { name: 'Submit registration' }).click()
      await expect(attendee.getByRole('status')).toContainText(/registration confirmed/i)

      await attendee.reload()
      const refreshedCard = attendee.getByRole('button').filter({ hasText: eventName })
      await expect(refreshedCard).toHaveCount(1)
      await refreshedCard.click()
      await expect(attendee.locator('.event-facts')).toContainText('1 / 50')
      await attendee.goto('/registrations')
      await attendee.reload()
      const registrationCard = attendee.getByRole('button').filter({ hasText: eventName })
      await expect(registrationCard).toHaveCount(1)
      await expect(registrationCard).toContainText('Confirmed')
      await registrationCard.click()
      await expect(attendee.locator('.event-detail').filter({ hasText: 'Email' })).toContainText(users.attendee.email)
    })

    await test.step('9. Organiser and Coordinator see the same registration total; Attendee receives confirmation', async () => {
      await expectNotification(attendee, eventName, /confirm/i)

      await organiser.goto('/my-events')
      const organiserCard = organiser.getByRole('button').filter({ hasText: eventName })
      await expect(organiserCard).toContainText('1 registration')
      await organiser.goto(`/events/${eventId}`)
      await expect(organiser.locator('.event-detail').filter({ hasText: 'Total registrations' })).toContainText('1')
      await expect(organiser.getByRole('row').filter({ hasText: users.attendee.email })).toBeVisible()

      await coordinator.goto(`/events/${eventId}`)
      await expect(coordinator.locator('.event-detail').filter({ hasText: 'Total registrations' })).toContainText('1')
      await expect(coordinator.getByRole('row').filter({ hasText: users.attendee.email })).toBeVisible()
    })
  })
})
