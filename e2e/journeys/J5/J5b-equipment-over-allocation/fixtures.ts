// Manual recording fixtures use an explicit run ID for later cleanup.
import { randomUUID } from 'node:crypto'
import { request } from '@playwright/test'
import { deleteFixtureEvents } from '../../../helpers/cleanup'
import { seedJ5b } from './helpers/seed'

async function main() {
  const clean = process.argv[2] === 'clean'
  const runId = clean ? process.argv[3] : process.argv[2] ?? randomUUID()
  if (!runId || !/^[a-zA-Z0-9-]+$/.test(runId)) {
    throw new Error('Provide a run ID containing only letters, numbers and hyphens. Usage: npm run journey:fixtures:clean -- <run-id>')
  }
  const scope = { eventNames: [`J5b Event A ${runId}`, `J5b Event B ${runId}`], venueNames: [] }
  if (clean) {
    await deleteFixtureEvents(scope)
    console.log(`Removed only J5b fixture events for run ${runId}.`)
    return
  }
  console.log(`Run ID: ${runId}. Remove with: npm run journey:fixtures:clean -- ${runId}`)
  const api = await request.newContext()
  try {
    const seeded = await seedJ5b(api, runId)
    console.log(`Seeded J5b. Record against event "${seeded.eventB}" (${seeded.window.start} to ${seeded.window.end}).`)
    console.log('Event A holds 40 tables; B has a pending request for 20. Run `npm run codegen` next.')
  } catch (error) {
    await deleteFixtureEvents(scope)
    throw error
  } finally {
    await api.dispose()
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1 })
