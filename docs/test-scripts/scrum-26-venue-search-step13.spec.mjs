import { chromium } from 'playwright'
const BASE = 'http://localhost:5174'
const browser = await chromium.launch()
const page = await (await browser.newContext({ viewport: { width: 1360, height: 1000 } })).newPage()
const errors = []
page.on('pageerror', (e) => errors.push(String(e)))

await page.goto(BASE, { waitUntil: 'networkidle' })
const select = page.locator('select[aria-label="Select active user"]')
await select.waitFor()
await select.selectOption(await page.locator('select[aria-label="Select active user"] option', { hasText: '— Event Coordinator' }).first().getAttribute('value'))
await page.waitForTimeout(300)
await page.goto(`${BASE}/venue-search`, { waitUntil: 'networkidle' })

const set = (label, value) => page.locator('label.field', { hasText: label }).locator('input').first().fill(value)
await set('Date', '2026-11-10'); await set('Start time', '09:00')
await set('End time', '12:00'); await set('Expected attendance', '120')

const statuses = []
page.on('response', (r) => { if (r.url().includes('/venue-search')) statuses.push(r.status()) })
await page.getByRole('button', { name: /Search/ }).click()
await page.waitForTimeout(4000)

const t = await page.locator('.main-content').innerText()
const shownError = t.includes('Unable to search venues right now.')
const formAlive = await page.locator('.venue-search-form').isVisible()
const noResults = (await page.locator('button.venue-card').count()) === 0
const pass = shownError && formAlive && noResults && errors.length === 0
console.log(`${pass ? 'PASS' : 'FAIL'}  13. Venue Availability down: error message, no crash`)
console.log(`      http=${statuses} errorShown=${shownError} formStillUsable=${formAlive} cards=${noResults ? 0 : 'some'} jsErrors=${errors.length}`)
await page.screenshot({ path: '/tmp/s26/shots/13-downstream-error.png', fullPage: true })
await browser.close()
process.exit(pass ? 0 : 1)
