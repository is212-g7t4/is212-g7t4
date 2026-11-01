# E2E journeys: traceability

Real-stack Playwright journeys. Manual and opt-in (never in CI): start the stack, then `npm run test:journeys` from the repo root.

## Isolated local runs

With Docker Desktop running, execute from the repository root:

```powershell
npm run test:journeys:isolated
npm run test:journeys:isolated -- --grep J2
```

Install root/frontend npm dependencies and Playwright Chromium first. No manual
frontend/backend startup or Supabase CLI is required. Each run creates a unique
Compose project with loopback-only dynamic ports, a fresh Postgres database,
real Supabase Auth (ES256/JWKS and role hook), RabbitMQ, all backend services,
notification dispatchers/consumer and a Vite frontend. All journeys in that run
share this disposable stack; it is separate from development and teammates.
The committed migrations and seed catalogue provision matching Auth accounts
with generated passwords. Development `.env` files are not loaded. Storage,
Studio and Realtime are omitted because journeys do not use them.

Reports/traces use run-specific subfolders under `report/` and `test-results/`;
the runner prints the report command. Exit, failures and Ctrl+C trigger teardown
of that run's containers and volumes. Force-killing the process or stopping
Docker can prevent cleanup. The temporary configuration path is printed at
startup; on teardown failure it is preserved with an exact recovery command.
It contains generated credentials: do not share or commit it.

Isolated helpers refuse missing service mappings or a non-loopback cleanup
database rather than falling back to shared data. The existing manual command
and existing unit tests are unchanged. This restores isolation only, not the
application fixes identified in earlier runs: equipment submission, staff
event-detail rendering and safety-rejection venue release can still fail their
journeys until addressed separately. Isolation does not guarantee green tests.
No CI changes are included.

Check isolation wiring without starting Docker:
`node --import tsx --test e2e/helpers/environment.test.ts e2e/isolated/model.test.mjs`.

The shared `openAs` helper injects the role session only on the app's origin
(`FRONTEND_URL`, default `http://localhost:5174`). It skips the initial
`about:blank` document and unrelated origins, avoiding storage-access errors
during page creation without suppressing real browser errors. Verify this in
Chromium without a running stack or real credentials:
`node --import tsx --test e2e/helpers/stack.test.ts`.
The check covers default/custom origins, role identity, refresh persistence,
other-origin isolation and absence of page errors. Chromium must already be
installed (`npx playwright install chromium`).

Cleanup reads `DATABASE_URL` from the root `.env`. URL-encoded credentials are
decoded once before connecting; keep the same valid database URL used by the
services. Test this parser without accessing a database with
`node --import tsx --test e2e/helpers/cleanup.test.ts`.
The isolation integration test uses its own disposable `postgres:17.6`
container and synthetic tables with foreign keys, never the shared Supabase
database. With Docker running, execute from the repo root in PowerShell:

```powershell
$env:RUN_CLEANUP_INTEGRATION = '1'
node --import tsx --test e2e\helpers\cleanup.integration.test.ts
Remove-Item Env:\RUN_CLEANUP_INTEGRATION
```

It verifies two concurrent teardowns, preservation of another journey and a
same-journey lookalike name, partial setup, repeated cleanup, renamed J6a
fixtures and old-name outbox intents, J6b bookings on a shared seeded venue,
and refusal to remove another event's venue bookings. The container and its data are removed
after the test.

Every journey must limit cleanup to its own run's exact event and venue names:

```ts
const runId = randomUUID() // import from node:crypto; generate once per run
const scope = {
  eventNames: [`J6a Event A ${runId}`, `J6a Event B ${runId}`],
  venueNames: [`J6a Venue ${runId}`],
}
test.afterAll(async () => { await deleteFixtureEvents(scope) })
```

`deleteFixtureEvents` requires both arrays (use `[]` for an unused entity).
It compares names by exact equality, never a prefix, wildcard or journey-wide
regex. Calling it without a scope fails before connecting. The single-event
`deleteNamedFixtureEvents({ eventName, venueName })` helper uses the same path.
Cleanup removes notification outbox dependencies first and refuses to delete a
venue still booked by an event outside the scope. It also cleans up partially
created fixtures when a journey's setup fails. Keep the scope outside setup so
teardown knows the names even if seeding throws.

J1, both J5 paths and both J6 paths use UUID run identifiers and run-scoped teardown. No run
automatically sweeps fixtures from older or interrupted runs. To recover those,
explicitly supply the exact names belonging to the abandoned run.
If a test renames an event, include every possible name in `eventNames`, keeping
the fixture prefix and the same run ID. J6a includes its original and proposed
names so approval and partial failures both clean up correctly. J6b supplies no
venue names because it uses a pre-existing seeded venue: only its own event and
dependent booking are removed, never that shared venue.

For manual J5b codegen fixtures, `npm run journey:fixtures` prints a run ID and
its cleanup command. Keep that ID, then run
`npm run journey:fixtures:clean -- <run-id>` to remove only that run. Cleanup
without an ID is rejected. An optional seed ID can be passed using
`npm run journey:fixtures -- <unique-run-id>`.

All testers must use this updated helper and scoped callers: an older checkout
or custom cleanup script can still delete another run's data in the shared
database. Run-scoped cleanup prevents cross-run deletion, not business-resource
conflicts: use separate fixture venues and non-overlapping equipment windows
(or separate test databases) when running concurrently. Unique event IDs alone
do not isolate shared stock.

Notification delivery also shares database outboxes. Dispatchers on different
machines claim from those same tables without a journey/run owner; each
dispatcher publishes to its configured RabbitMQ. Run-scoped cleanup does not
isolate this path. All participating delivery stacks must have working consumers
writing to the intended shared Notification database. Otherwise an intent can
be marked published by another stack without reaching the inbox used by a test.
For diagnosis, pause the competing `event-notification-dispatcher` (not merely
its frontend, test runner or consumer), confirm its stopped status, and rerun
with a fresh fixture. Do not reset shared published jobs or purge broker queues.
One shared delivery stack or separate test databases avoids cross-stack claims.

J6a now refreshes while waiting for asynchronous approval/rejection notifications
(up to two minutes per decision), and still requires exactly one matching
decision notification and the rejection reason. Its six-minute test budget
allows both delivery waits and the UI flow. Live diagnosis found a successful
change approval and a published outbox intent but no matching inbox row; a
passing concurrent delivery run is not yet verified.

J7 seeds run-owned Confirmed events through service APIs and verifies registration,
repeat, capacity, withdrawal and notification outcomes across attendee, coordinator
and organiser views. The full-event fixture is occupied by the second seeded
Attendee. The closed-registration case reads a past Confirmed event from the seed
catalogue because the attendee browse page intentionally omits events that have
already started; the journey only attempts registration against that event and
never mutates or cleans it.

J1 has passed all nine steps against the live stack with run-scoped cleanup.
It verifies the persisted safety decision through the assigned Coordinator's
feedback endpoint (not the pending-review endpoint after confirmation), including
the officer, remarks and decision timestamp. Attendee registration is checked
after refresh in both the event count and My registrations, followed by matching
Organiser/Coordinator registration visibility and the attendee notification.
The venue queue uses bounded refresh retries for transient loading failures,
allowing each in-flight load to finish before refreshing again.
The Safety Officer queue also provides a Refresh safety checks button, disabled
while loading. J1 retries only HTTP 502/503/504 responses from that queue, with
at most three load attempts; other errors and exhausted retries report the HTTP status
and response body instead of waiting for a missing event card. A temporary
fault-injection validation returned two queue 502s and verified that J1 refreshed
and completed all nine steps; all other calls in that run used the real stack.
Persistent component tests cover failed-load recovery, repeated failures and
refreshing a decided event out of the queue. After the recovery change,
`npm run test:journeys -- --grep J1 --repeat-each=2` passed both full live runs
without injected failures.

J1 Path B lives under `J1/J1b-coordinator-rejection/`. Its run-owned event is
created and assigned through service APIs; rejection and organiser verification
use the UI. It checks the required reason, Rejected status/reason after refresh,
the organiser's rejection notification (including the reason), and persisted
decision/action history with no approval recorded. Cleanup names only that run's
event. Its exact rejection/notification story attribution remains provisional
using the existing J1 keys, pending confirmation.
Run just Path B with `npm run test:journeys -- --grep J1b`, or both J1 paths
with `npm run test:journeys -- --grep J1`.

J5a also waits for each Venue Staff queue response and retries only HTTP
502/503/504 through Refresh requests, up to three load attempts per approval.
Persistent errors report the HTTP status/body; booking conflicts and rejected
approval decisions are not retried. The refresh button is disabled during a
load to prevent overlapping requests. Recovery waits for that button to become
enabled and checks the rendered error state, not just the first HTTP response:
React StrictMode can issue an ignored first request that succeeds before the
active request fails. A targeted fault-injection run reproduced this
first-200/second-502 sequence and completed the journey after UI refresh.
A component regression covers the same StrictMode ordering.
J5a has its own five-minute timeout for
the two staff queue loads and bounded recovery on the populated live stack.
The full live journey passed, and a temporary fault-injection run also passed
after two queue 502s before Event B review, while retaining both real approval
decisions and the buffer-only conflict rejection. Component tests cover queue
recovery, preventing duplicate refreshes, and persistent refresh failures.

After updating notification-consumer source, rebuild its container so it uses
the existing foreign-key quarantine handling for delayed messages whose fixture
events have already been deleted:
`docker compose up -d --build --no-deps notification-consumer`.
This preserves the broker queue and volumes; do not purge shared notifications
to recover a test.

| Journey | Spec | Jira task | User stories exercised | Fixture-only dependencies | Status |
|---|---|---|---|---|---|
| J1 Path A: Complete an event from submission to attendee registration | `J1/J1-complete-event-to-registration/` | SCRUM-255 | SCRUM-11, 13, 19, 28–30, 32–38, 40–41, 44–48, 149–150, 158–159, 162–163, 166, 168 | SCRUM-8, 31 | Live pass: all nine steps, including persisted safety audit, refreshed attendee registration, role totals and confirmation notification (story keys provisional) |
| J1 Path B: Coordinator rejects an assigned event | `J1/J1b-coordinator-rejection/` | SCRUM-255 | SCRUM-13, 19, 44–48, 166, 168 (provisional J1 keys; exact attribution pending) | SCRUM-8, 11, 159 | Live pass: rejection with reason, organiser status/reason after refresh, rejection notification and no approval in persisted history |
| J2A: Refuse protected event access | `J2/J2a-access-denied/` | SCRUM-256 | SCRUM-8, 9, 10 | SCRUM-8, 11, 159 | Live pass: anonymous, wrong-role, non-owner and unassigned access refused; owner retains access and rejected writes leave the event unchanged |
| J2B: Transfer event responsibility to a new Coordinator | `J2/J2b-responsibility-transfer/` | SCRUM-256 | SCRUM-8, 9, 10, 159, 160, 166 | SCRUM-8, 11 | Live pass: UI assignment/reassignment and history, new Coordinator manages, old access denied, and both reassignment notifications received |
| J3A: Block safety review until arrangements are ready | `J3/J3a-safety-gate/` | SCRUM-257 | SCRUM-19, 149, 152 | SCRUM-8, 11, 28, 29, 32, 33, 34, 159 | Live pass: pending venue and equipment block submission and direct confirmation; rejecting equipment is non-blocking, then safety approval confirms the event |
| J3B: Revise flagged arrangements and resubmit for safety review | `J3/J3b-safety-changes/` | SCRUM-257 | SCRUM-150, 151, 164 | SCRUM-8, 11, 28, 29, 31, 32, 33, 149, 159 | Live pass: only flagged venue returns to review, approved equipment remains approved, prior feedback persists, and round two is approved |
| J3C: Reject unsafe event and release reserved resources | `J3/J3c-safety-rejection/` | SCRUM-257 | SCRUM-151 | SCRUM-8, 11, 28, 29, 31, 32, 33, 34, 149, 159 | Live pass: rejection cancels with history; another event can request the released venue and approve the released equipment stock |
| J4A: Closure affects only an overlapping venue booking | `J4/J4a-closure-impact/` | SCRUM-258 | SCRUM-156, 170, 171, 173, 174 | SCRUM-8, 11, 19, 28, 29, 159 | Live pass: preview identifies one affected request; closure rejects only it, preserves other bookings and parent events, delivers the notification link/reason, and appears in calendar while search excludes the closed interval |
| J4B: Coordinator replaces the closure-rejected booking | `J4/J4b-replacement-booking/` | SCRUM-258 | SCRUM-28, 29, 30, 156, 157 | SCRUM-8, 11, 19, 159, 170, 171 | Live pass: Coordinator submits a separate alternative booking, Venue Staff approve it, and refresh retains the original rejection and unaffected arrangements on the unchanged event |
| J5a Prevent conflicting venue reservations | `J5/J5a-venue-conflict/` | SCRUM-259 | SCRUM-28, 29, 30, 154 | SCRUM-11, 159, 19 | Live pass (buffer conflict, resubmit, both approvals), plus injected queue-failure recovery; SCRUM-155, 145, 146, 147, 156 left to integration tests |
| J5c Prevent booking conflicts with tentative venue holds | `J5/J5c-tentative-venue-hold/` | SCRUM-259 | SCRUM-145, 146, 147, 28, 29, 30 | SCRUM-11, 159, 19 | Drafted, not yet run live; waits ~8 min for a real hold to expire |
| J5b Prevent equipment over-allocation | `J5/J5b-equipment-over-allocation/` | SCRUM-259 | SCRUM-32, 33, 34, 35 | SCRUM-31, 11, 159, 19 | Implemented |
| J6a Organiser requests a change | `J6/J6a-organiser-change-request/` | SCRUM-260 | SCRUM-42, 43, 49 | SCRUM-11, 159, 19 | Implemented (pending immutability, comparison, approval/rejection notifications, rejection reason) |
| J6b Coordinator edits a Confirmed event | `J6/J6b-confirmed-event-safety/` | SCRUM-260 | SCRUM-20, 153 | SCRUM-11, 159, 19, 28, 29, 149, 150 | Implemented (low-impact edit, arrangement conflict, safety withdrawal/history/queue); safety reapproval itself is covered by J1 |
| J7 Register, reject invalid repeat registration, and withdraw | `J7/` | SCRUM-261 | SCRUM-44–48, including SCRUM-46 | SCRUM-8, 11, 19, 28, 29, 149, 150 | Live pass: registration, duplicate/full/closed/non-Confirmed refusal, withdrawal deadline, notification, staff visibility and place reuse |
| J8 Save a draft and resolve clarification and amendment requests | `J8/J8-save-draft-and-resolve-requests/` | SCRUM-262 | SCRUM-11, 12, 15, 16, 44, 158, 159 | SCRUM-8 | Live pass: draft privacy/reopen, one unassigned queue row, Lead submission notification opened from bell, clarification/amendment locks, same Coordinator and retained history; clarification/amendment actions themselves do not currently emit notifications |

Other journeys (J8; SCRUM-262) get a row here when their spec is added.

## Adding a journey

1. Create one `J<n>/` folder for the Jira journey. Keep its main spec and alternate paths in that folder; put distinct paths in child folders or files, such as `J5/J5a-venue-conflict/` and `J5/J5b-equipment-over-allocation/`.
2. Put reusable helpers for all E2E suites in `e2e/helpers/`. Put helpers and fixture scripts used only by one journey/path alongside it under `J<n>/`; never add journey-specific setup to the global helper folder.
3. Set up data through service APIs (not UI clicks) and make fixture event names follow `J<n>[a|b|c] Event ...` (the pattern in `e2e/helpers/cleanup.ts`) so they are removed after the run.
4. Use `test.step` for each stage of the journey.
5. Add the row above.
