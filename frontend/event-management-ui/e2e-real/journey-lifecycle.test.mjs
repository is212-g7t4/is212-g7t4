/** SCRUM-45: As an Event Organiser, I want to receive an in-app notification
 * when the Lead Coordinator approves or rejects my event request, so that I know
 * the outcome and who is responsible for coordinating my event.
 * DR3/DR9: failure diagnostics must not hide the journey failure or skip close.
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { runBrowserJourney } from './journey-lifecycle.mjs'

test('original journey failure survives screenshot and request-log failures; close is attempted', async () => {
  const primary = new Error('linked rejection details missing')
  const screenshotError = new Error('screenshot target closed')
  const writeError = new Error('request-log disk full')
  const calls = []
  const diagnostics = []
  await assert.rejects(runBrowserJourney({
    run: async () => { calls.push('journey'); throw primary },
    screenshot: async () => { calls.push('screenshot'); throw screenshotError },
    writeRequests: async () => { calls.push('writeRequests'); throw writeError },
    browser: { close: async () => { calls.push('close') } },
    reportDiagnostic: diagnostic => diagnostics.push(diagnostic),
  }), error => error === primary)
  assert.deepEqual(calls, ['journey', 'screenshot', 'writeRequests', 'close'])
  assert.deepEqual(diagnostics, [
    { operation: 'screenshot', error: screenshotError },
    { operation: 'writeRequests', error: writeError },
  ])
})


test('browser close failure is reported separately without masking the original exception', async () => {
  const primary = new Error('real journey assertion')
  const closeError = new Error('browser close rejected')
  const diagnostics = []
  await assert.rejects(runBrowserJourney({
    run: async () => { throw primary },
    screenshot: async () => {},
    writeRequests: async () => {},
    browser: { close: async () => { throw closeError } },
    reportDiagnostic: diagnostic => diagnostics.push(diagnostic),
  }), error => error === primary)
  assert.deepEqual(diagnostics, [{ operation: 'close', error: closeError }])
})


test('request-log failure after success is not silent and still closes the browser', async () => {
  const writeError = new Error('disk full')
  const calls = []
  const diagnostics = []
  await assert.rejects(runBrowserJourney({
    run: async () => { calls.push('journey') },
    screenshot: async () => { assert.fail('successful journey needs no failure screenshot') },
    writeRequests: async () => { calls.push('writeRequests'); throw writeError },
    browser: { close: async () => { calls.push('close') } },
    reportDiagnostic: diagnostic => diagnostics.push(diagnostic),
  }), error => error instanceof AggregateError && error.errors.length === 1 && error.errors[0] === writeError)
  assert.deepEqual(calls, ['journey', 'writeRequests', 'close'])
  assert.deepEqual(diagnostics, [{ operation: 'writeRequests', error: writeError }])
})

test('successful journey returns its result after writing diagnostics and closing', async () => {
  const calls = []
  const result = await runBrowserJourney({
    run: async () => { calls.push('journey'); return 'complete' },
    screenshot: async () => { assert.fail('no failure screenshot expected') },
    writeRequests: async () => { calls.push('writeRequests') },
    browser: { close: async () => { calls.push('close') } },
    reportDiagnostic: () => { assert.fail('no secondary errors expected') },
  })
  assert.equal(result, 'complete')
  assert.deepEqual(calls, ['journey', 'writeRequests', 'close'])
})
