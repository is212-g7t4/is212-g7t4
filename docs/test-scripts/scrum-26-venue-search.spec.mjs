import { chromium } from 'playwright'
import fs from 'node:fs'

const BASE = 'http://localhost:5174'
const SHOTS = '/tmp/s26/shots'
fs.mkdirSync(SHOTS, { recursive: true })

const results = []
const record = (n, name, pass, notes = '') => {
  results.push({ n, name, pass, notes })
  console.log(`${pass ? 'PASS' : 'FAIL'}  ${n}. ${name}${notes ? ` — ${notes}` : ''}`)
}

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1360, height: 1000 } })
const page = await ctx.newPage()

// Track every /venue-search request so steps 2 and 4 can assert on them.
const calls = []
const started = new Map()
page.on('request', (req) => {
  if (req.url().includes('/venue-search')) started.set(req, Date.now())
})
page.on('response', (res) => {
  const t0 = started.get(res.request())
  if (t0 !== undefined) calls.push({ url: res.url(), status: res.status(), ms: Date.now() - t0 })
})

const shot = (name) => page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true })
const text = () => page.locator('.main-content').innerText()

async function pickRole(role) {
  await page.goto(BASE, { waitUntil: 'networkidle' })
  const select = page.locator('select[aria-label="Select active user"]')
  await select.waitFor()
  const option = page.locator(`select[aria-label="Select active user"] option`, { hasText: `— ${role}` }).first()
  await select.selectOption(await option.getAttribute('value'))
  await page.waitForTimeout(300)
}

async function fillSearch({ date, start, end, attendance }) {
  const set = async (label, value) => {
    if (value === undefined) return
    await page.locator('label.field', { hasText: label }).locator('input').first().fill(value)
  }
  await set('Date', date)
  await set('Start time', start)
  await set('End time', end)
  await set('Expected attendance', attendance)
}

const search = () => page.getByRole('button', { name: /Search/ }).click()

// ---------------------------------------------------------------- Step 1
await pickRole('Event Coordinator')
await page.getByRole('button', { name: 'Find a venue' }).click()
await page.waitForURL('**/venue-search')
const body = await text()
const labels = ['Date', 'Start time', 'End time', 'Expected attendance', 'Minimum capacity', 'Location', 'Supported layout', 'Required facilities', 'Accessibility requirements']
const missingLabels = labels.filter((l) => !body.includes(l))
const requiredMarks = await page.locator('label.field:has(.required)').count()
record(1, 'All criteria present; four marked required', missingLabels.length === 0 && requiredMarks === 4,
  `missing=[${missingLabels}] requiredAsterisks=${requiredMarks}`)
await shot('01-form')

// ---------------------------------------------------------------- Step 2
calls.length = 0
await search()
await page.waitForTimeout(600)
const alert2 = await page.locator('[role="alert"]').innerText()
record(2, 'Empty search lists all four required fields, sends nothing',
  alert2.includes('Date') && alert2.includes('Start time') && alert2.includes('End time') &&
  alert2.includes('Expected attendance') && calls.length === 0,
  `msg="${alert2}" requests=${calls.length}`)
await shot('02-required-message')

// ---------------------------------------------------------------- Step 3
await fillSearch({ date: '2026-11-10' })
calls.length = 0
await search()
await page.waitForTimeout(600)
const alert3 = await page.locator('[role="alert"]').innerText()
record(3, 'With date filled, message lists only what is still missing',
  !alert3.includes('Date,') && alert3.includes('Start time') && alert3.includes('Expected attendance') && calls.length === 0,
  `msg="${alert3}" requests=${calls.length}`)

// ---------------------------------------------------------------- Step 4
calls.length = 0
await fillSearch({ date: '2026-11-10', start: '09:00', end: '12:00', attendance: '120' })
await search()
await page.locator('button.venue-card').first().waitFor({ timeout: 10000 })
const ms = calls.at(-1)?.ms ?? -1
const cards4 = await page.locator('button.venue-card').allInnerTexts()
record(4, 'Results appear, /venue-search under 3000 ms', cards4.length > 0 && ms > 0 && ms < 3000,
  `${cards4.length} results in ${ms.toFixed(0)} ms`)
await shot('04-results')

// ---------------------------------------------------------------- Step 5
const first = page.locator('button.venue-card').first()
const card = await first.innerText()
const hasBadge = await first.locator('.venue-status').count()
const hasChips = await first.locator('.chip').count()
record(5, 'Each card shows details + availability badge',
  /people/.test(card) && hasBadge === 1 && hasChips > 0 && card.split('\n').length >= 5,
  `badge=${hasBadge} chips=${hasChips}`)

// ---------------------------------------------------------------- Step 6
const names4 = cards4.map((c) => c.split('\n')[0])
record(6, 'Grand Ballroom (Approved booking) and Auditorium (maintenance) excluded',
  !names4.includes('Grand Ballroom') && !names4.includes('Auditorium'), `listed=[${names4}]`)

// ---------------------------------------------------------------- Step 7
await fillSearch({ date: '2026-11-22', start: '10:00', end: '16:00', attendance: '100' })
await search()
await page.locator('button.venue-card').first().waitFor({ timeout: 10000 })
const pending = page.locator('button.venue-card', { hasText: 'Rooftop Garden' }).locator('.venue-status')
const pendingText = await pending.innerText()
const tooltip = await pending.getAttribute('title')
record(7, 'Rooftop Garden shows Pending request with an explanatory tooltip',
  pendingText.trim() === 'Pending request' && /waiting for review/.test(tooltip || ''),
  `badge="${pendingText.trim()}" title="${tooltip}"`)
await shot('07-pending-badge')

// ---------------------------------------------------------------- Step 8
await fillSearch({ date: '2026-11-10', start: '09:00', end: '12:00', attendance: '120' })
await page.locator('label.field', { hasText: 'Location' }).locator('input').fill('Level 12')
await page.locator('label.field', { hasText: 'Supported layout' }).locator('select').selectOption('banquet')
await page.locator('label.checkbox-option', { hasText: 'outdoor' }).locator('input').check()
await search()
await page.locator('button.venue-card').first().waitFor({ timeout: 10000 })
const names8 = (await page.locator('button.venue-card').allInnerTexts()).map((c) => c.split('\n')[0])
record(8, 'Location + layout + facility narrows to the rooftop venues',
  names8.length === 2 && names8.every((n) => n.startsWith('Rooftop')), `listed=[${names8}]`)
await shot('08-filtered')

// ---------------------------------------------------------------- Step 9
await page.locator('label.checkbox-option', { hasText: 'Hearing loop' }).locator('input').check()
await fillSearch({ date: '2026-11-10', start: '09:00', end: '12:00', attendance: '1000' })
await search()
await page.waitForTimeout(1500)
const empty = await text()
record(9, 'No matches shows the AC5 message',
  empty.includes('No venues are available for the selected date, time and requirements.'),
  '')
await shot('09-no-matches')

// ---------------------------------------------------------------- Step 10
await page.getByRole('button', { name: 'Clear all' }).click()
await page.waitForTimeout(400)
const vals = await page.locator('.venue-search-form input').evaluateAll((els) =>
  els.filter((e) => e.type !== 'checkbox').map((e) => e.value))
const boxes = await page.locator('.venue-search-form input[type=checkbox]:checked').count()
const layoutVal = await page.locator('label.field', { hasText: 'Supported layout' }).locator('select').inputValue()
const after = await text()
record(10, 'Clear all empties every field, results, messages and the URL query',
  vals.every((v) => v === '') && boxes === 0 && layoutVal === '' &&
  !after.includes('No venues are available') && page.url() === `${BASE}/venue-search`,
  `inputs=${JSON.stringify(vals)} checked=${boxes} url=${page.url()}`)
await shot('10-cleared')

// ---------------------------------------------------------------- Step 11
await fillSearch({ date: '2026-11-10', start: '09:00', end: '12:00', attendance: '120' })
await search()
await page.locator('button.venue-card').first().waitFor({ timeout: 10000 })
const urlWithQuery = page.url()
const beforeBack = (await page.locator('button.venue-card').allInnerTexts()).map((c) => c.split('\n')[0])
await page.locator('button.venue-card').first().click()
await page.waitForTimeout(1200)
const onDetail = /\/venues\/[^/]+$/.test(page.url())
await page.goBack()
await page.locator('button.venue-card').first().waitFor({ timeout: 10000 })
const afterBack = (await page.locator('button.venue-card').allInnerTexts()).map((c) => c.split('\n')[0])
const dateBack = await page.locator('label.field', { hasText: 'Date' }).locator('input').inputValue()
record(11, 'Back from a venue detail page restores the same criteria and results',
  onDetail && dateBack === '2026-11-10' && JSON.stringify(beforeBack) === JSON.stringify(afterBack),
  `detail=${onDetail} date=${dateBack} same=${JSON.stringify(beforeBack) === JSON.stringify(afterBack)}`)
await shot('11-back')

// ---------------------------------------------------------------- Step 12
const roleResults = []
for (const role of ['Venue Staff', 'Event Organiser', 'Technical Support']) {
  await pickRole(role)
  const navCount = await page.getByRole('button', { name: 'Find a venue' }).count()
  await page.goto(`${BASE}/venue-search`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(500)
  const t = await text()
  roleResults.push({ role, navCount, notice: t.includes('Venue search is available to Event Coordinators.') })
  if (role === 'Venue Staff') await shot('12-venue-staff-notice')
}
record(12, 'Other roles see the notice and get no nav item',
  roleResults.every((r) => r.navCount === 0 && r.notice), JSON.stringify(roleResults))

// ---------------------------------------------------------------- Step 13 (availability stopped by the shell)
await pickRole('Event Coordinator')
await page.goto(`${BASE}/venue-search`, { waitUntil: 'networkidle' })
if (process.env.AVAILABILITY_DOWN === '1') {
  await fillSearch({ date: '2026-11-10', start: '09:00', end: '12:00', attendance: '120' })
  await search()
  await page.waitForTimeout(3000)
  const t = await text()
  record(13, 'Venue Availability down: error message, no crash',
    t.includes('Unable to search venues right now.') && !t.includes('No venues are available'), '')
  await shot('13-downstream-error')
} else {
  // ------------------------------------------------------------- Step 14
  await fillSearch({ date: '2026-11-10', start: '09:00', end: '12:00', attendance: '120' })
  await search()
  await page.locator('button.venue-card').first().waitFor({ timeout: 10000 })
  const n = await page.locator('button.venue-card').count()
  record(14, 'After restart, results come back without a page reload', n > 0, `${n} results`)
  await shot('14-recovered')
}

await browser.close()
fs.writeFileSync('/tmp/s26/results.json', JSON.stringify(results, null, 2))
console.log(`\n${results.filter((r) => r.pass).length}/${results.length} passed`)
process.exit(results.every((r) => r.pass) ? 0 : 1)
