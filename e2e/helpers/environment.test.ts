import assert from 'node:assert/strict'
import { test } from 'node:test'
import { journeyServiceUrl } from './environment'

test('isolated journey service mappings fail closed; manual defaults are preserved', (t) => {
  const previousMode = process.env.E2E_ISOLATED
  const previousUrls = process.env.E2E_SERVICE_URLS
  t.after(() => {
    if (previousMode === undefined) delete process.env.E2E_ISOLATED
    else process.env.E2E_ISOLATED = previousMode
    if (previousUrls === undefined) delete process.env.E2E_SERVICE_URLS
    else process.env.E2E_SERVICE_URLS = previousUrls
  })
  delete process.env.E2E_ISOLATED
  assert.equal(journeyServiceUrl(5007, '/booking-requests'), 'http://localhost:5007/booking-requests')
  process.env.E2E_ISOLATED = '1'
  delete process.env.E2E_SERVICE_URLS
  assert.throws(() => journeyServiceUrl(5007), /missing/)
  process.env.E2E_SERVICE_URLS = JSON.stringify({ 5007: 'http://shared.example:5007' })
  assert.throws(() => journeyServiceUrl(5007), /loopback/)
  process.env.E2E_SERVICE_URLS = JSON.stringify({ 5007: 'https://127.0.0.1:45007' })
  assert.throws(() => journeyServiceUrl(5007), /HTTP loopback/)
  process.env.E2E_SERVICE_URLS = JSON.stringify({ 5007: 'http://127.0.0.1:45007' })
  assert.equal(journeyServiceUrl(5007, '/booking-requests'), 'http://127.0.0.1:45007/booking-requests')
})
