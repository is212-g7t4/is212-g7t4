# SCRUM-45 ticket 04 — reassignment verification

Executed locally on October 21, 2026, branch
`SCRUM-45-reassignment-notifications`, worktree `codes/scrum-45-ticket-04`.
**Final independent review is pending and parent-owned. Ticket remains open.**
No push, reset, remote database access or dependency remediation.

## Scope and implementation

Read AGENTS.md, glossary, implementation specification, delivery-ownership ADR
and ticket 04. Reused their approved mutation/outbox, worker/consumer and real
backend seams. Before implementation, merged integration branch
`SCRUM-45-event-organiser-status-and-update-notifications`: fast-forward
`94078fe` → `91042ef`. Repeated integration merge after the implementation
commit returned **Already up to date** at integration tip
`91042ef080b29a7635c4def62a36bf0a5495a89c`; ancestor check passed and the
working tree was clean. This evidence-only amendment does not alter tested code.

The existing successful coordinator-change transaction now records assignment
intent for **reassignment as well as initial assignment**. Existing closed-event
and unchanged-coordinator guards still reject before mutation. Missing organiser
still produces a diagnostic, never a guessed recipient. Reuses
`event.coordinator-assignment`, per-change UUIDs, immutable source facts,
User `username` lookup, freeze/retry, broker delivery and consumer deduplication;
no new type, migration, worker or frontend production logic was necessary.

## Actual RED → GREEN → REFACTOR

All full logs are **outside the repository**:
`/Users/daphnetok/.hermes/artifacts/scrum45-ticket04/`.
Temporary integration subprocess logs are in the scratch basetemps below.
Only this concise evidence file is added to repository documentation.

1. **RED**, before production edits, from `services/event-service`:
   `uv run pytest tests/unit/test_reassignment_notifications.py --no-cov`.
   Actual exit **1**, **1 failed**. HTTP reassignment Alice → Bob returned 200,
   but the assertion expecting one saved notification intent observed **0**.
   Failure was missing behaviour, not import/infrastructure/coverage failure.
   Raw: `01-red-unit.log`.
2. **Minimal GREEN**: remove initial-assignment-only restrictions from the
   existing transactional intent branch. Same focused command: exit **0**,
   **1 passed** (`02-green-focused.log`). The initial complete Event run had
   **525 passed**, but emitted a coverage-floor failure despite process exit 0:
   displayed 98.85% rounded below its exact 98.85 threshold
   (`03-green-event-suite.log`). This is **not** claimed as clean full-suite GREEN.
3. Added already-supported regression cases, not manufactured RED cycles:
   unchanged/closed assignment, invalid coordinator, unconfigured database and
   legacy ownerless reassignment. Their observable outcomes are rejection with
   no work, or successful legacy mutation with diagnosis and no guessed delivery.
   Complete Event suite became **532 passed**, **99.12%**, all gates reached
   (`05-green-regressions.log`).
4. **REFACTOR after GREEN**: name the frozen input `assignment_source`, format
   its construction, document the shared initial/reassignment contract and type
   the test fixture's heterogeneous row. No new abstraction/behaviour. Complete
   Event suite stayed **532 passed / 99.12%** (`06-refactor-green-event.log`).
   Exact measured coverage **99.11924119241192%**; ratcheted floor **98.85 → 99.11**
   without rounding the threshold above the measured value. Seven inherited
   lines/six branches remain uncovered; see external `event-coverage.json`.

## AC4 and agreed-rule evidence

- **AC4**: new mutation tracer verifies replacement ID, event name and submitting
  organiser; real delivery verifies Alice Tan then Bob Lim and event-details link.
- **DR2**: unchanged coordinator returns 409 and yields no extra work/message;
  terminal/no-op/invalid/unconfigured actions have no intent. Real PostgreSQL
  trigger failure on reassignment intent insertion returns 503 and rolls back
  coordinator/status; owning read/claim/inbox APIs show original state/no work.
- **DR3/DR4**: same-event ACTOR → Alice → Bob changes occur before processing.
  Two real worker attempts during a stopped RabbitMQ broker resolve saved IDs
  through the actual User Service and freeze both envelopes. Owning claim APIs
  expose two distinct IDs with Alice/Bob respectively. After renaming both users
  and the event, recovery delivers unchanged JSON envelope content to the
  organiser inbox. Replays plus a FIFO sentinel prove one entry per original ID.
  Original coordinator cannot retrieve these messages. Uses condition waits,
  not fixed sleeps or direct private-outbox-row assertions.
- **DR5**: ownerless reassignment regression diagnoses missing organiser and
  does not guess a recipient.

All new feature Python files start with the story and AC/DR mapping; every test
has an AC/DR and method docstring. Integration imports the existing non-test
`tests/integration/system.py`, never another test module. Reuse/regression tests
that were initially GREEN are not attributed independent RED evidence.

## Final executed verification

| Scope / command | Actual result | External raw log |
| --- | --- | --- |
| Root `npm run test:backend` | Exit 0; **17 suites / 2,562 passed**; all coverage gates reached | `07-backend-all.log` |
| Included Event `uv run pytest` | **532 passed**, **99.12%**, floor **99.11** | same |
| Included Event Workflow `uv run pytest` | **87 passed / 20 integration deselected**, **100%** | same |
| Included Notification `uv run pytest` | **97 passed**, **100%** | same |
| Included Coordinator Assignment / User | **37 / 8 passed**, unchanged floors | same |
| Focused new real reassignment integration | **2 passed**, exit 0, 22.05s | `04-integration-focused.log` |
| All real SCRUM-45 integration | **20 passed / 87 unit deselected**, exit 0, 210.22s; no skips | `08-integration-all.log` |
| Frontend `npm run build && npm run lint && npm test` | Exit 0; build succeeds; lint 0 errors/3 inherited warnings; **59 files / 720 tests passed** | `09-frontend.log` |
| Relevant mocked browser journeys | Exit 0; **8 passed**, including new reassignment history/content/navigation and existing assignment/approval/rejection/venue links | same |

Real integration command from `services/event-workflow-service`:

```sh
uv run --with psycopg2-binary python -m pytest -m integration --no-cov --tb=short --basetemp=/Users/daphnetok/.hermes/cache/scratch/scrum45-ticket04-final
```

Focused real integration uses the same command with
`tests/integration/test_reassignment_delivery.py` and basetemp
`/Users/daphnetok/.hermes/cache/scratch/scrum45-ticket04-focused`.
All twenty cases use UUID-owned local PostgreSQL 17 and RabbitMQ 4 containers,
loopback-only random ports, independent Event/Notification/User databases and
actual service processes. Subprocess environments are allowlisted with dotenv
disabled. No remote DB or production identities. All containers cleaned up:
`docker ps -a --filter name=scrum45- --format '{{.Names}}'` returned no rows.
Two unrelated Venue Availability/Venue Booking integration cases remain opt-in/deselected by the
root backend command; not claimed executed here.

Browser command from `frontend/event-management-ui`:

```sh
npm run test:e2e -- e2e/event-reassignment-notifications.spec.ts e2e/event-assignment-notifications.spec.ts e2e/event-approval-notifications.spec.ts e2e/event-rejection-notifications.spec.ts e2e/notifications.spec.ts
```

Browser APIs are mocked: they establish bell/inbox display of both historical
names, replacement link to the correct event, and read/unread behaviour, **not**
actual delivery. Real pytest integration establishes backend delivery, **not**
browser rendering. These forms of evidence are separate.

## Remaining limitations

No execution blocker remains. Final review/ticket closure belong to the parent.
The pre-existing high npm vulnerability and three Calendar Fast Refresh warnings
remain outside scope. Demo identity isolation is not production authentication.
