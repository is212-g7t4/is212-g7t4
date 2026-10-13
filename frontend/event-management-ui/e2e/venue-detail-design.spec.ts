import { allUsers, asUser, json, mock, test, expect, users, venues } from './fixtures'

// All backend traffic is intercepted. Screenshots contain synthetic demo fixtures only.
for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  test(`Venue details visual hierarchy and closure disclosure at ${viewport.width}px (mock fixtures)`, async ({ page, mockApi }, testInfo) => {
    await page.setViewportSize(viewport)
    await mockApi(page)
    await asUser(page, users.venueStaff.user_id)
    await mock(page, 'user', '/users', route => json(route, { users: allUsers.map(user => ({ ...user, username: `Demo ${user.role}` })) }))
    await mock(page, 'venue', '/venues', route => json(route, { venues }))
    await mock(page, 'venue', `/venues/${venues[0].id}`, route => json(route, { venue: venues[0] }))
    await mock(page, 'availability', '/venue-holds', route => json(route, { holds: [] }))
    let populated = false
    await mock(page, 'venueBooking', '/venue-closures', route => json(route, { closures: populated ? [{
      closureId: 'demo-closure-001', venueId: venues[0].id,
      startDateTime: '2026-12-01T09:00:00+08:00', endDateTime: '2026-12-02T18:00:00+08:00',
      reason: 'Scheduled air-conditioning maintenance', createdBy: 'Demo Venue Staff', createdAt: '2026-10-13T10:00:00+08:00',
    }] : [], nextCursor: null }))
    await page.goto('/venues')
    await page.getByRole('button', { name: 'View details for Grand Hall' }).click()
    await expect(page.getByText('No recorded closures.')).toBeVisible()
    const disclosure = page.getByRole('button', { name: 'Record temporary closure' })
    const refresh = page.getByRole('button', { name: 'Refresh closures' })
    const screenshot = async (name: string) => {
      await page.mouse.move(0, 0)
      await page.screenshot({ animations: 'disabled', path: process.env.VENUE_SCREENSHOT_DIR ? `${process.env.VENUE_SCREENSHOT_DIR}/${viewport.width}-${name}.png` : testInfo.outputPath(`${name}.png`), fullPage: true })
    }
    await screenshot('empty-collapsed')
    const styles = await disclosure.evaluate(el => { const s = getComputedStyle(el); return { bg: s.backgroundColor, color: s.color, cursor: s.cursor } })
    expect(styles.bg).not.toBe('rgba(0, 0, 0, 0)')
    expect(styles.color).toBe('rgb(255, 255, 255)')
    expect(styles.cursor).toBe('pointer')
    // WCAG text contrast, calculated from the actual rendered button colors.
    const luminance = (color: string) => {
      const channels = color.match(/\d+/g)!.slice(0, 3).map(Number).map(n => n / 255).map(n => n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4)
      return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
    }
    const contrast = (luminance(styles.color) + 0.05) / (luminance(styles.bg) + 0.05)
    expect(contrast).toBeGreaterThanOrEqual(4.5)
    expect(await refresh.evaluate(el => getComputedStyle(el).borderTopStyle)).toBe('solid')
    expect(await refresh.evaluate(el => parseFloat(getComputedStyle(el).borderTopWidth))).toBeGreaterThanOrEqual(1)
    const buttonBounds = []
    for (const button of [disclosure, refresh]) {
      const bounds = (await button.boundingBox())!
      buttonBounds.push(bounds)
      expect(bounds.height).toBeGreaterThanOrEqual(44)
      expect(bounds.x).toBeGreaterThanOrEqual(0)
      expect(bounds.x + bounds.width).toBeLessThanOrEqual(viewport.width)
    }
    await disclosure.hover()
    await expect.poll(() => disclosure.evaluate(el => getComputedStyle(el).backgroundColor)).not.toBe(styles.bg)
    await page.mouse.move(0, 0)
    await page.keyboard.press('Tab')
    await disclosure.focus()
    await expect(disclosure).toBeFocused()
    expect(await disclosure.evaluate(el => getComputedStyle(el).outlineStyle)).toBe('solid')
    await disclosure.press('Enter')
    await expect(disclosure).toHaveAttribute('aria-expanded', 'true')
    await expect(page.getByRole('form', { name: 'Record temporary closure' })).toBeVisible()
    await expect(page.getByLabel('Closure start (SGT)')).toBeVisible()
    for (const label of ['Closure start (SGT)', 'Closure end (SGT)', 'Reason']) {
      const control = page.getByLabel(label, { exact: true })
      await expect(control).toHaveAttribute('required', '')
      const field = control.locator('..')
      await expect(field.locator('.required-marker')).toHaveText('*')
      await expect(field.locator('.required-marker')).toHaveCSS('color', 'rgb(179, 38, 30)')
    }
    const venueField = page.getByLabel('Closure venue', { exact: true })
    await expect(venueField).toHaveAttribute('readonly', '')
    await expect(venueField).toHaveValue('Grand Hall')
    expect(await venueField.evaluate(el => getComputedStyle(el).backgroundColor)).not.toBe('rgb(255, 255, 255)')
    await expect(page.getByText('* Required fields', { exact: true })).toBeVisible()
    const reason = page.getByLabel('Reason', { exact: true })
    await reason.fill('Draft survives collapse')
    await screenshot('empty-expanded')
    await disclosure.click()
    await expect(disclosure).toHaveAttribute('aria-expanded', 'false')
    await expect(reason).toHaveCount(0)
    populated = true
    await refresh.click()
    await expect(page.getByText('Scheduled air-conditioning maintenance', { exact: true })).toBeVisible()
    await screenshot('populated-collapsed')
    await disclosure.click()
    await expect(reason).toHaveValue('Draft survives collapse')
    await screenshot('populated-expanded')
    const reasonBounds = (await reason.boundingBox())!
    const saveBounds = (await page.getByRole('button', { name: 'Save closure' }).boundingBox())!
    expect(saveBounds.y).toBeGreaterThanOrEqual(reasonBounds.y + reasonBounds.height)
    const overflow = await page.evaluate(() => [...document.querySelectorAll('*')].filter(el => el.getBoundingClientRect().right > innerWidth + 1).map(el => ({ tag: el.tagName, class: el.className, width: el.getBoundingClientRect().width })))
    expect(overflow, 'elements overflow viewport').toEqual([])
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width)
    await testInfo.attach('button-layout-and-contrast', { body: JSON.stringify({ viewport, styles, contrast, buttonBounds, reasonBounds, saveBounds }), contentType: 'application/json' })
  })
}
