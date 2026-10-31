import assert from 'node:assert/strict'
import { mock, test } from 'node:test'
import type { TestContext } from 'node:test'
import { Client } from 'pg'
import { deleteFixtureEvents, deleteNamedFixtureEvents } from './cleanup'

const scope = { eventNames: ['J1 Event run.1'], venueNames: ['J1 Venue run.1'] }

function mockDatabase(t: TestContext) {
  const previousUrl = process.env.DATABASE_URL
  t.after(() => {
    mock.restoreAll()
    if (previousUrl === undefined) delete process.env.DATABASE_URL
    else process.env.DATABASE_URL = previousUrl
  })
  process.env.DATABASE_URL = 'postgresql://test:password@localhost:5432/postgres'
  mock.method(process, 'loadEnvFile', () => {})
  const connect = mock.method(Client.prototype, 'connect', async () => {})
  const queries: { sql: string; parameters?: readonly (readonly string[])[] }[] = []
  mock.method(Client.prototype, 'query', async (sql: string, parameters?: readonly (readonly string[])[]) => {
    queries.push({ sql, parameters })
    return { rows: [] }
  })
  const end = mock.method(Client.prototype, 'end', async () => {})
  return { queries, connect, end }
}

test('journey cleanup decodes URL credentials once and preserves literal plus signs', async (t) => {
  mockDatabase(t)
  const connected: Client[] = []
  mock.method(Client.prototype, 'connect', async function (this: Client) {
    connected.push(this)
  })
  for (const [encoded, expected] of [
    ['test%3Fpassword%2B%23%40', 'test?password+#@'],
    ['test+password?literal', 'test+password?literal'],
    ['test%253Fpassword', 'test%3Fpassword'],
  ]) {
    process.env.DATABASE_URL = `postgresql://test%2Euser:${encoded}@localhost:5432/postgres`
    await deleteFixtureEvents(scope)
    const client = connected.at(-1)
    assert.ok(client)
    assert.equal(client.user, 'test.user')
    assert.equal(client.password, expected)
  }
})

test('cleanup uses only exact name arrays and removes outbox dependencies before parents', async (t) => {
  const { queries, end } = mockDatabase(t)
  await deleteNamedFixtureEvents({ eventName: scope.eventNames[0], venueName: scope.venueNames[0] })
  assert.equal(queries[0].sql, 'BEGIN')
  assert.equal(queries.at(-1)?.sql, 'COMMIT')
  const deletes = queries.filter(({ sql }) => sql.startsWith('DELETE'))
  for (const { sql, parameters } of deletes) {
    assert.match(sql, /= ANY\(\$1::text\[\]\)/)
    assert.doesNotMatch(sql, /event_name ~|venue_name ~|LIKE/)
    assert.ok(parameters)
    assert.ok(parameters.every((names) => names.length === 1 && [scope.eventNames[0], scope.venueNames[0]].includes(names[0])))
  }
  const position = (table: string) => queries.findIndex(({ sql }) => sql.startsWith(`DELETE FROM public."${table}"`))
  assert.ok(position('VenueNotificationOutbox') < position('VenueBooking'))
  assert.ok(position('VenueNotificationOutbox') < position('VenueClosure'))
  for (const table of ['EventNotificationOutbox', 'EquipmentNotificationOutbox', 'RegistrationNotificationOutbox']) {
    assert.ok(position(table) >= 0)
    assert.ok(position(table) < position('Event'))
  }
  assert.equal(end.mock.callCount(), 1)
})

test('two run scopes, including multiple events and SQL wildcard characters, stay separate', async (t) => {
  const { queries } = mockDatabase(t)
  const first = { eventNames: ['J6a Event A run_%.*', 'J6a Event B run_%.*'], venueNames: [] }
  const second = { eventNames: ['J6a Event A another-run'], venueNames: ['J6a Venue another-run'] }
  await deleteFixtureEvents(first)
  const boundary = queries.length
  await deleteFixtureEvents(second)
  for (const [batch, owned] of [[queries.slice(0, boundary), first], [queries.slice(boundary), second]] as const) {
    const allowed = new Set([...owned.eventNames, ...owned.venueNames])
    for (const { parameters } of batch) {
      for (const names of parameters ?? []) {
        assert.ok(names.every((name) => allowed.has(name)))
      }
    }
  }
})

test('cleanup fails closed for missing, empty, malformed or non-fixture scopes before connecting', async (t) => {
  const { connect, queries } = mockDatabase(t)
  for (const invalid of [
    undefined, {}, { eventNames: [], venueNames: [] },
    { eventNames: 'J1 Event test', venueNames: [] },
    { eventNames: ['A real event'], venueNames: [] },
    { eventNames: [], venueNames: ['A real venue'] },
    { eventNames: ['J1 Event '], venueNames: [] },
    { eventNames: [null], venueNames: [] },
  ]) {
    await assert.rejects(Reflect.apply(deleteFixtureEvents, undefined, [invalid]), /Cleanup/)
  }
  assert.equal(connect.mock.callCount(), 0)
  assert.equal(queries.length, 0)
})

test('cleanup rolls back and closes the connection on a database failure', async (t) => {
  const { end } = mockDatabase(t)
  const statements: string[] = []
  const failure = new Error('Database operation failed')
  mock.method(Client.prototype, 'query', async (sql: string) => {
    statements.push(sql)
    if (sql.startsWith('DELETE')) throw failure
    return { rows: [] }
  })
  await assert.rejects(deleteFixtureEvents(scope), failure)
  assert.equal(statements.at(-1), 'ROLLBACK')
  assert.equal(end.mock.callCount(), 1)
})

test('cleanup refuses to remove a venue used by an event outside its scope', async (t) => {
  const { end } = mockDatabase(t)
  const statements: string[] = []
  mock.method(Client.prototype, 'query', async (sql: string) => {
    statements.push(sql)
    return { rows: sql.startsWith('SELECT 1 FROM') ? [{ exists: 1 }] : [] }
  })
  await assert.rejects(deleteFixtureEvents(scope), /another run or event/)
  assert.equal(statements.some((sql) => sql.startsWith('DELETE')), false)
  assert.equal(statements.at(-1), 'ROLLBACK')
  assert.equal(end.mock.callCount(), 1)
})
