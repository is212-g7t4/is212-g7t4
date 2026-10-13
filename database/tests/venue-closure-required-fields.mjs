// Run with: node database/tests/venue-closure-required-fields.mjs /absolute/path/to/@electric-sql/pglite/dist/index.js
// Uses isolated in-memory PostgreSQL (PGlite), never DATABASE_URL or shared data.
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
const { PGlite } = await import(pathToFileURL(process.argv[2]).href);
const root = new URL('../', import.meta.url);
const baseline = readFileSync(new URL('supabase/migrations/20261011140000_baseline_schema.sql', root), 'utf8');
const migrationPath = new URL('supabase/migrations/20261012234245_require_venue_closure_metadata.sql', root);
// Missing migration intentionally exercises the pre-change schema for RED.
const migration = existsSync(migrationPath) ? readFileSync(migrationPath, 'utf8') : '';
const columns = ['closure_id', 'venue_id', 'start_date_time', 'end_date_time', 'reason', 'created_by', 'created_at'];
const values = ['00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000002', '2030-01-01T09:00:00+08:00', '2030-01-01T10:00:00+08:00', 'Maintenance', '00000000-0000-4000-8000-000000000003', '2026-01-01T00:00:00Z'];
const insert = `INSERT INTO public."VenueClosure" (${columns.join(',')}) VALUES (${columns.map((_, i) => '$' + (i + 1)).join(',')})`;
async function fresh() {
  const db = new PGlite();
  await db.exec(baseline);
  await db.query('INSERT INTO public."Venue" (venue_id) VALUES ($1)', [values[1]]);
  await db.query('INSERT INTO public."User" (user_id) VALUES ($1)', [values[5]]);
  return db;
}
const db = await fresh();
try {
  await db.exec(migration);
  const metadata = await db.query("SELECT column_name, is_nullable FROM information_schema.columns WHERE table_schema='public' AND table_name='VenueClosure'");
  for (const col of columns) assert.equal(metadata.rows.find(r => r.column_name === col)?.is_nullable, 'NO', `${col} must be NOT NULL`);
  await db.query(insert, values);
  const saved = await db.query('SELECT * FROM public."VenueClosure"');
  assert.equal(saved.rows.length, 1);
  assert.equal(saved.rows[0].reason, values[4]);
  for (let i = 0; i < columns.length; i++) {
    const invalid = [...values]; invalid[0] = '00000000-0000-4000-8000-000000000099'; invalid[i] = null;
    await assert.rejects(db.query(insert, invalid), e => e.code === '23502', `${columns[i]} must reject NULL`);
  }
  console.log('PASS: all seven columns NOT NULL; valid insert/read; seven explicit NULL inserts rejected');
} finally { await db.close(); }
for (const col of ['venue_id', 'created_by', 'created_at']) {
  const legacy = await fresh();
  try {
    const invalid = [...values]; invalid[columns.indexOf(col)] = null;
    await legacy.query(insert, invalid);
    await assert.rejects(legacy.exec(migration), e => e.code === '23502', `migration must refuse existing NULL ${col}`);
    await legacy.exec('ROLLBACK');
    const row = (await legacy.query('SELECT * FROM public."VenueClosure"')).rows[0];
    assert.equal(row[col], null, 'must not invent historical data');
    const metadata = await legacy.query("SELECT column_name, is_nullable FROM information_schema.columns WHERE table_schema='public' AND table_name='VenueClosure' AND column_name IN ('venue_id','created_by','created_at')");
    assert.ok(metadata.rows.every(r => r.is_nullable === 'YES'), 'failed migration must not partially apply');
    console.log(`PASS: existing NULL ${col} blocks migration without changing row or constraints`);
  } finally { await legacy.close(); }
}
