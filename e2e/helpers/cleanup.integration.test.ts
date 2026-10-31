import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { test } from 'node:test'
import { Client } from 'pg'
import { deleteFixtureEvents } from './cleanup'

function docker(args: string[]) {
  const result = spawnSync('docker', args, { encoding: 'utf8', timeout: 120_000 })
  if (result.status !== 0) throw new Error(`Docker ${args[0]} failed: ${result.error?.message ?? result.stderr}`)
  return result.stdout.trim()
}

test('run-scoped cleanup preserves concurrent runs and rejects cross-run venue deletion in Postgres', {
  skip: process.env.RUN_CLEANUP_INTEGRATION !== '1',
  timeout: 180_000,
}, async (t) => {
  const container = `cleanup-isolation-${randomUUID()}`
  const previousUrl = process.env.DATABASE_URL
  let db: Client | undefined
  t.after(async () => {
    try {
      await db?.end()
    } finally {
      if (previousUrl === undefined) delete process.env.DATABASE_URL
      else process.env.DATABASE_URL = previousUrl
      docker(['rm', '-f', '-v', container])
    }
  })
  docker([
    'run', '-d', '--name', container, '-e', 'POSTGRES_HOST_AUTH_METHOD=trust',
    '-p', '127.0.0.1::5432', 'postgres:17.6', 'sh', '-c',
    'openssl req -new -x509 -nodes -days 1 -subj /CN=localhost -keyout /tmp/cleanup.key -out /tmp/cleanup.crt >/dev/null 2>&1'
      + ' && chown postgres:postgres /tmp/cleanup.key && chmod 600 /tmp/cleanup.key'
      + ' && exec docker-entrypoint.sh postgres -c ssl=on -c ssl_cert_file=/tmp/cleanup.crt -c ssl_key_file=/tmp/cleanup.key',
  ])
  const port = docker(['port', container, '5432']).split(':').pop()
  process.env.DATABASE_URL = `postgresql://postgres:local-test@127.0.0.1:${port}/postgres`
  for (let attempt = 0; attempt < 60; attempt++) {
    const candidate = new Client({
      connectionString: process.env.DATABASE_URL,
      ssl: { rejectUnauthorized: false },
      connectionTimeoutMillis: 1_000,
    })
    try {
      await candidate.connect()
      db = candidate
      break
    } catch (error) {
      await candidate.end()
      if (attempt === 59) throw error
      await new Promise((resolve) => setTimeout(resolve, 500))
    }
  }
  assert.ok(db)
  // Minimal owner tables retain the foreign keys relevant to the cleanup order.
  await db.query(`
    CREATE TABLE public."Event" (event_id text PRIMARY KEY, event_name text NOT NULL);
    CREATE TABLE public."Venue" (venue_id text PRIMARY KEY, venue_name text NOT NULL);
    CREATE TABLE public."SafetyCheck" (safety_check_id text PRIMARY KEY, event_id text REFERENCES public."Event");
    CREATE TABLE public."SafetyCheckFlag" (safety_check_id text REFERENCES public."SafetyCheck");
    CREATE TABLE public."VenueBooking" (booking_id text PRIMARY KEY, event_id text REFERENCES public."Event", venue_id text REFERENCES public."Venue");
    CREATE TABLE public."VenueClosure" (closure_id text PRIMARY KEY, venue_id text REFERENCES public."Venue");
    CREATE TABLE public."VenueNotificationOutbox" (
      source_id text PRIMARY KEY,
      booking_id text REFERENCES public."VenueBooking",
      closure_id text REFERENCES public."VenueClosure"
    );
  `)
  for (const table of ['Notification', 'EquipmentRequest', 'EventChangeReq', 'Registration']) {
    await db.query(`CREATE TABLE public."${table}" (event_id text REFERENCES public."Event")`)
  }
  for (const table of ['EventNotificationOutbox', 'EquipmentNotificationOutbox', 'RegistrationNotificationOutbox']) {
    await db.query(`CREATE TABLE public."${table}" (source_id text PRIMARY KEY, source jsonb NOT NULL)`)
  }
  async function seed(id: string, eventName: string, venueName: string) {
    assert.ok(db)
    await db.query('INSERT INTO public."Event" VALUES ($1,$2)', [id, eventName])
    await db.query('INSERT INTO public."Venue" VALUES ($1,$2)', [id, venueName])
    await db.query('INSERT INTO public."SafetyCheck" VALUES ($1,$1)', [id])
    await db.query('INSERT INTO public."SafetyCheckFlag" VALUES ($1)', [id])
    await db.query('INSERT INTO public."VenueBooking" VALUES ($1,$1,$1)', [id])
    await db.query('INSERT INTO public."VenueClosure" VALUES ($1,$1)', [id])
    await db.query('INSERT INTO public."VenueNotificationOutbox" VALUES ($1,$1,$1)', [id])
    for (const table of ['Notification', 'EquipmentRequest', 'EventChangeReq', 'Registration']) {
      await db.query(`INSERT INTO public."${table}" VALUES ($1)`, [id])
    }
    for (const table of ['EventNotificationOutbox', 'EquipmentNotificationOutbox', 'RegistrationNotificationOutbox']) {
      await db.query(`INSERT INTO public."${table}" VALUES ($1,$2)`, [id, { eventId: id }])
    }
  }
  const first = { eventNames: ['J1 Event run_%.*', 'J1 Event second'], venueNames: ['J1 Venue run_%.*', 'J1 Venue second'] }
  const second = { eventNames: ['J6a Event run-two'], venueNames: ['J6a Venue run-two'] }
  await seed('a', first.eventNames[0], first.venueNames[0])
  await seed('a2', first.eventNames[1], first.venueNames[1])
  await seed('b', second.eventNames[0], second.venueNames[0])
  await seed('lookalike', `${first.eventNames[0]} suffix`, `${first.venueNames[0]} suffix`)
  await seed('real', 'Real event', 'Real venue')

  const tables = (await db.query<{ tablename: string }>(
    "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename",
  )).rows.map(({ tablename }) => tablename)
  async function snapshot() {
    assert.ok(db)
    const state: Record<string, Record<string, string>[]> = {}
    for (const table of tables) {
      state[table] = (await db.query(`SELECT * FROM public."${table}" ORDER BY 1`)).rows
    }
    return state
  }
  const before = await snapshot()
  await deleteFixtureEvents(first)
  const after = await snapshot()
  for (const table of tables) {
    assert.deepEqual(after[table], before[table].filter((row) => !['a', 'a2'].includes(
      row.event_id ?? row.venue_id ?? row.safety_check_id ?? row.source_id,
    )), `${table} must preserve all other runs and real records`)
  }
  // Repeated teardown and cleanup of a partially seeded run are safe.
  await deleteFixtureEvents(first)
  await db.query('INSERT INTO public."Event" VALUES ($1,$2)', ['partial', 'J1 Event partial'])
  await deleteFixtureEvents({ eventNames: ['J1 Event partial'], venueNames: ['J1 Venue never-created'] })
  assert.deepEqual(await snapshot(), after)

  await db.query('INSERT INTO public."VenueBooking" VALUES ($1,$2,$3)', ['cross-run', 'b', 'lookalike'])
  const sharedVenue = await snapshot()
  await assert.rejects(deleteFixtureEvents({
    eventNames: [`${first.eventNames[0]} suffix`], venueNames: [`${first.venueNames[0]} suffix`],
  }), /another run or event/)
  assert.deepEqual(await snapshot(), sharedVenue, 'refusal must roll back without touching either run')
  await db.query('DELETE FROM public."VenueBooking" WHERE booking_id=$1', ['cross-run'])

  // Both independent teardown transactions may execute at the same time.
  await seed('a', first.eventNames[0], first.venueNames[0])
  await seed('a2', first.eventNames[1], first.venueNames[1])
  await Promise.all([deleteFixtureEvents(first), deleteFixtureEvents(second)])
  for (const [table, rows] of Object.entries(await snapshot())) {
    assert.equal(rows.length, 2, `${table} must retain only lookalike and real fixtures`)
  }

  // J6a approves a title change; old-name intents must follow the renamed event.
  const renamed = {
    eventNames: ['J6a Event approve rename-run', 'J6a Event approved proposal rename-run'],
    venueNames: [],
  }
  await db.query('INSERT INTO public."Event" VALUES ($1,$2)', ['renamed', renamed.eventNames[0]])
  for (const table of ['EventNotificationOutbox', 'EquipmentNotificationOutbox', 'RegistrationNotificationOutbox']) {
    await db.query(`INSERT INTO public."${table}" VALUES ($1,$2),($3,$4)`, [
      'renamed', { eventId: 'renamed', eventName: renamed.eventNames[0] },
      'orphan', { eventId: 'already-removed', eventName: renamed.eventNames[0] },
    ])
  }
  await db.query('UPDATE public."Event" SET event_name=$1 WHERE event_id=$2', [renamed.eventNames[1], 'renamed'])
  const renamedBefore = await snapshot()
  await deleteFixtureEvents(renamed)
  for (const [table, rows] of Object.entries(await snapshot())) {
    assert.deepEqual(rows, renamedBefore[table].filter((row) =>
      !['renamed', 'orphan'].includes(row.event_id ?? row.source_id),
    ), `${table} must delete the J6a renamed fixture and its old-name intents only`)
  }

  // J6b owns its booking, not the pre-existing venue it uses.
  const seededVenueBefore = (await db.query('SELECT * FROM public."Venue" WHERE venue_id=$1', ['real'])).rows
  await db.query('INSERT INTO public."Event" VALUES ($1,$2)', ['j6b', 'J6b Event confirmed run'])
  await db.query('INSERT INTO public."VenueBooking" VALUES ($1,$1,$2)', ['j6b', 'real'])
  await db.query('INSERT INTO public."VenueNotificationOutbox" (source_id,booking_id) VALUES ($1,$1)', ['j6b'])
  await deleteFixtureEvents({ eventNames: ['J6b Event confirmed run'], venueNames: [] })
  assert.deepEqual(
    (await db.query('SELECT * FROM public."Venue" WHERE venue_id=$1', ['real'])).rows,
    seededVenueBefore,
    'J6b teardown must preserve the shared seeded venue',
  )
  assert.equal((await db.query('SELECT 1 FROM public."VenueBooking" WHERE booking_id=$1', ['j6b'])).rowCount, 0)
})
