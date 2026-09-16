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

Every table has Row Level Security (RLS) turned on with **no policies**
defined yet. That means:

- If you connect with `DATABASE_URL` (the `postgres` role) — RLS doesn't
  apply to this role. Full read/write access, works normally.
- If you use the Supabase client library (`supabase-py`, JS client, or the
  REST API) with `SUPABASE_ANON_KEY` — every query returns zero rows and
  every write is rejected, because RLS defaults to deny with no policies.

So for now, always use `DATABASE_URL` with a regular Postgres driver/ORM,
not the Supabase SDK, to read or write these tables.

## 4. Add a Postgres driver to your service

The service templates don't include one yet. From your service directory:

```
cd services/<your-service>
uv add psycopg2-binary
# or, if you want an ORM:
uv add sqlalchemy psycopg2-binary
```

## 5. The tables

All 8 tables live in the **public** schema of the `is212-g7t4` project (ref
`gjrbkvljlvroghwvhjtc`). Full column definitions are in
[`database/supabase/migrations/20260912150524_create_service_tables.sql`](../database/supabase/migrations/20260912150524_create_service_tables.sql)
— that file is the source of truth; the summary below is just an index.

| Table | Owning service | Key columns |
|---|---|---|
| `event_service` | Event | `event_id` (PK), `event_name`, `status`, `organiser_id`/`coordinator_id` → `user_service.user_id` |
| `event_changereq` | Event (change requests) | `change_id` (PK), `event_id` → `event_service`, `reviewed_by` → `user_service` |
| `equipment_service` | Equipment | `equipment_id` (PK), `equipment_type`, `total_quantity` |
| `user_service` | User | `user_id` (PK), `username`, `email`, `role` |
| `booking_service` | Booking Conflict | `booking_id` (PK), `event_id`/`venue_id`/`requested_by`/`reviewed_by` (FKs) |
| `venue_service` | Venue | `venue_id` (PK), `venue_name`, `max_capacity`, `facilities` (jsonb) |
| `registration_service` | Registration | `registration_id` (PK), `event_id`/`attendee_id` (FKs) |
| `equipment_request` | Equipment Availability | `equipment_request_id` (PK), `event_id`/`equipment_id`/`reviewed_by` (FKs) |

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
        cur.execute("select event_id, event_name, status from event_service limit 10;")
        rows = cur.fetchall()
```

(If you're using SQLAlchemy instead, point `create_engine()` at the same
`DATABASE_URL`.)

## 7. If you need to change the schema (add columns, add a table)

This requires the Supabase CLI, which is already scaffolded in this repo
under `database/supabase/` (`config.toml`, `migrations/`). The CLI expects
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
