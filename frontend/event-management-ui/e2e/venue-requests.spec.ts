import { allUsers, asUser, json, mock, test, expect, users } from './fixtures'

// Safety revision AC2/AC4 (mocked browser): Venue Staff re-review the affected booking
// while its unaffected Approved sibling remains reviewed on desktop and mobile.
for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  for (const decision of ['Approved', 'Rejected'] as const) {
    test(`Venue Staff can mark safety-revision booking ${decision} at ${viewport.width}px`, async ({ page, mockApi }, testInfo) => {
      await mockApi(page)
      await page.setViewportSize(viewport)
      await asUser(page, users.venueStaff.user_id)
      await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
      let status = 'Pending Review'
      const booking = () => ({ id: 'b1', eventId: 'e1', venueId: 'v1', venueName: 'Grand Hall',
        requestedStartTime: '2026-11-07T10:00:00', requestedEndTime: '2026-11-07T16:00:00', requiredCapacity: 100,
        venueRequirements: 'Keep exit routes clear.', status, reviewedBy: null,
        safetyFeedback: { reason: 'Emergency access blocked.', requestedChanges: ['Move the stage away from the exit.'] } })
      await mock(page, 'venueBooking', '/booking-requests', (route) => json(route, { events: [{
        eventId: 'e1', eventName: 'Community Fair', eventStatus: 'Safety Changes Requested', coordinatorId: users.coordinator.user_id,
        bookings: [booking(), { ...booking(), id: 'b2', venueName: 'Unaffected Room', status: 'Approved', safetyFeedback: null }],
      }] }))
      // SCRUM-29: Review opens the request with its event and venue details first.
      await mock(page, 'venueBooking', '/booking-requests/b1', (route) => json(route, {
        booking: { ...booking(), awaitingReview: true, occupiedFrom: '2026-11-07T09:30:00', occupiedTo: '2026-11-07T16:45:00' },
        event: { id: 'e1', eventName: 'Community Fair', status: 'Safety Changes Requested', coordinatorId: users.coordinator.user_id,
          preferredStartDate: '2026-11-07T09:00:00', preferredEndDate: '2026-11-07T17:00:00', expectedAttendance: '100',
          venueRequirements: 'Stage', accessibilityNeeds: null },
        venue: { id: 'v1', name: 'Grand Hall', capacity: 200, status: 'Available', setupTimeMinutes: 30, turnaroundTimeMinutes: 45 },
        canDecide: true, decisionBlockedReason: null,
      }))
      await mock(page, 'venueBooking', '/booking-requests/b1/review', (route) => {
        expect(route.request().postDataJSON()).toEqual(decision === 'Rejected'
          ? { status: decision, reviewedBy: users.venueStaff.user_id, rejectionReason: 'Exit still blocked.' }
          : { status: decision, reviewedBy: users.venueStaff.user_id })
        status = decision
        return json(route, booking())
      })
      await page.goto('/venue-requests')
      if (viewport.width >= 768) await expect(page.getByRole('navigation').getByRole('button', { name: 'Venue requests', exact: true })).toBeVisible()
      await expect(page.getByRole('heading', { name: 'Venue requests', exact: true }).last()).toBeVisible()
      const row = page.getByRole('row').filter({ hasText: 'Grand Hall' })
      await expect(row.getByRole('button', { name: 'Review', exact: true })).toBeVisible()
      const unaffected = page.getByRole('row').filter({ hasText: 'Unaffected Room' })
      await expect(unaffected.getByRole('button', { name: 'Review', exact: true })).toHaveCount(0)
      const scroll = page.getByRole('region', { name: 'Community Fair venue requests' })
      expect(await scroll.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true)
      await scroll.evaluate((element) => { element.scrollLeft = element.scrollWidth })
      await expect(row.getByText('Move the stage away from the exit.')).toBeVisible()
      await page.screenshot({ path: testInfo.outputPath(`venue-requests-${viewport.width}-${decision}.png`), fullPage: true })
      await row.getByRole('button', { name: 'Review', exact: true }).click()
      const dialog = page.getByRole('dialog', { name: 'Grand Hall for Community Fair' })
      if (decision === 'Approved') {
        await dialog.getByRole('button', { name: 'Approve', exact: true }).click()
      } else {
        await dialog.getByRole('button', { name: 'Reject', exact: true }).click()
        await page.getByLabel(/Reason for rejection/).fill('Exit still blocked.')
        await page.getByRole('button', { name: 'Confirm rejection' }).click()
      }
      await expect(row.locator('.status-badge')).toHaveText(decision)
      await expect(unaffected.locator('.status-badge')).toHaveText('Approved')
    })
  }
}

test('coordinators cannot open the Venue Staff review page', async ({ page, mockApi }) => {
  await mockApi(page)
  await asUser(page, users.coordinator.user_id)
  await mock(page, 'user', '/users', (route) => json(route, { users: allUsers }))
  await page.goto('/venue-requests')
  await expect(page.getByText('Venue requests are visible only to Venue Staff.')).toBeVisible()
})