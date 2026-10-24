import { Client } from 'pg'

// Journey fixtures are named with this prefix; cleanup never touches other events.
export const FIXTURE_PREFIX = 'J5'

function connect() {
  process.loadEnvFile('.env') // run from the repo root, as the npm scripts do
  const raw = process.env.DATABASE_URL
  if (!raw) throw new Error('DATABASE_URL is not set in the root .env')
  // Parsed by hand: the password may contain "?" or "+", which URL parsing mangles.
  const match = raw.match(/^postgres(?:ql)?:\/\/([^:]+):(.+)@([^@]+?):(\d+)\/(\w+)$/)
  if (!match) throw new Error('DATABASE_URL is not in the expected postgresql://user:password@host:port/db form')
  const [, user, password, host, port, database] = match
  return new Client({ user, password, host, port: Number(port), database, ssl: { rejectUnauthorized: false } })
}

/** Deletes journey fixture events (and their dependent rows) left by this or earlier runs. */
export async function deleteFixtureEvents() {
  const db = connect()
  await db.connect()
  try {
    const ids = `(SELECT event_id FROM public."Event" WHERE event_name LIKE $1)`
    const like = [`${FIXTURE_PREFIX}% Event %`]
    await db.query('BEGIN')
    for (const table of ['Notification', 'EquipmentRequest', 'VenueBooking', 'EventChangeReq', 'Registration']) {
      await db.query(`DELETE FROM public."${table}" WHERE event_id IN ${ids}`, like)
    }
    await db.query(`DELETE FROM public."Event" WHERE event_name LIKE $1`, like)
    await db.query('COMMIT')
  } catch (error) {
    await db.query('ROLLBACK')
    throw error
  } finally {
    await db.end()
  }
}
