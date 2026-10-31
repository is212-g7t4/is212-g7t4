# Supabase setup — for team members

How to configure a service for the shared Supabase database. The baseline
column reference is [db-structure.md](db-structure.md); later migrations in
`database/supabase/migrations/` add features such as notification outboxes.
Compose startup does not apply migrations or create accounts. Check the deployment
with the team before applying missing migrations; never rerun shared setup blindly.

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

For each existing service, start from its own `.env.example`; create `.env` only
if it is missing, then fill in the team-approved values. From the repository root:

```
service=equipment-request-service  # choose the service you need
[ -f "services/$service/.env" ] || cp "services/$service/.env.example" "services/$service/.env"
```

Set `service` to the real directory name before using the command.
Configure its server-side `DATABASE_URL` using the team-approved session-pooler
connection string; examples may contain placeholders, not working credentials.
For Compose, configure the root `.env` as well: it supplies shared settings such
as `SUPABASE_URL`, `SUPABASE_ANON_KEY` and `INTERNAL_SERVICE_TOKEN`. Preserve
service-specific database values in the `env_file` paths declared by Compose.

Use the approved project URL and anon/publishable key. Database credentials,
service-role keys and the shared internal-service token are server-side secrets;
never put them in frontend `VITE_*` settings.

**Never commit `.env`** — it's already covered by `.gitignore`.

## 3. Important: connect via `DATABASE_URL`, not the Supabase client

The supplied schema export does **not** include RLS settings, policies or
role grants. Their current state has not been verified; do not assume that
an anonymous Supabase client can read these tables, or that RLS protects
requests made through a privileged backend connection.

The existing backend pattern is `DATABASE_URL` with a Postgres driver.
Keep that connection server-side. A privileged `postgres` connection can
bypass RLS, so each service verifies the caller's Supabase Auth token itself
(see below) before applying its own role rules.
Inspect live policies and grants before enabling direct browser data access.

### Supabase Auth (SCRUM-8)

Sign-in uses Supabase Auth's email + password grant, called only by User
Service's `POST /auth/login` with `SUPABASE_URL` and `SUPABASE_ANON_KEY`.
Every `auth.users` row has the same id and email as its `public."User"` row;
accounts are created in Supabase (there is no sign-up).

Each service verifies access tokens against the project's JWKS
(`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`, ES256, audience
`authenticated`). The caller's role is read from the **`user_role`** claim,
which `public.custom_access_token_hook` copies from `public."User".role`. That
hook must be enabled under **Authentication → Hooks → Customize Access Token
(JWT) Claims**; without it tokens carry no role and every role check answers
`403`.

## 4. Add a Postgres driver to your service

A new service has no Postgres driver until you add one. From your service directory:

```
cd services/<your-service>
uv add psycopg2-binary
# or, if you want an ORM:
uv add sqlalchemy psycopg2-binary
```

## 5. The tables

The tables below match [db-structure.md](db-structure.md), the final Week 7
structure, which is created by migration
`20261011140000_baseline_schema.sql`. Column names are `snake_case`.
Table names are PascalCase, and PostgreSQL folds unquoted identifiers to
lowercase, so use double quotes (for example `public."VenueBooking"`). To
confirm the stored names:

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
ORDER BY table_name;
```

All time columns are `TIMESTAMPTZ`. Existing values were converted from naive
Singapore local time as `Asia/Singapore`. psycopg2 returns them timezone-aware
(in the session's zone, UTC on Supabase), so convert before treating them as
Singapore local. Event Service and Venue Availability keep their HTTP APIs in
naive Singapore-local time and convert at the database boundary: naive input
is bound as `Asia/Singapore`, and values read back are turned into Singapore
local time. Binding a naive value directly would be read as UTC, 8 hours off.
`Event.submission_date` and `Registration.registration_date` are returned with
their offset.

| Table | Owning service | Key columns |
|---|---|---|
| `public."Event"` | Event | `event_id` (PK), `event_name`, `status`, `organiser_id`, `coordinator_id`, `registration_enabled` (an event's venue is its `VenueBooking` rows) |
| `public."EventChangeReq"` | Event | `change_id` (PK), `event_id`, `requested_changes` (jsonb), `status`, `request_date`, `requested_by`, `reason`, `reviewed_by` |
| `public."Equipment"` | Equipment | `equipment_id` (PK), `equipment_type`, `total_quantity`, `operational_status` |
| `public."User"` | User | `user_id` (PK), `username`, `email` (unique), `role` (the Lead is role `Event Coordinator Lead`) |
| `public."Venue"` | Venue | `venue_id` (PK), `venue_name`, `max_capacity`, `facilities` (jsonb), `setup_time_minutes`, `turnaround_time_minutes`, `operational_status` |
| `public."VenueBooking"` | **Venue Availability** | `booking_id` (PK), `event_id`, `venue_id`, `requested_start_time`, `requested_end_time`, `required_capacity`, `status`, `held_by`, `hold_expires_at`, `conflict_reason`, `closure_id` |
| `public."VenueClosure"` | Venue Availability | `closure_id` (PK), `venue_id`, `start_date_time`, `end_date_time`, `reason` |
| `public."EquipmentRequest"` | Equipment Request | `equipment_request_id` (PK), `event_id`, `equipment_id`, `quantity_requested`, `quantity_reserved`, `requested_by`, `reviewed_by` |
| `public."Registration"` | Registration | `registration_id` (PK), `event_id`, `attendee_id`; unique on both |
| `public."Notification"` | Notification | `notification_id` (PK), `recipient_id`, `event_id`, `dedupe_key`, `read_at` |
| `public."SafetyCheck"` | Safety Check | `safety_check_id` (PK), `event_id`, `round_number`, `status`; unique on `(event_id, round_number)` |
| `public."SafetyCheckFlag"` | Safety Check | `flag_id` (PK), `safety_check_id`, `booking_id`, `equip_request_id` |

There is no `VenueHold` table any more. A hold is a `VenueBooking` row with
status `On Hold` (see below).

### Venue Availability ownership and this sprint's scope

Venue Availability now owns booking records, holds, venue closures and conflict checking.
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
next sprint**. The schema now has `VenueClosure` for dated blocks, but the calendar service does not read it yet.
`Venue.operational_status` is not a substitute for a dated block. This sprint
therefore covers booking-based availability only, not the original plan's
recorded operational-block coverage. Record that scope reduction in Jira;
do not claim the full Week 4 unavailability requirement is complete.

### Schema sufficiency and implementation prerequisites

| Check | Supplied schema | Required handling |
|---|---|---|
| Booking identity and relationships | UUID PK; FKs to Event, Venue and User | Existing references support the model; foreign-key columns remain nullable. |
| Booking range | Both fields are `TIMESTAMPTZ NOT NULL` | Existing values were converted as Singapore local time. Reads accept naive or offset ISO datetimes and output `+08:00`. |
| Required values | `requested_start_time`, `requested_end_time` and `required_capacity` are `NOT NULL`; every other column, including `event_id`, `venue_id` and `venue_requirements`, is nullable (a hold has no event) | Require venue, event, requester, start, end and status in write validation. Never silently treat malformed rows as free time. |
| Range validity | No end-after-start check shown | Validate end > start; add a DB CHECK after auditing existing data. |
| Status | Unconstrained nullable varchar | Inspect distinct live values and agree one canonical enum/check before mapping approved/pending states. |
| Concurrent approvals | No overlap exclusion constraint shown | Recheck and save under a transaction-safe per-venue lock or equivalent DB enforcement. Every blocking write must follow the same rule. |
| Query performance | PKs shown; secondary indexes not supplied | Inspect live indexes; add a venue/time-range index if needed. |
| Internal-only access | User role field exists; RLS policies not established by this export | Services verify the Supabase Auth token (SCRUM-8) and apply their own role rules over the privileged connection. |

Conflict computation itself needs no additional booking columns. The
`required_capacity` and `venue_requirements` columns are instead required for
per-booking suitability and display. The schema alone does not enforce
canonical statuses or no-double-booking, and it does not implement
authentication or calendar APIs.
An approved event is not automatically an approved venue booking.

Query intervals as start-inclusive, end-exclusive: an overlap exists when
`existing_start < range_end AND existing_end > range_start`. Exclude the
current booking ID when checking an edit. For calendar reads, return pending
records as well as approved records; only approved records block selection.

Example parameterized read (assuming the intended quoted table name has
been confirmed). Bind timezone-aware boundaries (naive input is treated as Singapore local
and given `+08:00` first):

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
verified the quoted table and UUID identity columns (the timestamp columns have since become `TIMESTAMPTZ`),
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
under `database/supabase/`. The whole schema is one baseline migration,
`20261011140000_baseline_schema.sql`, generated from the shared project on
11 Oct 2026; it replaced every earlier migration file. Add new migrations
after it. If `supabase migration list` shows versions that exist on only one
side, fix the history with `supabase migration repair` before running
`supabase db push`, never by re-running old files. The CLI expects
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

## Mock data

`database/supabase/seed.sql` holds the shared project's mock data in the
Week 7 structure. `supabase db reset` (local) runs it after the migrations.
To reset the shared project's data to it, run
`psql "$DATABASE_URL" -f database/supabase/seed.sql`. It **empties every
public table first**, so check with the team before running it on the shared
project.

## Equipment table conventions

Equipment Service (`services/equipment-service/`) expects these values in
`public."Equipment"`; the rows in `database/supabase/seed.sql` already
match.

- `equipment_type` — a class name from the Equipment OO model:
  `Microphone`, `LightingKit`, `Projector`, `Laptop`, `Furniture`, `Table`,
  `Chair`, `Speaker`. Technical Support can also add other types through the
  UI ("Add new…"); those are stored as typed (max 100 characters) and use the
  base `Equipment` class.
- `operational_status` — `Available` or `Unavailable`.
- There are no check constraints; the service validates `POST /equipment`.
- Mock rows: `cd services/equipment-service && uv run python scripts/seed_equipment.py`
  (idempotent; run the migration first).
