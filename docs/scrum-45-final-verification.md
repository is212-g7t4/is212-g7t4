# SCRUM-45 final combined verification — ticket 05

Executed October 21, 2026 on `SCRUM-45-event-organiser-status-and-update-notifications`.
**Independent standards/specification review is pending; no ticket closure is claimed.**
Local commits only; no push, production database access or worktree cleanup.

## Merge and scope

- Ticket 04 input: `9c8bc0d6103bd2b62f10dd9e975e34c3d09ca6bf`
  (`SCRUM-45-reassignment-notifications`).
- Non-fast-forward integration merge: `dbb434facd0802334c5212313cd2f809efce882e`,
  message `SCRUM-45: merge coordinator reassignment notification ticket 04`.
- Tickets 01–04 already implement and meaningfully test ticket 05's combined
  delivery/recovery requirements. Reused those tests rather than adding duplicate
  assertions or manufacturing RED for working behaviour. No production or test
  code changed in ticket 05. Documentation now distinguishes current implementation
  from original interview/first-RED chronology; the original first-RED observations
  and earlier ticket results are retained as historical evidence.
- After this evidence commit, ticket 04 is fast-forwarded to the integration tip;
  exact final SHA is reported by the merger. Original worktrees remain present.

## Commands and actual results

Raw logs are outside the repository at
`/Users/daphnetok/.hermes/artifacts/scrum45-final/`.
All commands below exited **0**, except the unconfigured-checkout Compose check
explicitly called out under startup. No test failures or infrastructure skips.

| Working directory / command | Actual result | Raw log |
| --- | --- | --- |
| Repository root: `npm run test:backend` | **17 service suites; 2,562 passed, 22 integration deselected**; every configured coverage gate reached | `backend.log` |
| Included Event Service | **532 passed**, **99.12%**, floor **99.11** | same |
| Included Event Workflow | **87 passed, 20 integration deselected**, **100%** | same |
| Included Notification | **97 passed**, **100%** | same |
| UI: `npm run build` | TypeScript + Vite build succeeds, 100 modules transformed | `build.log` |
| UI: `npm run lint` | **0 errors, 3 inherited warnings** in `ClosureDetails.tsx` | `lint.log` |
| UI: `npm run test:coverage` | Full Vitest: **59 files / 720 passed** | `vitest.log` |
| UI: `npm run test:e2e` | Full mocked Chromium suite: **73 passed**, 16.9s | `playwright.log` |
| Event Workflow: real integration command below | **20 passed, 87 unit deselected**, 253.75s | `integration.log` |
| Root: `git diff --check` | No whitespace errors | terminal output |

UI means `frontend/event-management-ui`. Real integration command, from
`services/event-workflow-service`:

```sh
uv run --with psycopg2-binary python -m pytest -m integration --no-cov --tb=short --basetemp=/Users/daphnetok/.hermes/cache/scratch/scrum45-final-integration
```

This runs the **entire isolated SCRUM-45 integration suite**, not just selected
files: approval **4**, combined delivery/migrations **5**, initial assignment **5**,
reassignment **2**, rejection **4**. Real Event/User/Notification HTTP services,
worker and consumer use owned UUID-named PostgreSQL 17 and RabbitMQ 4 containers,
loopback-only random ports and separate owner databases. Subprocess environments
are allowlisted, with dotenv disabled. Synthetic test identities/credentials only.
All owned containers were removed: after completion,
`docker ps -a --filter name=scrum45- --format '{{.Names}}'` returned no rows.
Subprocess logs remain under the explicit scratch basetemp, not in Git.

## AC and agreed-rule mappings

Paths below are within Event Workflow's `tests/integration/` unless qualified.
These are executed coverage mappings, not merely planned test names.

| Requirement | Meaningful existing verification |
| --- | --- |
| **AC1 approval** | `test_approval_delivery.py::test_real_approval_is_retrievable_after_broker_outage_with_saved_facts`, parameterized `approve` / `progress`: saved decision, original submitting recipient, event name, approval content, event-details destination and real inbox persistence. Event unit `test_approval_notifications.py` covers trigger, validation, repeated action and freeze contract. |
| **AC2 rejection/reason** | `test_rejection_delivery.py::test_real_rejection_outage_recovery_deduplication_and_recipient_isolation`, both supported routes: stored reason including newline, saved decision/recipient and inbox payload. Event unit `test_rejection_notifications.py` covers recorded reason and intent transaction. |
| **AC3 name/decision/link/details** | Both decision integration modules assert event name, decision and event-details destination; owning details API exposes decision/reason. Mocked `event-approval-notifications.spec.ts` / `event-rejection-notifications.spec.ts` separately verify bell/inbox rendering, click destination and rejection reason on the organiser screen. |
| **AC4 initial assignment** | `test_initial_assignment_delivery.py::test_real_initial_assignment_delivers_username_event_link_and_deduplicates`: real User `username`, event name, original organiser, details destination, actual stored notification. Event unit `test_initial_assignment_notifications.py` covers transactional historical source and freeze validation. |
| **AC4 reassignment/history** | `test_reassignment_delivery.py::test_rapid_reassignments_keep_saved_identity_and_frozen_name_across_retry`: Alice then Bob recorded before processing; distinct saved IDs/names/envelopes survive broker outage and subsequent user/event renaming; correct event link. Event unit `test_reassignment_notifications.py` covers replacement identity and no-op/closed/invalid/ownerless cases. Mocked reassignment browser journey renders both historical names and navigates correctly. |
| **DR1 distinct approval/assignment** | `test_combined_delivery.py::test_initial_assignment_and_approval_deliver_distinct_updates`: both recorded before processing yield exactly two persisted messages with separate source IDs/types, named coordinator, approval decision and correct organiser. |
| **DR2 transactional/no-op** | `test_failed_approval_rolls_back_event_and_pending_work` / `test_failed_rejection_rolls_back_event_and_pending_work`, both routes; real failed initial assignment/reassignment tests: PostgreSQL intent failure rolls back owner state and leaves no work/message. Unchanged Bob assignment returns 409 and adds no work. |
| **DR3 outage/recovery/redelivery** | Both decision delivery tests, initial-assignment broker/name-retry test and rapid reassignment test stop/restart the real broker and recover persisted work. Replay checks prevent duplicate inbox entries; decisions retain read state. Reassignment uses a later FIFO sentinel to establish consumption of earlier duplicates. |
| **DR4 frozen history** | Saved recipient/event facts in decision tests; initial-assignment retry/name-change test; rapid Alice/Bob reassignment test verifies entire frozen envelope after recovery. |
| **DR5 legacy missing recipient** | Event unit `test_rejection_notifications.py`, `test_approval_notifications.py`, `test_initial_assignment_notifications.py`, `test_reassignment_notifications.py`: legacy actions remain possible with diagnostics, never guessed/broadcast recipients. |
| **DR6 lookup retry/hold/repair** | `test_real_name_hold_does_not_block_rejection_and_can_be_repaired` (missing and blank username), `test_real_user_outage_retries_and_broker_retry_preserves_first_prepared_name`: real User lookup, held item repair/release, unrelated rejection delivery and retry. |
| **DR7 future changes only** | New mutation-triggered intent only; no backfill implementation exists or is claimed. No contrived backfill test added. |
| **DR8 recipient isolation** | Real decision/assignment/reassignment inbox queries under another synthetic identity cannot retrieve the submitting organiser's messages; existing Notification scoping tests remain green. Demo identity only, not production authentication. |
| **DR9 inbox regression** | Notification unit suite plus full mocked Playwright suite, including `notifications.spec.ts`: read/unread and existing venue destinations retained. |

Backend integration proves persistence/delivery, **not browser rendering**.
Playwright routes mock backend APIs: it proves rendering/navigation, **not actual
backend delivery**. No unmocked full-stack browser journey is claimed.

## Existing TDD evidence (chronology preserved)

- `scrum-45-tdd-evidence.md`: original consumer contract assertion RED, including
  the full-service run distinguishing behaviour failure from focused coverage noise.
- `scrum-45-ticket-01-evidence.md`, `scrum-45-ticket-02-evidence.md`,
  `scrum-45-ticket-03-evidence.md`: respective rejection/approval/initial-assignment
  RED → minimal GREEN → REFACTOR and boundary/real-delivery evidence.
- `scrum-45-combined-02-03-evidence.md`: actual PostgreSQL migration RED when
  approval replaced assignment's type constraint; minimal additive fix and GREEN
  for both migration orders. Combined delivery regression was already GREEN.
- `scrum-45-ticket-04-evidence.md`: reassignment request succeeded but saved **0**
  intents at RED; minimal general fix, focused GREEN, regression/refactor GREEN.
  Also transparently records the intermediate exact coverage-floor failure.
- Ticket 05 introduces no new behaviour requiring implementation; these reruns
  are regression/final verification, **not a new RED cycle**. No original failure
  was re-created by deliberately breaking working production code.

## Compose, migrations and manual local startup

Checked Compose service wiring: Event owns intent; Event Workflow dispatcher
uses Event/User HTTP and the shared internal token; RabbitMQ/Notification consumer
are separate processes; atomics do not publish. Reassignment uses the existing
assignment type and requires no new migration.

Real migration cases in `test_forward_migrations_preserve_all_notification_types`
passed **all four** clean/existing-rejection × chronological/independent-order
combinations, preserving old work and allowing rejection, approval and assignment.
This validates the service-specific baseline and SCRUM-45 forwards together,
**not every unrelated monorepo migration**.

Direct root `docker compose config --quiet` exited **1**: this worktree has no
root/service `.env` configuration and the root internal token is unset. No real
credentials were copied in. A scratch-only copy of the same Compose model,
changing only build paths to absolute paths and env-file inputs to committed
`.env.example` files, passed config validation (**exit 0**) with a synthetic
internal token. Reproducible helper/output: external `check_compose.py` and
`compose.log`. This is syntax/config validation, **not a successful Compose boot**.

Manual startup prerequisites (do not point any URL at production):

1. Start Docker Desktop. Provision disposable/local owner databases with the
   repository's required baseline schema. Configure service-specific local URLs;
   containers must use Docker-reachable hosts (for example `host.docker.internal`
   for a host database), not their own `localhost`. The isolated suite above is
   the already-verified safe startup path for acceptance testing.
2. Create ignored `.env` files from the committed `.env.example` templates for
   every `env_file` listed in `docker-compose.yml`, including the root file.
   Set each owning service's **local** database URL independently; do not copy a
   production/root database URL indiscriminately into all services.
3. On the **Event-owned local database**, apply in order:
   `database/supabase/migrations/20261021000000_event_notification_outbox.sql`,
   `20261021000100_event_approval_notifications.sql`,
   `20261021020000_event_notification_assignments.sql`.
   On the **Notification-owned local database**, apply
   `20261017000000_notification_inbox.sql` after its baseline. Apply migrations
   with `psql "$EVENT_LOCAL_DATABASE_URL" -v ON_ERROR_STOP=1 -f <event-file>`
   and the corresponding Notification-local URL for its file; first verify those
   URLs target the intended disposable/local databases. Do not run this against
   production or share an owner's data store with another service.
4. Set a nonempty matching `INTERNAL_SERVICE_TOKEN` in root and Event configuration.
   Configure root broker credentials consistently; Compose supplies broker URL
   and Event/User URLs to `event-notification-dispatcher`, broker URL to
   `notification-consumer`. Set `NOTIFICATION_DEV_MODE=true` only for the local
   demo and use the existing demo identity headers. `FRONTEND_ORIGIN` must match
   Vite's pinned `http://localhost:5174` (and Compose override if changed).
5. From root run `docker compose config --quiet`, then
   `docker compose up --build -d`. Check `docker compose ps`, Event `:5003`, User
   `:5001` and Notification `:5015` health endpoints plus
   `docker compose logs event-notification-dispatcher notification-consumer`.
   RabbitMQ readiness may lag container startup; workers restart/retry.
   Run `npm ci` in the UI if needed, then root `npm run dev:frontend`.
   Stop the manually started stack with `docker compose down`; preserve broker
   volume unless deliberately resetting disposable demo data.
6. Named-coordinator delivery requires a real User `username`. Missing/blank
   names hold the item without blocking others. Inspect authenticated
   `GET /internal/notification-outbox/held`, repair the saved user's data, then
   `POST /internal/notification-outbox/<source-id>/release` with `{}` and the
   matching `X-Internal-Token`. See Event Workflow README for lease/retry details.

## Limits and pending work

- No execution blocker for the isolated acceptance/regression suites. Manual
  Compose startup remains unexecuted until local env/database configuration exists.
- Root unit run deliberately deselects 22 integrations: the 20 SCRUM-45 cases ran
  separately; unrelated Venue Availability and Venue Booking integrations (one
  each) were not executed and are not claimed green.
- Frontend coverage report is scoped by existing `vitest.config.ts` include rules,
  not whole-application coverage: **98.1% statements, 92.4% branches, 96.6%
  functions, 98.76% lines**. Backend inherited service coverage below 100 remains;
  no floor was lowered and no new coverage padding was added.
- Three inherited Fast Refresh lint warnings remain. Earlier ticket evidence
  reports one high npm vulnerability; dependency remediation/audit is not part of
  this verification and no fresh audit result is claimed.
- Demo recipient headers are not production authentication. Missing-organiser
  legacy data cannot receive these notifications until ownership is repaired.
- Standards/specification review and ticket closure remain explicitly pending
  and parent-owned. No tracker state was changed by this task.
