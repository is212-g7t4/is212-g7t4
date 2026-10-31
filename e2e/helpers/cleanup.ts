import { Client } from 'pg'

// Fixture events are named "J<n>[a|b] Event ..."; cleanup never touches other events.
const FIXTURE_NAME = '^J[0-9]+[ab]? Event '
const FIXTURE_VENUE = '^J[0-9]+[ab]? Venue '

function connect() {
  process.loadEnvFile('.env') // run from the repo root, as the npm scripts do
  const raw = process.env.DATABASE_URL
  if (!raw) throw new Error('DATABASE_URL is not set in the root .env')
  // Split before decoding so escaped delimiters remain part of the credentials.
  const match = raw.match(/^postgres(?:ql)?:\/\/([^:]+):(.+)@([^@]+?):(\d+)\/(\w+)$/)
  if (!match) throw new Error('DATABASE_URL is not in the expected postgresql://user:password@host:port/db form')
  const [, user, password, host, port, database] = match
  return new Client({
    user: decodeURIComponent(user),
    password: decodeURIComponent(password),
    host,
    port: Number(port),
    database,
    ssl: { rejectUnauthorized: false },
  })
}

type FixtureNames = { eventName: string; venueName: string }
type FixtureScope = { eventNames: readonly string[]; venueNames: readonly string[] }

/** Deletes only one run's exact fixture event and venue names. */
export async function deleteNamedFixtureEvents(names: FixtureNames) {
  await deleteFixtureEvents({ eventNames: [names.eventName], venueNames: [names.venueName] })
}

/** Deletes only explicitly named fixtures. There is deliberately no all-journeys mode. */
export async function deleteFixtureEvents(scope: FixtureScope) {
  if (!scope || !Array.isArray(scope.eventNames) || !Array.isArray(scope.venueNames)
    || scope.eventNames.length + scope.venueNames.length === 0) {
    throw new Error('Cleanup requires explicit eventNames and venueNames arrays with at least one fixture name.')
  }
  if (scope.eventNames.some((name) => typeof name !== 'string' || !new RegExp(`${FIXTURE_NAME}\\S`).test(name))
    || scope.venueNames.some((name) => typeof name !== 'string' || !new RegExp(`${FIXTURE_VENUE}\\S`).test(name))) {
    throw new Error('Cleanup names must use the journey fixture naming convention.')
  }
  const db = connect()
  await db.connect()
  try {
    const ids = `(SELECT event_id FROM public."Event" WHERE event_name = ANY($1::text[]))`
    const events = [scope.eventNames]
    const venueNames = [scope.venueNames]
    const venues = `(SELECT venue_id FROM public."Venue" WHERE venue_name = ANY($1::text[]))`
    await db.query('BEGIN')
    await db.query(`SELECT venue_id FROM public."Venue" WHERE venue_name = ANY($1::text[]) FOR UPDATE`, venueNames)
    await db.query(`SELECT event_id FROM public."Event" WHERE event_name = ANY($1::text[]) FOR UPDATE`, events)
    const foreignBookings = await db.query(
      `SELECT 1 FROM public."VenueBooking" b
       WHERE b.venue_id IN ${venues}
         AND NOT EXISTS (SELECT 1 FROM public."Event" e WHERE e.event_id = b.event_id AND e.event_name = ANY($2::text[]))
       LIMIT 1`,
      [scope.venueNames, scope.eventNames],
    )
    if (foreignBookings.rows.length > 0) {
      throw new Error('Cleanup refused: a fixture venue has bookings belonging to another run or event.')
    }
    await db.query(
      `DELETE FROM public."VenueNotificationOutbox" WHERE booking_id IN (SELECT booking_id FROM public."VenueBooking" WHERE event_id IN ${ids})`,
      events,
    )
    await db.query(
      `DELETE FROM public."VenueNotificationOutbox" WHERE booking_id IN (SELECT booking_id FROM public."VenueBooking" WHERE venue_id IN ${venues}) OR closure_id IN (SELECT closure_id FROM public."VenueClosure" WHERE venue_id IN ${venues})`,
      venueNames,
    )
    for (const table of ['EventNotificationOutbox', 'EquipmentNotificationOutbox', 'RegistrationNotificationOutbox']) {
      await db.query(
        `DELETE FROM public."${table}" WHERE source->>'eventName' = ANY($1::text[])
         OR source->>'eventId' IN (SELECT event_id::text FROM public."Event" WHERE event_name = ANY($1::text[]))`,
        events,
      )
    }
    await db.query(
      `DELETE FROM public."SafetyCheckFlag" WHERE safety_check_id IN (SELECT safety_check_id FROM public."SafetyCheck" WHERE event_id IN ${ids})`,
      events,
    )
    for (const table of ['SafetyCheck', 'Notification', 'EquipmentRequest', 'VenueBooking', 'EventChangeReq', 'Registration']) {
      await db.query(`DELETE FROM public."${table}" WHERE event_id IN ${ids}`, events)
    }
    await db.query(`DELETE FROM public."Event" WHERE event_name = ANY($1::text[])`, events)
    await db.query(`DELETE FROM public."VenueClosure" WHERE venue_id IN ${venues}`, venueNames)
    await db.query(`DELETE FROM public."Venue" WHERE venue_name = ANY($1::text[])`, venueNames)
    await db.query('COMMIT')
  } catch (error) {
    await db.query('ROLLBACK')
    throw error
  } finally {
    await db.end()
  }
}
