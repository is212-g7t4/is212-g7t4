# SCRUM-45 manual testing — shared Supabase DEVELOPMENT

Current instructions: October 23, 2026. These supersede the **manual startup**
sections of older SCRUM-45 evidence; those documents retain their historical
results. **Manual testing uses the team's existing, persistent Supabase
DEVELOPMENT database. It does not require local Postgres, `psql`, a database
copy, or disposable owner databases.** UI actions below persist real development
records/notifications. Coordinate with the team; never use production or somebody
else's event. No shared migrations, data mutations or container restarts were
performed during this sync.

## 1. Use this checkout, preserve configuration

```sh
cd '/Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-integration'
git branch --show-current
# SCRUM-45-event-organiser-status-and-update-notifications
docker compose config --quiet
```

The root `.env` and existing service `.env` files are already present. Do not
recopy the root file over service files or replace manually entered values.
Never paste credentials, print `.env`, or print resolved `docker compose config`.
The quiet validation above succeeded in this checkout.

Current Compose rules (including main's SCRUM-173 fix):

- Event loads optional root `.env`, then `services/event-service/.env` (service DB
  wins). Compose explicitly supplies the nonempty **root** `INTERNAL_SERVICE_TOKEN`.
  HTTP workers must use that same token; stale service-file tokens do not override it.
- Notification API **and** consumer use root
  `NOTIFICATION_DATABASE_URL`, falling back to root `DATABASE_URL`. They **do not
  load** `services/notification-service/.env` under Compose. The user-created file
  is preserved; it can matter when launching the service directly, not here.
- Read-only verification confirmed effective Event and Notification DSNs are the
  **same shared development database**. Keep the existing intended settings; do
  not split/copy that DB to imitate the automated harness.
- Root `NOTIFICATION_DEV_MODE=true` was verified. This enables the prototype's
  selected-user inbox headers; it is not production authentication. User Service
  must return actual users/roles and nonblank `username` values for coordinators.
- Compose defaults CORS to `http://localhost:5174`; Vite pins 5174 with strict-port
  checking. Keep `COMPOSE_FRONTEND_ORIGIN`/frontend origin settings aligned if
  deliberately choosing another port. Frontend `VITE_*_SERVICE_URL` overrides must
  address the matching manual backend, not a test harness or stale deployment.

## 2. Read-only schema gate — currently BLOCKED for SCRUM-45

Use the **correct development project's Supabase SQL Editor** (no local DB client
needed). Confirm the project with the team before running even this read-only check:

```sql
BEGIN READ ONLY;
SELECT
  to_regclass('public."Notification"') AS inbox,
  to_regclass('public."NotificationFailure"') AS failure_log,
  to_regclass('public."VenueNotificationOutbox"') AS venue_outbox,
  to_regclass('public."EventNotificationOutbox"') AS event_outbox;
SELECT version FROM supabase_migrations.schema_migrations ORDER BY version;
SELECT column_name FROM information_schema.columns
 WHERE table_schema = 'public' AND table_name = 'EventNotificationOutbox'
 ORDER BY ordinal_position;
ROLLBACK;
```

The October 23 check used a read-only PostgreSQL transaction against the effective
Compose Event connection: Notification, NotificationFailure and
VenueNotificationOutbox exist; **EventNotificationOutbox does not**. Recorded
migration versions end at `20261017000001`; the three SCRUM-45 versions below
are absent. Existing Event columns include `rejection_reason`, `assigned_by`,
`assigned_at`, `previous_coordinator_id`; Notification has `source_id`.

**Do not attempt notification mutations/dispatcher startup until the team's
migration owner has reviewed and applied the pending files to this shared
DEVELOPMENT project, in this order:**

1. `database/supabase/migrations/20261021000000_event_notification_outbox.sql`
2. `database/supabase/migrations/20261021000100_event_approval_notifications.sql`
3. `database/supabase/migrations/20261021020000_event_notification_assignments.sql`

These create Event's outbox, extend its allowed types for approval/assignment,
and add `held_at`. They were **not applied by this task**. Recheck the table,
`held_at` column and installed type constraint for `event.rejection`,
`event.approval`, `event.coordinator-assignment` after the authorised migration.
Do not replay the baseline/all migrations onto this populated DB; don't reapply
`20261017000000_notification_inbox.sql` merely because Notification is being
reconfigured. The schema/history check is the prerequisite, not a localhost
Postgres setup. Delivery is for **new changes only**, not automatic backfill.

## 3. Stack/worker ownership gate, then startup

The original **`is212-g7t4-*` manual stack was running and left untouched**. Its
API ports 5001–5015 (as listed by Compose), broker 5672/15672, and possibly a
frontend already occupy this machine. A different project name alone does not
avoid published-port conflicts. Do not run this checkout's `npm run dev`,
`docker compose up`, `npm run stop`, or `docker compose down` against that stack
without an agreed handover. In particular, root `stop` force-kills port 5174.

Before startup, agree with its owner which checkout, ports and broker are used.
Also agree that **one intended event-outbox dispatcher owns claims against the
shared Event DB**, and that its broker's Notification consumer writes to the
intended shared Notification DB. Two projects with separate brokers but the same
Event outbox can claim each other's work and send it to different brokers. An old
consumer competing on a shared queue may not support these new event types.
Don't independently stop/restart another person's workers or purge queues.

Only **after both gates and an authorised handover/free ports**, from this root:

```sh
docker compose config --quiet
docker compose up --build -d
docker compose ps
for port in 5001 5003 5004 5015; do
  curl --fail --silent --show-error "http://localhost:$port/health"
  printf '\n'
done
docker compose logs --tail=50 event-notification-dispatcher notification-consumer
npm --prefix frontend/event-management-ui ci
npm run dev:frontend
```

Expected: owning APIs respond 200 with `status: ok`; dispatcher and consumer
remain running after broker readiness. Health alone does **not** prove schema or
delivery. Inspect errors locally; redact secrets/personal data before sharing.
The new dispatcher is a separate Compose service, not part of the frontend or
Event HTTP process. Startup/handover above was **not executed** during this sync.

## 4. Persistent development UI checks (after gates)

Use uniquely named **team-approved test events** and existing test identities;
record their IDs for the team. `Viewing as` / **Select active user** switches demo
identity. Do not assume changing a display role grants authority to decide an
event assigned to another coordinator.

1. **Initial assignment:** select an Event Organiser; **Submit event** and complete
   required fields, then **Submit Request** (not **Save as Draft**). Select the
   **Event Coordinator Lead**. Under **Events → Unassigned requests**, click
   **Refresh queue**, choose **Coordinator**, then **Assign**. For the Lead-decision
   scenario choose the Lead as the assigned coordinator where available. Switch
   back to the original organiser; open the notification bell/inbox, use
   **Refresh notifications**, and find `<username> has been assigned to coordinate
   <event name>.` It must open the matching event via **Open notification**.
2. **Approval:** on a separate submitted/assigned event, select its assigned Lead
   (or actual assigned coordinator under the current prototype's decision rules),
   open **Events → Request review** (`/requests/review`), **Refresh requests**, and
   **Approve Request**. Expect **Event Request Approved**. As the original
   organiser, refresh notifications: `<event name> was approved`; open it and
   verify the matching event's Approved decision, not a rejection reason. Initial
   assignment and approval are **distinct notifications**, not duplicates.
3. **Rejection:** use another submitted event assigned to the acting Lead. In
   **Request review**, **Reject Request** opens **Reject event request?**. Fill
   **Reason for rejection**, **Confirm rejection**; expect **Event Request
   Rejected**. Original organiser refreshes inbox and opens the delivered entry:
   correct event/name, Rejected decision, exact **Rejection reason**. Opening
   changes unread to read; a page reload must preserve read state.
4. **Reassignment:** as Lead, on an eligible active assigned event use **Reassign
   Coordinator**, choose **New coordinator**, **Confirm Reassignment**. Organiser
   gets a separate named update linked to that event. Repeat with another
   coordinator; the earlier notification must keep the earlier person's name.
   Choosing the current coordinator is a no-op/error and must not add a message.
5. **Isolation/regression:** another organiser must not see these entries. Existing
   venue notifications and their destinations must still work. Do not use shared
   broker outages, destructive schema changes, forced replay, or queue purge to
   test failure paths manually: those are covered in the disposable suite.

Missing/blank coordinator names hold assignment delivery; they must not fabricate
a name or block unrelated decisions. Ask the owner to inspect authenticated
`GET /internal/notification-outbox/held`; after correcting the specific user's
`username`, an authorised operator can release that source via
`POST /internal/notification-outbox/<source-id>/release` with `{}` and the internal
token. Never print the token or run bulk repair. Leave persistent test records
for agreed team cleanup; don't truncate/reset this development DB.

## 5. Automated checks are a different environment

The opt-in cross-service tests now live in **repo-root `e2e/scrum45/`**, not a
service's `tests/integration/`. They start their own UUID-named Docker Postgres 17
and RabbitMQ 4 containers, random loopback API/UI ports, separate synthetic owner
DBs, allowlisted subprocess environments, and **disabled dotenv**. These test
DBs are disposable; the shared Supabase DEVELOPMENT DB above is not.

With Docker running, service-local locked dependencies installed (`uv sync
--locked` in Event, Event Workflow, Notification, User, Coordinator Assignment
and Venue Availability), frontend `npm ci` and Playwright Chromium installed:

```sh
# From the exact repository root in §1; no shared credentials supplied.
env -i HOME="$HOME" PATH="$PATH" \
  TMPDIR=/Users/daphnetok/.hermes/cache/scratch \
  PYTHON_DOTENV_DISABLED=1 FLASK_SKIP_DOTENV=1 \
  uv run --no-project --with pytest --with httpx --with psycopg2-binary \
  python -m pytest e2e/scrum45 --tb=short -ra \
  --basetemp=/Users/daphnetok/.hermes/cache/scratch/scrum45-manual-isolated
```

This runs 26 real cross-service cases including one unmocked browser rejection
journey and verifies owned-resource cleanup. Don't replace it with a broad
`pytest -m integration` or `-m live`: those select different suites, and live
checks can target Supabase. Full commands/results and remaining warnings are in
`scrum-45-main-sync.md`. No manual shared-development delivery success is claimed
until the pending schema and stack-ownership gates are satisfied.
