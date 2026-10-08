# Supabase setup — for team members

How to connect your service to the shared Supabase database and start
reading/writing the 8 tables that already exist.

## 1. Get the DB password

The connection string needs a real database password, which is **not**
committed anywhere in this repo. Get it from whoever set up the project, or
if you've been added to the Supabase org yourself:

1. Log into [supabase.com](https://supabase.com/dashboard) with the account
   that was invited to the `is212-g7t4` org.
2. Open the **is212-g7t4** project.
3. Click **Connect** (top of the project page), and copy the password shown
   there (or reset it if you don't have it and nobody else does either —
   note this invalidates the old password for everyone).

## 2. Set up your `.env`

Copy the root `.env.example` into your service directory as `.env`:

```
cp .env.example services/<your-service>/.env
```

Then edit `services/<your-service>/.env` and replace `<DB-PASSWORD>` with
the real password from step 1. `DATABASE_URL` is already set to the
**session pooler** connection string — use it as-is, don't switch to the
direct connection (`db.<ref>.supabase.co`) host, since that requires IPv6
and won't connect on most networks.

`SUPABASE_URL` and `SUPABASE_ANON_KEY` are already filled in — those are
safe to be public (the anon/publishable key is meant for client-side use),
only the DB password is a real secret.

**Never commit `.env`** — it's already covered by `.gitignore`.

## 3. Important: connect via `DATABASE_URL`, not the Supabase client

The supplied schema export does **not** include RLS settings, policies or
role grants. Their current state has not been verified; do not assume that
an anonymous Supabase client can read these tables, or that RLS protects
requests made through a privileged backend connection.

The existing backend pattern is `DATABASE_URL` with a Postgres driver.
Keep that connection server-side. A privileged `postgres` connection can
bypass RLS, so production availability access must independently verify identity
and allow only Event Coordinators, Venue Staff and Technical Support Staff.
SCRUM-25 explicitly defers real authentication: its calendar GET is disabled by
default and offers an opt-in `CALENDAR_DEV_MODE=true` user-switcher simulation
using spoofable `X-Dev-User-Id` / `X-Dev-Role` headers. This is **not secure auth**;
see the Venue Availability README for the exact development-only contract.
Inspect live policies and grants before enabling direct browser data access.

## 4. Add a Postgres driver to your service

The service templates don't include one yet. From your service directory:

```
cd services/<your-service>
uv add psycopg2-binary
# or, if you want an ORM:
uv add sqlalchemy psycopg2-binary
```

## 5. The tables

The eight tables below are documented from the user-supplied Supabase
context-only schema export reviewed on 2026-09-23. This is **schema review,
not a live database or application integration verification**. Do not execute
that export as a migration. The previously linked migration
`20260912150524_create_service_tables.sql` is absent from this checkout.

The export spells table names in PascalCase. PostgreSQL folds unquoted
identifiers to lowercase, so use double quotes for the intended mixed-case
names (for example `public."VenueBooking"`). Because the context export omits
those quotes, confirm the exact stored names before deploying:

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
ORDER BY table_name;
```

| Exported table name / intended SQL identifier | Owning service | Key columns |
|---|---|---|
| `public."Event"` | Event | `event_id` (PK), `event_name`, `status`, `organiser_id`, `coordinator_id` |
| `public."EventChangeReq"` | Event | `change_id` (PK), `event_id`, `requested_changes` (jsonb), `reviewed_by` |
| `public."Equipment"` | Equipment | `equipment_id` (PK), `equipment_type`, `description`, `total_quantity`, `location`, `operational_status` |
| `public."User"` | User | `user_id` (PK), `username`, `email`, `role`, `manager_id` (self-reference) |
| `public."VenueBooking"` | **Venue Availability** | `booking_id` (PK), `event_id`, `venue_id`, `requested_start_time`, `requested_end_time`, `status`, `requested_by`, `reviewed_by` |
| `public."Venue"` | Venue | `venue_id` (PK), `venue_name`, `max_capacity`, `facilities` (jsonb), `supported_layouts` (jsonb), `operational_status` |
| `public."Registration"` | Registration | `registration_id` (PK), `event_id`, `attendee_id` |
| `public."EquipmentRequest"` | Equipment Request | `equipment_request_id` (PK), `event_id`, `equipment_id`, `quantity_requested`, `reviewed_by` |

### Venue Availability ownership and this sprint's scope

Venue Availability now owns both booking records and conflict checking.
There is no separate Booking Conflict atomic service or duplicate booking
table in the agreed design. Conflict is calculated from venue, time range
and status; no stored `conflict` column is needed. Venue Service continues
to own the catalogue. The checked-in `INDEX.md`, `AGENTS.md`, and architecture
documents now reflect the merged Venue Availability ownership.

`VenueBooking` supplies the fields needed for a booking-based day/week/month
calendar and overlap detection. All three internal roles can inspect ranges
and choose one venue from a simple selector. Venue search/filtering and
booking submission are separate work, not prerequisites for this read UI.
Approved bookings block selection; pending requests are displayed but do
not block. Rejected/cancelled requests are excluded from calendar reads.
The SCRUM-25 read-only live smoke confirmed `Approved`, `Pending` and `Rejected`
values; the existing write code emits `Pending Review`, which the reader also
supports. Unknown/null relevant statuses fail closed. No live rows were changed.

Scheduled maintenance/operational blocks (`venueBlock`) are **deferred to
next sprint**. The current schema cannot represent those intervals.
`Venue.operational_status` is not a substitute for a dated block. This sprint
therefore covers booking-based availability only, not the original plan's
recorded operational-block coverage. Record that scope reduction in Jira;
do not claim the full Week 4 unavailability requirement is complete.

### Schema sufficiency and implementation prerequisites

| Check | Supplied schema | Required handling |
|---|---|---|
| Booking identity and relationships | UUID PK; FKs to Event, Venue and User | Existing references support the model; foreign-key columns remain nullable. |
| Booking range | Both fields are `timestamp without time zone`, nullable | SCRUM-25 interprets existing naive values as Singapore local; reads accept naive or offset ISO datetimes and output `+08:00`. No type migration was applied. |
| Required values | Only `booking_id` is `NOT NULL` | Require venue, event, requester, start, end and status in write validation; audit/backfill before adding DB `NOT NULL` constraints. Never silently treat malformed rows as free time. |
| Range validity | No end-after-start check shown | Validate end > start; add a DB CHECK after auditing existing data. |
| Status | Unconstrained nullable varchar | Inspect distinct live values and agree one canonical enum/check before mapping approved/pending states. |
| Concurrent approvals | No overlap exclusion constraint shown | Recheck and save under a transaction-safe per-venue lock or equivalent DB enforcement. Every blocking write must follow the same rule. |
| Query performance | PKs shown; secondary indexes not supplied | Inspect live indexes; add a venue/time-range index if needed. |
| Internal-only access | User role field exists; JWT linkage/policies not established by this export | Production auth remains deferred. SCRUM-25 tests direct external-role denial only in opt-in, spoofable DEV header simulation; never claim real identity enforcement. |

No new booking columns are required for basic conflict computation. However,
the schema alone does not enforce valid intervals, canonical statuses or
no-double-booking, and it does not implement authentication or calendar APIs.
An approved event is not automatically an approved venue booking.

Query intervals as start-inclusive, end-exclusive: an overlap exists when
`existing_start < range_end AND existing_end > range_start`. Exclude the
current booking ID when checking an edit. For calendar reads, return pending
records as well as approved records; only approved records block selection.

Example parameterized read (assuming the intended quoted table name has
been confirmed). Bind timezone-naive boundaries using the agreed convention
while the database retains `timestamp without time zone`:

```sql
SELECT booking_id, venue_id, requested_start_time, requested_end_time, status
FROM public."VenueBooking"
WHERE venue_id = %s
  AND requested_start_time < %s  -- visible range end
  AND requested_end_time > %s    -- visible range start
ORDER BY requested_start_time, booking_id;
```

### Existing application compatibility

The checked-out Event Service now queries `public."Event"` (verified in
`services/event-service/app/models.py`), not the earlier `public.event_service`.
Venue Availability queries `public."VenueBooking"`; its SCRUM-25 live smoke
verified the quoted table, UUID identity columns and naive timestamp columns,
and exercised the actual GET through a Flask test client with read-only DB
transactions. This does not verify every service, RLS policy or write workflow.

There is **no Postgres-level schema wall** between services — all tables
share `public`, so the database itself won't stop your service from
querying another service's table. Per `AGENTS.md`'s service boundaries,
still only read/write the table(s) your service owns; if you need data from
another service, go through that service's HTTP API, not its table
directly.

## 6. Example: connecting from Flask

```python
import os
import psycopg2

def get_connection():
    return psycopg2.connect(os.environ["DATABASE_URL"])

# Example: read from the table your service owns
with get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute("select event_id, event_name, status from public.\"Event\" limit 10;")
        rows = cur.fetchall()
```

(If you're using SQLAlchemy instead, point `create_engine()` at the same
`DATABASE_URL`.)

## 7. If you need to change the schema (add columns, add a table)

This requires the Supabase CLI, which is already scaffolded in this repo
under `database/supabase/`. This checkout includes
`20260927100000_add_venue_id_to_event.sql` and
`20260927110000_create_venue_booking.sql`; their presence does not prove their
application to the shared database. Confirm the baseline before applying new
migrations. No migrations were applied for SCRUM-25. The CLI expects
its `supabase/` folder to be in your current directory, so run these from
`database/`, not the repo root:

```
brew install supabase/tap/supabase   # one-time, if you don't have it
cd database
supabase login                        # opens a browser — needs your Supabase account to have access to the project
supabase link --project-ref gjrbkvljlvroghwvhjtc
supabase migration new <name>
# edit the generated file in supabase/migrations/
supabase db push
```

Don't make schema changes directly in the Supabase dashboard SQL editor —
migrations should be committed so everyone's local history matches the
remote project. Coordinate with the team before changing a table another
service's code already depends on.

## Equipment table conventions

Equipment Service (`services/equipment-service/`) expects these values in
`public."Equipment"`; migration
`20261002120000_normalize_equipment_catalogue.sql` converted the original rows
to match.

- `equipment_type` — a class name from the Equipment OO model:
  `Microphone`, `LightingKit`, `Projector`, `Laptop`, `Furniture`, `Table`,
  `Chair`, `Speaker`. Technical Support can also add other types through the
  UI ("Add new…"); those are stored as typed (max 100 characters) and use the
  base `Equipment` class.
- `operational_status` — `Available` or `Unavailable`.
- There are no check constraints; the service validates `POST /equipment`.
- Mock rows: `cd services/equipment-service && uv run python scripts/seed_equipment.py`
  (idempotent; run the migration first).
