// Manual-recording helper: `npm run journey:fixtures` seeds J5b data, `npm run journey:fixtures:clean` removes it.
import { request } from '@playwright/test'
import { deleteFixtureEvents } from '../../../helpers/cleanup'
import { seedJ5b } from './helpers/seed'

async function main() {
  if (process.argv[2] === 'clean') {
    await deleteFixtureEvents()
    console.log('Removed all J5 fixture events.')
    return
  }
  await deleteFixtureEvents()
  const api = await request.newContext()
  const seeded = await seedJ5b(api, Date.now().toString(36))
  await api.dispose()
  console.log(`Seeded J5b. Record against event "${seeded.eventB}" (${seeded.window.start} to ${seeded.window.end}).`)
  console.log('Event A holds 40 tables; B has a pending request for 20. Run `npm run codegen` next.')
  console.log('Remove with: npm run journey:fixtures:clean')
}

main().catch((error) => { console.error(error); process.exit(1) })// Manual-recording helper: `npm run journey:fixtures` seeds J5b data, `npm run journey:fixtures:clean` removes it.
import { request } from '@playwright/test'
import { deleteFixtureEvents } from '../../../helpers/cleanup'
import { seedJ5b } from './helpers/seed'

async function main() {
  if (process.argv[2] === 'clean') {
    await deleteFixtureEvents()
    console.log('Removed all J5 fixture events.')
    return
  }
  await deleteFixtureEvents()
  const api = await request.newContext()
  const seeded = await seedJ5b(api, Date.now().toString(36))
  await api.dispose()
  console.log(`Seeded J5b. Record against event "${seeded.eventB}" (${seeded.window.start} to ${seeded.window.end}).`)
  console.log('Event A holds 40 tables; B has a pending request for 20. Run `npm run codegen` next.')
  console.log('Remove with: npm run journey:fixtures:clean')
}

main().catch((error) => { console.error(error); process.exit(1) })