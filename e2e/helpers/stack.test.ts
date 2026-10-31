import assert from 'node:assert/strict'
import { mock, test } from 'node:test'
import { chromium } from '@playwright/test'
import { openAs, users } from './stack'

test('role sessions are injected only on the configured app origin, without blank-page errors', async (t) => {
  const previousOrigin = process.env.FRONTEND_URL
  const previousPassword = process.env.E2E_PASSWORD
  process.env.E2E_PASSWORD = 'local-test-password'
  t.after(() => {
    mock.restoreAll()
    if (previousOrigin === undefined) delete process.env.FRONTEND_URL
    else process.env.FRONTEND_URL = previousOrigin
    if (previousPassword === undefined) delete process.env.E2E_PASSWORD
    else process.env.E2E_PASSWORD = previousPassword
  })
  mock.method(globalThis, 'fetch', async (_input: unknown, init: RequestInit) => {
    const { email } = JSON.parse(String(init.body)) as { email: string }
    const actor = Object.values(users).find((user) => user.email === email)
    assert.ok(actor)
    return Response.json({
      accessToken: 'test-token', expiresAt: 4_000_000_000,
      user: { user_id: actor.id, username: actor.role, email: actor.email, role: actor.role },
    })
  })

  const browser = await chromium.launch()
  t.after(() => browser.close())
  const errors: string[] = []
  browser.on('context', (context) => {
    context.on('page', (page) => page.on('pageerror', (error) => errors.push(error.message)))
  })

  for (const [frontendUrl, actor] of [
    [undefined, users.coordinator],
    ['http://localhost:5188/custom-path', users.attendee],
  ] as const) {
    if (frontendUrl === undefined) delete process.env.FRONTEND_URL
    else process.env.FRONTEND_URL = frontendUrl
    const origin = new URL(frontendUrl ?? 'http://localhost:5174').origin
    const page = await openAs(browser, actor)
    try {
      assert.equal(page.url(), 'about:blank')
      await page.context().route('http://**/*', (route) => route.fulfill({
        contentType: 'text/html', body: '<!doctype html><title>Session test</title>',
      }))
      await page.goto(`${origin}/events`)
      const readSession = () => page.evaluate(() => JSON.parse(localStorage.getItem('session') ?? 'null'))
      assert.equal((await readSession()).user.id, actor.id)
      await page.reload()
      assert.equal((await readSession()).user.id, actor.id)

      await page.goto('http://127.0.0.1:5199/other-origin')
      assert.equal(await readSession(), null)
      assert.deepEqual(errors, [])
    } finally {
      await page.context().close()
    }
  }
})
