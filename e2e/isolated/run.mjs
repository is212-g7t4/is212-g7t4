import { spawn } from 'node:child_process'
import { generateKeyPairSync, randomBytes, randomUUID } from 'node:crypto'
import { mkdtemp, readFile, readdir, rm, rmdir, writeFile } from 'node:fs/promises'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { Client } from 'pg'
import { parse, stringify } from 'yaml'
import { isolatedModel } from './model.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..')
const project = `journeys-${randomUUID()}`
const directory = await mkdtemp(resolve(tmpdir(), `${project}-`))
const config = resolve(directory, 'compose.yml')
const envFile = resolve(directory, 'empty.env')
const secret = () => randomBytes(24).toString('hex')
const signingKey = {
  ...generateKeyPairSync('ec', { namedCurve: 'prime256v1' }).privateKey.export({ format: 'jwk' }),
  kid: randomUUID(), alg: 'ES256', use: 'sig', key_ops: ['sign', 'verify'],
}
let frontend
let interrupted = false
let active = false
const children = new Set()
const abort = () => {
  interrupted = true
  for (const child of children) child.kill()
}
process.once('SIGINT', abort)
process.once('SIGTERM', abort)

function command(executable, args, options = {}) {
  if (interrupted && !args.includes('down')) return Promise.reject(new Error('Isolated journey run interrupted.'))
  return new Promise((accept, reject) => {
    const child = spawn(executable, args, { cwd: root, ...options })
    children.add(child)
    let output = ''
    child.stdout?.on('data', chunk => { output += chunk })
    child.on('error', error => { children.delete(child); reject(error) })
    child.on('close', code => {
      children.delete(child)
      if (code !== 0) reject(new Error(`${executable} ${args[0]} failed (exit ${code}).`))
      else accept(output.trim())
    })
  })
}
const compose = (args, capture = false) => command('docker',
  ['compose', '--env-file', envFile, '--project-name', project, '--file', config, ...args],
  { stdio: capture ? ['ignore', 'pipe', 'inherit'] : 'inherit' })

async function published(name, port) {
  const result = await compose(['port', name, String(port)], true)
  if (!/^127\.0\.0\.1:\d+$/.test(result)) throw new Error(`Unexpected isolated port mapping for ${name}.`)
  return `http://${result}`
}

async function waitFor(url, timeout = 120_000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (interrupted) throw new Error('Isolated journey run interrupted.')
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(3_000) })
      if (response.ok) return
    } catch (error) {
      if (!(error instanceof TypeError) && error.name !== 'TimeoutError') throw error
    }
    await new Promise(accept => setTimeout(accept, 1_000))
  }
  throw new Error(`Isolated service did not become ready: ${url}`)
}

try {
  await command('docker', ['info'], { stdio: 'ignore' })
  const server = createServer()
  await new Promise((accept, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', accept) })
  const frontendPort = server.address().port
  await new Promise(accept => server.close(accept))
  const frontendOrigin = `http://127.0.0.1:${frontendPort}`
  const credentials = { database: secret(), rabbit: secret(), internal: secret(), password: secret(), signingKey, frontendOrigin }
  const source = parse(await readFile(resolve(root, 'docker-compose.yml'), 'utf8'))
  const { compose: model, servicePorts } = isolatedModel(source, root, credentials)
  await writeFile(envFile, '', { mode: 0o600 })
  await writeFile(config, stringify(model), { mode: 0o600 })
  console.log(`Starting isolated stack ${project}`)
  console.log(`Recovery config (contains temporary credentials): ${config}`)
  active = true
  await compose(['up', '-d', '--wait', 'database'])
  const database = new URL(await published('database', 5432))
  const db = new Client({ host: database.hostname, port: Number(database.port), user: 'postgres', password: credentials.database, database: 'journeys', ssl: false })
  await db.connect()
  try {
    await db.query(`ALTER ROLE supabase_auth_admin PASSWORD '${credentials.database}'`)
    await compose(['up', '-d', 'supabase-auth', 'supabase'])
    const authOrigin = await published('supabase', 80)
    await waitFor(`${authOrigin}/auth/v1/health`)
    const migrations = resolve(root, 'database', 'supabase', 'migrations')
    for (const file of (await readdir(migrations)).filter(name => name.endsWith('.sql')).sort())
      await db.query(await readFile(resolve(migrations, file), 'utf8'))
    const seed = await readFile(resolve(root, 'database', 'supabase', 'seed.sql'), 'utf8')
    // Fresh database: the historical truncate list omits newer FK-dependent tables.
    const truncate = /truncate table[\s\S]*?;/i
    if (!truncate.test(seed)) throw new Error('Expected seed truncate statement not found.')
    await db.query(seed.replace(truncate, ''))
    await db.query(`
      CREATE FUNCTION public.custom_access_token_hook(event jsonb) RETURNS jsonb
      LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public AS $$
      DECLARE claims jsonb; user_role text;
      BEGIN
        SELECT role INTO STRICT user_role FROM public."User" WHERE user_id = (event->>'user_id')::uuid;
        claims := jsonb_set(event->'claims', '{user_role}', to_jsonb(user_role));
        RETURN jsonb_build_object('claims', claims);
      END $$;
      REVOKE ALL ON FUNCTION public.custom_access_token_hook(jsonb) FROM PUBLIC, anon, authenticated;
      GRANT SELECT ON public."User" TO supabase_auth_admin;
      GRANT EXECUTE ON FUNCTION public.custom_access_token_hook(jsonb) TO supabase_auth_admin;
    `)
    const { rows } = await db.query('SELECT user_id, email FROM public."User"')
    for (const user of rows) {
      await db.query(`
        INSERT INTO auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
          raw_app_meta_data, raw_user_meta_data, created_at, updated_at, confirmation_token,
          recovery_token, email_change_token_new, email_change)
        VALUES ('00000000-0000-0000-0000-000000000000', $1, 'authenticated', 'authenticated', $2,
          crypt($3, gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{}', now(), now(), '', '', '', '');
      `, [user.user_id, user.email, credentials.password])
      await db.query(`
        INSERT INTO auth.identities (id, provider_id, user_id, identity_data, provider, created_at, updated_at)
        VALUES (gen_random_uuid(), $1::text, ($1::text)::uuid, jsonb_build_object('sub', $1::text, 'email', $2::text), 'email', now(), now());
      `, [user.user_id, user.email])
    }
    const authLogin = await fetch(`${authOrigin}/auth/v1/token?grant_type=password`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: rows[0].email, password: credentials.password }),
      signal: AbortSignal.timeout(10_000),
    })
    if (!authLogin.ok) {
      await compose(['logs', '--tail', '15', 'supabase-auth'])
      throw new Error(`Supabase Auth account preflight failed (${authLogin.status}): ${await authLogin.text()}`)
    }
  } finally { await db.end() }
  await compose(['up', '-d', '--build'])
  const urls = {}
  for (const [port, name] of Object.entries(servicePorts))
    urls[port] = await published(name, name === 'rabbitmq' ? Number(port) : 5000)
  await Promise.all(Object.entries(urls).filter(([port]) => !['5672', '15672'].includes(port))
    .map(([, url]) => waitFor(`${url}/health`)))
  const env = { ...process.env, E2E_ISOLATED: '1', E2E_SERVICE_URLS: JSON.stringify(urls),
    E2E_PASSWORD: credentials.password, FRONTEND_URL: frontendOrigin,
    E2E_REPORT_DIR: resolve(root, 'e2e', 'journeys', 'report', project),
    E2E_OUTPUT_DIR: resolve(root, 'e2e', 'journeys', 'test-results', project),
    DATABASE_URL: `postgresql://postgres:${credentials.database}@127.0.0.1:${database.port}/journeys` }
  for (const key of Object.keys(env)) if (key.startsWith('E2E_PASSWORD_')) delete env[key]
  const vitePorts = {
    USER: 5001, EVENT: 5003, COORDINATOR_ASSIGNMENT: 5004, REGISTRATION: 5005,
    VENUE: 5006, VENUE_BOOKING: 5007, VENUE_AVAILABILITY: 5008, ATTENDEE_REGISTRATION: 5009,
    EQUIPMENT: 5002, EQUIPMENT_RESERVATION: 5010, EQUIPMENT_REQUEST: 5011,
    SAFETY_CHECK: 5012, SAFETY_CHECK_RECORD: 5013, EVENT_WORKFLOW: 5014, NOTIFICATION: 5015,
  }
  for (const key of Object.keys(env)) if (key.startsWith('VITE_')) delete env[key]
  for (const [name, port] of Object.entries(vitePorts)) env[`VITE_${name}_SERVICE_URL`] = urls[port]
  const vite = resolve(root, 'frontend', 'event-management-ui', 'node_modules', 'vite', 'bin', 'vite.js')
  frontend = spawn(process.execPath, [vite, '--host', '127.0.0.1', '--port', String(frontendPort), '--strictPort'],
    { cwd: resolve(root, 'frontend', 'event-management-ui'), env, stdio: 'inherit' })
  children.add(frontend)
  frontend.on('error', error => { console.error(error.message); abort() })
  frontend.on('close', () => { children.delete(frontend) })
  await waitFor(frontendOrigin)
  // Verify real login, JWKS signature and role authorization before journey writes.
  const login = await fetch(`${urls[5001]}/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: 'alice.tan@connectsphere.example', password: credentials.password }),
    signal: AbortSignal.timeout(10_000),
  })
  if (!login.ok) throw new Error(`Isolated sign-in preflight failed (${login.status}): ${await login.text()}`)
  const session = await login.json()
  const profile = await fetch(`${urls[5001]}/users`, {
    headers: { Authorization: `Bearer ${session.accessToken}` }, signal: AbortSignal.timeout(10_000),
  })
  if (!profile.ok) throw new Error(`Isolated ES256 verification preflight failed (${profile.status}).`)
  await command(process.execPath, [resolve(root, 'node_modules', '@playwright', 'test', 'cli.js'),
    'test', '-c', 'e2e/journeys', ...process.argv.slice(2)], { env, stdio: 'inherit' })
} catch (error) {
  console.error(error.message)
  process.exitCode = 1
  // The stack is torn down next, so CI would otherwise lose the service logs.
  if (active && process.env.CI) await compose(['logs', '--no-color', '--tail', '80']).catch(() => {})
} finally {
  if (frontend && frontend.exitCode === null && frontend.signalCode === null) {
    await new Promise(accept => { frontend.once('close', accept); frontend.kill() })
  }
  let tornDown = true
  if (active) {
    try { await compose(['down', '--volumes', '--remove-orphans']) }
    catch (error) {
      tornDown = false
      console.error(`Teardown failed for ${project}: ${error.message}`)
      console.error(`Recover: docker compose --env-file "${envFile}" -p ${project} -f "${config}" down --volumes --remove-orphans`)
      process.exitCode = 1
    }
  }
  if (tornDown) {
    await rm(config, { force: true })
    await rm(envFile, { force: true })
    await rmdir(directory)
  }
  console.log(`Report: npx playwright show-report e2e\\journeys\\report\\${project}`)
}
