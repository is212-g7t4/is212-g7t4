/** SCRUM-45 full story: As an Event Organiser, I want an in-app notification
 * when the Lead Coordinator approves/rejects my event request, so that I know
 * the outcome and who coordinates my event. AC2/AC3/DR9, unmocked opt-in harness.
 * Invoked by the isolated Python integration fixture, NOT the mocked e2e suite.
 */
import { chromium, expect } from '@playwright/test'
import { writeFile } from 'node:fs/promises'

const base = process.env.SCRUM45_FRONTEND
const event = process.env.SCRUM45_EVENT
const artifacts = process.env.SCRUM45_ARTIFACTS
const reason = 'Browser journey requires a safety plan.'
const browser = await chromium.launch({ headless: true })
const context = await browser.newContext()
const page = await context.newPage()
const errors = []
const requests = []
page.on('pageerror', error => errors.push(error.message))
page.on('requestfailed', request => errors.push(`${request.method()} ${request.url()} ${request.failure()?.errorText}`))
page.on('response', response => {
  requests.push({ status: response.status(), method: response.request().method(), url: response.url() })
  if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`)
})
try {
  await context.addInitScript(id => localStorage.setItem('activeUserId', id), process.env.SCRUM45_LEAD)
  await page.goto(`${base}/requests/review`)
  await expect(page.getByRole('heading', { name: 'Community Workshop', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Reject Request', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Reject event request?' })
  await dialog.getByLabel('Reason for rejection').fill(reason)
  await dialog.getByRole('button', { name: 'Confirm rejection' }).click()
  await expect(page.getByRole('dialog', { name: 'Event Request Rejected' })).toContainText(reason)
  // Same real UI, new page load under the existing demo identity mechanism.
  // Clear the Lead startup script by using a fresh organiser context.
  const organiser = await browser.newContext()
  await organiser.addInitScript(id => localStorage.setItem('activeUserId', id), process.env.SCRUM45_ORGANISER)
  const own = await organiser.newPage()
  own.on('pageerror', error => errors.push(error.message))
  own.on('requestfailed', request => errors.push(`${request.method()} ${request.url()} ${request.failure()?.errorText}`))
  own.on('response', response => {
    requests.push({ status: response.status(), method: response.request().method(), url: response.url() })
    if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`)
  })
  await own.goto(`${base}/notifications`)
  // Delivery is asynchronous; use the existing refresh control, not fake timers.
  await expect(async () => {
    await own.getByRole('button', { name: 'Refresh notifications', exact: true }).click()
    await expect(own.getByText(`Community Workshop was rejected: ${reason}`, { exact: true })).toBeVisible({ timeout: 1000 })
  }).toPass({ timeout: 20000 })
  await expect(own.getByRole('button', { name: 'Notifications, 1 unread', exact: true })).toBeVisible()
  await own.getByRole('link', { name: 'Open notification' }).click()
  await expect(own).toHaveURL(`${base}/events/${event}`)
  await expect(own.getByRole('heading', { name: 'Community Workshop', exact: true })).toBeVisible()
  await expect(own.getByRole('heading', { name: 'Rejection reason', exact: true })).toBeVisible()
  await expect(own.getByText(reason, { exact: true })).toBeVisible()
  await expect(own.getByRole('button', { name: 'Notifications, 0 unread', exact: true })).toBeVisible()
  await own.screenshot({ path: `${artifacts}/organiser-linked-details.png`, fullPage: true })
  expect(errors).toEqual([])
  console.log('PASS: real Lead rejection -> PostgreSQL/outbox worker -> RabbitMQ/consumer -> organiser inbox -> read linked details; no failed HTTP requests')
  await organiser.close()
} catch (error) {
  await page.screenshot({ path: `${artifacts}/browser-failure.png`, fullPage: true })
  throw error
} finally {
  await writeFile(`${artifacts}/browser-requests.json`, JSON.stringify({ requests, errors }, null, 2))
  await browser.close()
}
