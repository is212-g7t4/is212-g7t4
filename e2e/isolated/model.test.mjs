import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { test } from 'node:test'
import { parse } from 'yaml'
import { isolatedModel } from './model.mjs'

test('every service and worker uses only the isolated database, broker and service network', () => {
  const root = resolve('.')
  const source = parse(readFileSync(resolve(root, 'docker-compose.yml'), 'utf8'))
  const before = JSON.stringify(source)
  const credentials = { database: 'test-db', rabbit: 'test-broker', internal: 'test-internal',
    frontendOrigin: 'http://127.0.0.1:45000', signingKey: { alg: 'ES256' } }
  const { compose, servicePorts } = isolatedModel(source, root, credentials)
  assert.equal(JSON.stringify(source), before)
  for (const [name, service] of Object.entries(compose.services)) {
    assert.equal(service.env_file, undefined, name)
    assert.equal(service.restart, undefined, name)
    assert.equal(service.container_name, undefined, name)
    assert.equal(JSON.stringify(service).includes('${'), false, name)
    if (source.services[name]?.command) assert.deepEqual(service.command, source.services[name].command)
    for (const port of service.ports ?? []) {
      assert.equal(port.host_ip, '127.0.0.1')
      assert.equal(port.published, '0')
    }
    if (name.endsWith('-service') || name.endsWith('-dispatcher') || name === 'notification-consumer') {
      assert.match(service.environment.DATABASE_URL, /@database:5432\/journeys$/)
      assert.match(service.environment.RABBITMQ_URL, /@rabbitmq:5672/)
      assert.equal(service.environment.SUPABASE_URL, 'http://supabase')
      assert.equal(service.environment.FRONTEND_ORIGIN, credentials.frontendOrigin)
      assert.equal(service.environment.CLOSURE_CONFIRMATION_KEY, credentials.internal)
      assert.equal(service.environment.EQUIPMENT_REQUEST_SERVICE_URL, 'http://equipment-request-service:5000')
    }
  }
  assert.equal(servicePorts['5015'], 'notification-service')
  assert.equal(compose.services['registration-notification-dispatcher'].environment.OUTBOX_OWNER, 'registration')
  assert.match(compose.services['supabase-auth'].environment.GOTRUE_JWT_KEYS, /ES256/)
  assert.equal(compose.services['supabase-auth'].environment.GOTRUE_HOOK_CUSTOM_ACCESS_TOKEN_ENABLED, 'true')
  for (const volume of Object.values(compose.volumes)) {
    assert.equal(volume?.name, undefined)
    assert.equal(volume?.external, undefined)
  }
})
