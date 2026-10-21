# SCRUM-45 tickets 02 + 03 — combined integration evidence

Date: October 21, 2026. Local-only integration on
`SCRUM-45-event-organiser-status-and-update-notifications`, exclusively in
`codes/scrum-45-integration`. No push, ticket closure, reassignment implementation,
remote database access or original-ticket worktree modification.

## Merge inputs and resolutions

- Approval input: `4f40e1364a54e9e6ffc9aea23f2a8680bf9ec313`.
- Approval merge: `ba3c03a657dc5c3a58005712f25d2fea48d01cf0`.
- Initial assignment input: `e0e355746566b095ada8fbd2c46c19e7dce550dc`.
- This document is included in the second, non-fast-forward merge; its exact
  commit is discoverable through `git log --merges` and the final task report.
- Resolved shared outbox validation and worker preparation preserving
  `event.rejection`, `event.approval`, and `event.coordinator-assignment`.
  Consumer/model additions merged without manual conflicts.
- Retained one shared **non-test** integration helper, `tests/integration/system.py`,
  registered through `conftest.py`. Incorporated ticket 03's real User Service
  and third independent local database, and explicitly includes both forward
  migration filenames. No test-module imports from another test module.
- Combined measured Event coverage is **98.85057471264368%**; raised the floor
  from the higher input floor **98.83** to **98.85**. Event Workflow and
  Notification remain **100%**. No coverage gate was lowered or disabled for
  any full unit suite. Ten inherited Event lines and seven branches remain
  uncovered; see the captured coverage report, not a claim of 100%.
- Updated worker rollout instructions to require the approval and assignment
  migrations together. Original rejection-only migration remains unchanged.

## New failing migration test, then minimal fix

Added `tests/integration/test_combined_delivery.py` before changing the approval
migration. The new PostgreSQL test applies the two independently delivered
forward migrations in either order, against a clean outbox or one containing
existing rejection work, then inserts all three types and checks the old row.

RED command, from `services/event-workflow-service`:

```sh
uv run --with psycopg2-binary python -m pytest tests/integration/test_combined_delivery.py -k "forward and independent-order and clean" -m integration --no-cov --tb=short --basetemp=/Users/daphnetok/.hermes/cache/scratch/scrum45-combined-red
```

Actual exit **1**, **1 failed / 4 deselected**, 9.52s. Real PostgreSQL rejected
`event.coordinator-assignment` with `CheckViolation` after the approval migration
replaced the installed type expression. This was an actual constraint failure,
not a dependency/import/infrastructure RED. Full raw output:
`verification/scrum45-combined/migration-red.log`.

Minimal fix: approval migration now extends `pg_get_expr` from the installed
constraint using `OR type = 'event.approval'`, matching the assignment migration's
additive convention. Does not alter the rejection-only base migration or add
reassignment behavior. All four clean/existing and chronological/independent-order
migration cases passed in the full integration run below. Clean here means the
owning service's baseline tables plus a freshly installed rejection-only outbox;
this is not a claim to have applied every unrelated monorepo schema migration.

Added a combined delivery regression: initial assignment and approval recorded
before any worker processing produce two separate persisted inbox messages with
distinct source IDs, the correct submitting recipient, approval decision, saved
coordinator's real User `username`, event name and details destination. Already
GREEN on the merged implementation; not claimed as a new RED cycle.

## Actual final verification

Raw command output is committed under `docs/verification/scrum45-combined/`.

| Command / scope | Actual result | Raw log |
| --- | --- | --- |
| Root `npm run test:backend`, final run after raising the floor | Exit 0; **17 suites, 2,554 passed** | `all-backend-final.log` |
| Included Event full suite, `uv run pytest` | **524 passed**, **98.85%**, floor **98.85** | same log; `event-coverage.json` contains exact metrics |
| Included Event Workflow full suite, `uv run pytest` | **87 passed**, **18 integration deselected**, **100%** | same log |
| Included Notification full suite, `uv run pytest` | **97 passed**, **100%** | same log |
| Included Coordinator Assignment full suite | **37 passed**, **87.85%**, unchanged floor | same log |
| Included User full suite | **8 passed**, **97.87%**, unchanged floor | same log |
| Real integration command below | Exit 0; **18 passed / 87 unit deselected**, 193.81s | `integration-green.log` |
| Frontend `npm run build && npm run lint && npm test` | Exit 0; build succeeds, lint 0 errors / 3 warnings, **59 files / 720 tests passed** | `frontend.log` |
| Relevant mocked Playwright journeys, command below | Exit 0; **7 passed** | `frontend.log` |

The root backend command deliberately excludes opt-in integration tests: Event
Workflow's 18 were executed separately, while two unrelated service integration
tests (Venue Availability and Venue Booking, one each) remain deselected. No
infrastructure skips occurred in the 18-test SCRUM-45 integration run.

Real integration command from `services/event-workflow-service`:

```sh
uv run --with psycopg2-binary python -m pytest -m integration --no-cov --tb=short --basetemp=/Users/daphnetok/.hermes/cache/scratch/scrum45-combined-green
```

- Approval **4**, rejection **4**, initial assignment **5**, combined/migrations
  **5** passed. Covers actual delivery, rollback, both decision mutation routes,
  outage recovery, frozen name/content across retry, missing/blank name
  hold/repair, unrelated delivery, replay deduplication and recipient isolation.
- Every test owns UUID-named PostgreSQL 17 and RabbitMQ 4 containers with
  loopback-only random host ports. Three separate databases belong to Event,
  Notification and User. Event/Notification/User HTTP services, worker and
  consumer are real local processes. User is not a mock HTTP server.
- Subprocess environments are allowlisted; `PYTHON_DOTENV_DISABLED=1` and
  `FLASK_SKIP_DOTENV=1`. Local synthetic identities and credentials only.
- Integration subprocess logs remain under the explicit scratch basetemp above.
  Cleanup verified: `docker ps -a --filter name=scrum45- --format '{{.Names}}'`
  produced no rows after the run.

Browser command from `frontend/event-management-ui`:

```sh
npm run test:e2e -- e2e/event-approval-notifications.spec.ts e2e/event-assignment-notifications.spec.ts e2e/event-rejection-notifications.spec.ts e2e/notifications.spec.ts
```

Browser tests mock the backend and separately establish rendering/navigation,
not real persistence. Real pytest integration establishes backend persistence,
not browser rendering. These two forms of evidence are not conflated.

## Remaining limitations / pending review

- Independent combined-code review is **pending** (Codex unavailable per task
  context); these test results do not substitute for that review. Do not close
  tickets based on this merge alone.
- `npm ci --ignore-scripts` reported one high-severity dependency vulnerability;
  no dependency changes were made. Lint's three inherited Fast Refresh warnings
  remain in `src/features/calendar/ClosureDetails.tsx`.
- Demo identity isolation remains demo-only, not production authentication.
- Reassignment is intentionally deferred; no reassignment changes or claims.
- No execution blocker remained for the requested local verification.
