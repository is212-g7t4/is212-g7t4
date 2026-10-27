# SCRUM-166 — Receive assignment notifications

Status: review fixes implemented and verified in the original checkout. All affected default coverage gates, complete service integration tiers, migration rehearsals and normal frontend test/coverage/build/lint commands pass. Work remains uncommitted; no shared migration or deployment was performed.
Baseline: origin/main `f0cd2c16ef56b5a4e15bc7d774d1b3ddb6b65f9e`.
Local branch: `scrum-166-receive-assignment-notifications` in the original checkout.

## Story and acceptance criteria

As an Event Coordinator, I want to receive in-app notifications when I am assigned to or removed from an event, so that I know which events I am responsible for.

The supplied criteria are numbered below for traceability; reassignment's two recipient requirements remain one AC.

- **AC1:** Given the Lead Coordinator successfully assigns an Event Coordinator to an event that previously had no assigned coordinator, the assigned coordinator receives an in-app assignment notification.
- **AC2:** Given the Lead Coordinator successfully reassigns an event from one coordinator to a different coordinator:
  - The new coordinator receives an in-app notification that they have been assigned.
  - The previous coordinator receives an in-app notification that they have been removed.
- **AC3:** Assignment notifications include the event name, Event Organiser name, proposed event date/time, and a link to view the newly assigned event.
- **AC4:** Removal notifications include the event name, Event Organiser name, proposed event date/time, and a clear statement that the recipient is no longer assigned to the event.
- **AC5:** Saving an assignment without changing the assigned coordinator does not create new assignment or removal notifications.

## Confirmed scope

- Add coordinator notifications; preserve SCRUM-44 submission, SCRUM-45 organiser, and SCRUM-173 venue-impact notifications, including their recipients, payloads, links and delivery rules.
- Reassignment A → B produces removal for A and assignment for B. Do not add a standalone unassign operation.
- Reuse existing inbox refresh/polling. No email, push, new realtime transport or E2E suite.
- Show full proposed start/end in Singapore time, labelled Proposed; absent schedule displays Not provided.
- Assignment has a structured event-details link. Removal has no event link. Preserve current permissions and existing unchanged-save rejection behavior.
- Historical event facts are retained. Failed assignment transactions create no notification work. Successful assignment is not rolled back merely because asynchronous delivery is delayed.
- Distinct stable delivery IDs per recipient; retries cannot duplicate inbox entries or overwrite read state.
- Self-assignment notifies the actor if existing assignment eligibility allows it; do not change eligibility.
- Rapid A → B → C changes retain each historical notification. Temporarily unavailable organiser name delays preparation; genuinely missing names remain an explicit held delivery problem rather than invented data.
- No dedicated rapid-reassignment test or extra unchanged-save response case. During approved coverage restoration, organiser repair-hold/transient-error cases were unavoidable for Workflow’s existing 100% branch floor; their limited addition is recorded below. AC5 suppression retains its original acceptance tests.

## Important discovery: historical organiser name

Event Service can snapshot event name, organiser ID and preferred start/end inside the assignment transaction. The organiser display name belongs to User Service and is currently obtainable only at dispatcher preparation time. Freezing that lookup across retries does NOT prove the name as of assignment time.

**Confirmed by the user:** capture organiser name on first successful notification preparation and freeze it across retries. Event-owned facts remain assignment-time snapshots. This explicitly permits worker-time organiser-name enrichment rather than claiming an exact assignment-time name. No venue/contact fields are required by this story and none should be added.

## Implementation design

Reuse Event's transactional outbox → Event Workflow → RabbitMQ → Notification inbox. Do not introduce new tables, shared libraries, synchronous delivery, or cross-owner SQL.

### 1. Event Service: transaction and source facts

Files: `services/event-service/app/models.py`, `app/outbox.py`; assignment route in `app/__init__.py` should retain its existing contract unless implementation establishes a necessary change.

- Extend `update_event_coordinator()` within its existing locked transaction. Capture previous coordinator before updating.
- Leave existing organiser-facing `_record_notification()` behavior intact. Add a narrowly scoped helper taking an explicit coordinator recipient rather than changing the organiser helper's meaning.
- Initial assignment adds a coordinator assignment intent. Reassignment adds assignment to B and removal to A. Existing organiser intent remains additional and unchanged.
- Capture event ID/name, organiser ID, proposed start/end and exact recipient in each source record. Never derive old recipients from mutable current assignment during dispatch.
- Use distinct IDs for independent deliveries. Atomic insertion failure must roll back assignment and every new intent.
- Proposed internal types: `event.coordinator-assigned` and `event.coordinator-removed`; retain `event.coordinator-assignment` exclusively for SCRUM-45.
- Extend frozen-envelope validation explicitly for both types, including destination policy. New types must not fall through rejection handling.

### 2. Additive migration

Directory: `database/supabase/migrations/`.

Extend `EventNotificationOutbox_type_check` to allow both new types while preserving every currently accepted type. Use a new migration ordered after the fetched baseline's migration inventory; do not edit applied migrations. JSONB source/envelope storage suffices; no new table or inbox column is planned.

Before any separately authorised deployment, verify clean installation and upgrade with existing synthetic records on disposable PostgreSQL. Check constraint behavior, preservation of unrelated rows and migration history, not textual SQL/cast formatting. Apply schema support before enabling new writers. No shared migration is authorised by this plan.

### 3. Event Workflow: prepare, freeze and publish

File: `services/event-workflow-service/app/dispatcher.py`.

- Add explicit branches for the two coordinator-facing types before existing fallbacks.
- Use captured recipient and event facts. Resolve organiser display name via User Service only, using the confirmed first-successful-preparation name exception above.
- Assignment wording: You have been assigned to {event name}. Removal wording: You are no longer assigned to {event name}.
- Both include Event Organiser and Proposed start/end (SGT); assignment includes event-details destination; removal omits navigation using the existing envelope's supported no-destination representation (verify its exact shape before coding).
- Freeze prepared content through Event's API before publishing; publish the owner-returned frozen envelope. Reuse existing hold/retry/completion logic and stable IDs.
- Do not query another service's database or change submission fanout/SCRUM-45 preparation.

### 4. Notification Service: validate and reuse storage

File: `services/notification-service/app/consumer.py`.

Add explicit type-specific contract validation for required details and assignment/removal destination policy. Retain other validators and quarantine behavior. `app/store.py` already provides generic persistence, source-ID deduplication and recipient-scoped inbox APIs; no storage behavior change is planned.

### 5. Frontend: minimal conditional change

Files: `frontend/event-management-ui/src/features/notifications/notifications.ts` and `NotificationCenter.tsx`.

Confirm existing generic message/date rendering can present the full new payload. Add only organiser-name typing/rendering and Proposed/SGT/no-schedule presentation that is actually missing; no contact or venue additions, new route, permission change, old-link redesign, or polling change. Scope formatting to new types so SCRUM-173 closure periods and existing legacy notifications retain their meaning.

Review approval explicitly includes one frontend removal-rendering regression: suppress a destination warning only for the exact coordinator-removal type with explicit null destination. Missing/invalid removal destinations and legacy content-only records retain warnings; no link or permission behavior changes.

### Unchanged owner

Coordinator Assignment Service continues Lead validation and forwarding. Reuse its existing legitimate-Lead regression coverage; no new story module or production change unless inspection during implementation establishes a concrete need.

## Minimal direct acceptance tests

Initial budget: ten direct cases plus three supporting cases across the feature. Review approval expanded it for meaningful coverage restoration and one removal component regression. The original 13 backend story cases remain; six added unit functions expand to 31 cases (Event 10, Workflow 5, Notification 16). One existing migration parameter rehearses upgrade from the pinned main inventory; it is infrastructure, not another story AC.

| ID | Owner/layer | Scenario and observable expected result |
|---|---|---|
| AC1-I1 | Event integration | Initially unassigned event is assigned through the API. Assignment persists and exactly one coordinator assignment obligation exists for the new coordinator, with no removal. Count SCRUM-45 separately and preserve it. |
| AC1-I2 | Notification integration | Consume an independently constructed assignment envelope. Recipient inbox returns the exact persisted message; another coordinator cannot retrieve it. |
| AC2-I1 | Event integration | Reassign A → B. Saved assignment and two distinct coordinator obligations identify B as assigned and A as removed, with different delivery IDs; organiser work is preserved. |
| AC2-I2 | Notification integration | Consume assignment-to-B and removal-to-A envelopes. Each recipient sees exactly their own notification, not the other's. |
| AC3-U1 | Workflow unit | Captured assignment facts produce exact organiser/event/proposed period and event-details destination for the captured recipient; publication uses the frozen envelope returned by the owner. |
| AC3-I1 | Workflow adapter integration | Exercise actual HTTP client with strict HTTP stubs: exact claim/freeze/complete contract, required assignment content/link and recording publisher payload. This is adapter integration, not live-service delivery or browser navigation. |
| AC4-U1 | Workflow unit | Captured old-recipient facts produce explicit removal wording, required organiser/event/proposed period and no event link. |
| AC4-I1 | Workflow adapter integration | Actual HTTP adapter and strict stubs verify removal freeze/publish contract uses previous recipient and omits navigation. |
| AC5-U1 | Event unit | Unchanged coordinator is rejected/no-op without mutation or notification insertion; mock SQL I/O, not the business decision. |
| AC5-I1 | Event integration | Same-coordinator API request leaves complete event and outbox snapshots unchanged, including organiser work. Exact existing response is preserved, not a separate extra case. |

### Small supporting checks (not new ACs)

- Event integration: force failure on the second SCRUM-166 recipient insertion during reassignment; assert assignment and ALL new intents roll back. Failure only on the first insertion does not establish partial-fanout rollback.
- Workflow adapter integration: simulated publication/completion failure followed by retry retains frozen identity/content and does not prematurely complete. This is not a live broker recovery claim.
- Notification integration: replay a new coordinator source ID after marking read; assert one inbox row and preserved read state. Reuse an existing applicable case if it actually covers the new contract rather than cloning generic recovery coverage.

The original ceiling was explicitly expanded after the coverage-only failures. Added cases validate owner freeze contracts, consumer quarantine/storage contracts and safe hold-versus-retry behavior; no coverage floor was changed, no exclusions added and no production branches removed to satisfy coverage.

## Test file organization and readable documentation

Filename in every required service/layer:
`test_scrum_166_receive_assignment_notifications.py`.

Implemented modules:
- `services/event-service/tests/unit/test_scrum_166_receive_assignment_notifications.py`
- `services/event-service/tests/integration/test_scrum_166_receive_assignment_notifications.py`
- `services/event-workflow-service/tests/unit/test_scrum_166_receive_assignment_notifications.py`
- `services/event-workflow-service/tests/integration/test_scrum_166_receive_assignment_notifications.py`
- `services/notification-service/tests/integration/test_scrum_166_receive_assignment_notifications.py`
- `services/notification-service/tests/unit/test_scrum_166_receive_assignment_notifications.py`

The approved Notification unit module covers both delivery types, valid/absent schedules, malformed display/identity/period/destination contracts, quarantine versus inbox SQL and transaction-exit-before-ACK. PostgreSQL persistence remains the integration tier’s responsibility.

Every module begins with the full story and all five original ACs once, followed by a short explanation of real versus substituted dependencies and limits of its evidence. Group under short AC headings/classes; name cases `test_ac1_...` etc. Supporting checks have a separate Design Rules section, not invented AC numbers. Each test has a two/three-line plain-English scenario/result docstring; add Arrange/Act/Assert comments where sequences are complex. Avoid repeated AC paragraphs or implementation-detail commentary.

Reuse service-local `tests/integration/conftest.py` and `factories.py`. Adapt organiser-only factories for explicit coordinator identities without breaking existing consumers. Shared helpers belong in factories/fixtures, never imported from another test module. Keep one module per layer per owner; do not merge services to reduce file count.

## Isolation, repeatability and truthful evidence

- Event and Notification integrations use existing disposable PostgreSQL fixtures, synthetic parent/event/user data and full applicable unmodified migrations. Use the fixture-pinned image, currently reported as postgres:17.6, after confirming fixture configuration at implementation time.
- Guard exact fixture-owned connection identity before writes/truncation. Loopback alone is not ownership proof. Never inherit shared Supabase credentials or dotenv settings.
- Reuse established container lifecycle/per-test reset, unique resource names and bounded readiness. Always attempt teardown and record owned-container/volume cleanup failures.
- Workflow integration is strict HTTP adapter integration with substituted endpoints and a recording publisher; it has no owned database and must not be represented as real cross-service delivery.
- Unit tests mock external I/O including psycopg2; socket blocking alone does not stop libpq connections.
- Run services separately with their locked environments; sanitize inherited PYTHONPATH/PYTHONHOME and disable dotenv. Do not install packages globally or invent unsupported socket flags.
- Retain original failure output, final outcomes, source revision/tree identity and exact commands. Keep one current machine-readable evidence index during implementation, with run status initially not-run, per-layer references, cleanup results and superseded runs. Raw logs stay outside the proposed PR.

## Agreed TDD and verification sequence

1. Reconfirm task scope and target changes before implementation; preserve unrelated work. Historical-name timing is confirmed above. Null is explicitly supported for coordinator removal in Event freeze, Notification validation and storage; the review frontend fix makes deliberate content-only removal render without a misleading unavailable-destination warning.
2. Reuse the existing isolated runner/configuration; run an owning-service baseline. Do not build another runner/framework by default.
3. Implement vertical slices: one AC test fails for missing behavior, minimal production change, rerun green, then next case. Do not create all tests first or manufacture RED for already-supported behavior.
4. Start with AC1 Event transaction and additive schema support, then assignment preparation/persistence. Extend through AC2/AC4 removal, AC3 complete presentation, and AC5 suppression. Fit supporting rollback/retry cases at their respective boundaries.
5. Review/refactor only with green affected tests. Run new owner-service tests and existing SCRUM-44/45/173 regressions at their owning layers. Preserve exact existing recipients/content/link semantics, not just counts.
6. Verify the complete affected default suites with existing coverage gates; targeted passes do not establish service coverage. For production changes run broader repository-required checks before eventual publication.
7. Exercise migration clean-install and upgrade behavior on disposable PostgreSQL. Existing suitable migration tests should be extended/reused, not duplicated as user-facing ACs. If missing migration coverage requires extra infrastructure cases, expose that scope before adding it.
8. Record actual results and cleanup, then stop for review. Commit, push, PR, shared migration and deployment each remain separately authorised.

Commands used through the existing locked service environments, with an allowlisted environment, Python path variables removed, dotenv disabled and no shared database variables passed:

```sh
uv sync --locked
uv run --no-env-file --locked pytest
uv run --no-env-file --locked pytest tests/integration/test_scrum_166_receive_assignment_notifications.py -m integration --no-cov -v
```

Configured integration socket markers were used. Docker server availability was verified (29.1.3); fixtures used postgres:17.6. Exact executed commands and exit codes are in the external evidence index below.

## Retrospective application and policy notes

- Reuse existing runner/fixtures and locked dependencies; solve agent environment interference centrally rather than changing product code.
- Disposable migration rehearsal before shared deployment; behavioral postconditions rather than fragile constraint-string matching.
- Original checkout only; service unit/integration ownership, teammate-owned journeys untouched.
- Review persisted obligation, recipient, required content, invalid-action suppression and retry boundary, not coverage percentages alone.
- One current evidence index, concise per-test documentation, tiered verification. Documentation-only changes do not justify infrastructure reruns.
- Existing automatic CI primarily covers units; this plan does not claim disposable integrations run automatically. SCRUM-173's manual cross-service workflow is not equivalent to an owner-service CI path. Record the gap; no new workflow is authorised.
- Team integration guide filename advice conflicts with the user's explicit ticket-bearing names. Use the explicitly approved `test_scrum_166_receive_assignment_notifications.py`; leave policy files unchanged.
- Approved lowercase branch name differs from AGENTS.md's uppercase example; retain the exact name explicitly approved by the user.

## Current implementation evidence

Evidence index (local, outside the repository):
`/Users/daphnetok/.hermes/cache/scratch/scrum166-20261026-133542/index.json`.
It records each command, working directory, actual exit code, raw log, sensitivity probe, resource cleanup and source identity. The initial planning document and glossary bytes are preserved there; the glossary was not edited by this implementation worker.

### Implemented behavior

- Event mutation retains the organiser-facing intent and atomically saves assignment to the new coordinator plus removal to the previous coordinator. Event-owned facts and recipients are captured in that transaction.
- `20261026000000_coordinator_received_notifications.sql` additively permits the two new types, retaining the existing constraint expression. Prior migrations are unchanged.
- Workflow enriches the organiser name on successful preparation, freezes through Event before publishing the owner-returned envelope, and reuses existing retry/completion handling. Genuinely unavailable names hold coordinator deliveries for repair; transient HTTP failures retry. Dedicated missing-name tests remain intentionally outside the approved budget.
- The frozen message contains the organiser and full Proposed Singapore period (or Not provided). The frontend review fix suppresses only the deliberate removal/null destination warning. One focused component regression covers removal content/no navigation while preserving malformed/legacy warnings.
- Removal uses `destination: null`. This required a narrow storage change in `notification-service/app/store.py`: retain the event reference from validated removal details rather than dereferencing a destination. Other types retain their existing storage path.
- Existing Event organiser tests were scoped to their original three notification types; original recipient/content assertions remain. Submission tests inspect the Event UPDATE rather than assuming it is the final SQL operation. No tests were removed.

### Verified review results — 26 October 2026

Current evidence index (exact commands, exit codes, logs, cleanup and source SHA-256 manifest):
`/Users/daphnetok/.hermes/cache/scratch/scrum166-review-20261026/index.json`.
The preceding index remains the historical product RED/GREEN and original 13-case sensitivity record; it is not rewritten as if its coverage failures or timed-out final checks passed.

All Python commands below use `uv run --no-env-file --locked`, an allowlisted environment with no inherited PYTHONPATH/PYTHONHOME/shared database credentials, and disabled dotenv. Coverage is configured whole-application line+branch coverage for each listed service.

| Scope | Actual command | Verified result |
|---|---|---|
| Event default | `pytest` | 677 passed, 143 deselected; 99.53%, unchanged floor 99.51%; exit 0 |
| Workflow default | `pytest` | 134 passed, 28 deselected; 100%, unchanged floor 100%; exit 0 |
| Notification default | `pytest` | 113 passed, 20 deselected; 100%, unchanged floor 100%; exit 0 |
| Coordinator Assignment default | `pytest` | 37 passed; 87.85%, unchanged floor 87%; exit 0 |
| Event complete integration tier | `pytest -m integration --no-cov -vs` | 143 passed, including all 10 migration cases; exit 0 |
| Workflow complete adapter tier | `pytest -m integration --no-cov -vs` | 28 passed; final rerun includes full owner/User response shapes; exit 0 |
| Notification complete integration tier | `pytest -m integration --no-cov -vs` | 20 passed; exit 0 |
| Explicit migration rerun | `pytest tests/integration/test_infra_migrations.py -m integration --no-cov -vs` | 10 passed; clean install and existing-row upgrades including pinned f0cd2c16 inventory; exit 0 |
| Frontend normal suite | `npm test` | 839 Vitest cases in 66 files, plus 4 Node lifecycle tests; exit 0 |
| Frontend configured coverage | `npm run test:coverage` | Same 839 + 4 pass; configured allowlist 98.13% statements / 92.42% branches / 96.66% functions / 98.78% lines; exit 0, not full-source coverage |
| Frontend build / lint | `npm run build`; `npm run lint` | Both exit 0; TypeScript/Vite build succeeds; lint reports 5 warnings, 0 errors |
| Whitespace | `git diff --check` | Exit 0 |

### Review corrections and evidence limits

- Removal rendering was regression-first: the focused component test failed on the misleading warning before the narrow UI fix; then all 23 cases in its existing module passed. Normal frontend checks include existing SCRUM-44/45/173 notification components/adapters. No new E2E was written or run.
- Added 31 backend parameter instances across six functions: Event freeze accepts exact captured content/destinations and refuses malformed/changed content; Notification validates required display facts, recipient consistency, ordered timezone-aware intervals and type-specific destinations before inbox storage/ACK; Workflow distinguishes organiser repair holds from transient HTTP retries without unsafe publication. These tested existing implementation behavior, so their initial passing cases are not manufactured product RED.
- Workflow’s 100% floor made the previously excluded missing/unavailable-organiser branches unavoidable: four hold cases (missing ID, 404, invalid-name failure, hold-write failure) and one transient 503 retry case were added under the expanded approval. No dedicated rapid A→B→C test was added.
- Every new backend parameter instance was assertion-sensitivity checked (31 ordinary assertion failures), with external bytecode cache isolation and exact source restoration. All three complete default suites passed after restoration. This is not comprehensive mutation testing. The original 13 story tests retain their prior sensitivity evidence.
- All six Python story modules retain the full story/five ACs and explain ownership, doubles and uncovered boundaries. Workflow HTTP stubs cite Event’s `operate`/`serialize`/`mutate` and User’s `user_details`/`serialize` source contracts. The respx completion count of 2 includes the failed 503 attempt and one successful retry, **not two successful completions**.
- Initial review runs reproduced the three coverage-only failures. A first frontend filter ran before a guarded append succeeded and selected zero tests; the actual recorded RED failed one assertion. New Notification unit expectations initially used incorrect SQL parameter positions; these were corrected against the declared INSERT columns, without changing application behavior. Raw failures are retained. A sensitivity-summary guard initially misread UUID log text as a setup-error summary; the underlying four cases were ordinary assertion failures and source was restored.
- Docker was initially stopped; Docker Desktop was started, its server verified as 29.1.3, then existing fixture-owned postgres:17.6 tests ran. Teardown verifies exact owned containers and anonymous volumes absent. No Compose, environment files, shared credentials or shared data were used.
- Existing SCRUM-44/45/173 service regressions are included in the executed complete owner tiers; this is not a live broker, hosted CI, shared deployment or browser-journey claim. Event’s pre-existing uncovered paths remain (99.53% total); its outbox module is now 100% line+branch covered.

## Previous implementation completion boundary

Review corrections, restored coverage floors and the formerly timed-out verification are complete in this checkout. Changes remain uncommitted on `scrum-166-receive-assignment-notifications` at HEAD `f0cd2c16ef56b5a4e15bc7d774d1b3ddb6b65f9e`; the external index identifies exact dirty source bytes. No commit, push, PR, workflow/shared-library change, shared migration or deployment was performed. Shared rollout must apply the additive migration before enabling new writers; independent parent review remains required.

## Priority 1 test expansion — 27 October 2026 (complete; awaiting read-only review)

Only the approved Priority 1 additions and existing-case strengthening were made.
The six consolidated story filenames and full story/AC headers remain unchanged.
No Priority 2 organiser/date/retry scenarios, waived rapid reassignments, E2E,
CI changes, shared writes, commits, pushes, runtime rebuilds or restarts were added.

### Scope completed

- **Seven new parameter-expanded cases across five functions:** Event unit initial/reassignment
  SQL fanout (2), Event integration captured facts after later public detail edits (1),
  Event integration initial coordinator insert failure after organiser work with atomic
  rollback (1), Event unit missing removal destination (1), Notification integration
  poison assignment/removal quarantine before ACK followed by valid delivery (2).
- Strengthened existing cases without increasing their counts: current coordinator
  linked-detail GET returns 200 and former coordinator gets 403, with no `viewerRole`
  bypass; Workflow assignment/removal publication equals a distinguishable, valid
  owner-returned frozen envelope at unit/HTTP-adapter boundaries; Notification ACK
  independently reads the exact current source and persisted payload, while another
  recipient's mark-read attempt returns 404 without changing state.
- The missing-removal-destination regression first returned 200 instead of 400.
  A one-condition Event outbox validator fix now requires an explicit destination
  key; explicit null remains accepted. This is the only production change in this
  phase. Other additions exercised existing behaviour and initially passed; their
  green results are not presented as manufactured product RED.
- Assertion-sensitivity probes produced ordinary assertion failures for all seven
  added cases and the strengthened boundaries; exact source was restored. These
  checks show assertion execution, not exhaustive implementation mutation coverage.

### Actual isolated verification

All Python commands use `uv run --no-env-file --locked`, disabled dotenv,
an allowlisted environment without inherited Python paths or shared credentials,
and isolated bytecode-cache paths during sensitivity checks. Existing coverage
floors and exclusions are unchanged.

| Owner | Default suite | Whole-app line+branch coverage | Complete integration tier |
|---|---|---|---|
| Event | 680 passed, 145 deselected; exit 0 | 99.53%; floor 99.51% | 145 passed, including 10 migration regressions; exit 0 |
| Workflow | 134 passed, 28 deselected; exit 0 | 100%; floor 100% | 28 passed; exit 0 |
| Notification | 113 passed, 22 deselected; exit 0 | 100%; floor 100% | 22 passed; exit 0 |
| Coordinator Assignment (unchanged regression) | 37 passed; exit 0 | 87.85%; floor 87% | Not rerun: no changes to this service |

Actual story collection is now **51 cases / 24 functions**: Event unit 14 / integration 6,
Workflow unit 7 / adapter integration 3, Notification unit 16 / integration 5.
Event `app/outbox.py`, Workflow `app/dispatcher.py`, Notification `app/consumer.py`
and `app/store.py` have 100% line+branch coverage. Event `app/models.py` remains
99.67% (missing line 1801; branches 1104→1107 and 1800→1801); Event routes
remain 99.25% (missing lines 1067, 1170, 1178, 1188; branches 221→224,
1066→1067 and 1169→1170). These unrelated paths were not expanded just to raise
metrics. The JSON reports retain exact missing-branch destinations and denominators.

PostgreSQL integrations applied the full unmodified checkout migration chain to
fixture-owned postgres:17.6 containers; logs verify exact owned container/volume
cleanup. Workflow uses strict HTTP stubs and a recording publisher, not running
owner services or a broker. Consumer tests call the callback with a recording ACK
channel; no RabbitMQ transport or cross-service/browser delivery is established.
Frontend files were not modified in this phase, so frontend checks were not rerun.
No schema files changed; the complete Event integration tier nevertheless reran
all existing clean-install/upgrade migration cases.

### Evidence and review boundary

External phase index (commands, exit codes, baseline backups, source hashes,
collection IDs, sensitivity logs, coverage JSON and cleanup):
`/Users/daphnetok/.hermes/cache/scratch/scrum166-priority1-20261027/index.json`.
Earlier evidence indexes remain unchanged. Initial historical-edit setup lacked
required complete event fields and returned 400; the fixture was corrected, not
production. Two attempted rollback selections collected zero tests after a guarded
append was refused; both logs remain alongside the actual one-case passing rerun.

Fetched `origin/main` read-only at `bf6652175465778bd696630dc719e60f07a6e12e`;
HEAD remains `f0cd2c16ef56b5a4e15bc7d774d1b3ddb6b65f9e`. The existing dirty feature
was preserved and not merged with that newer target; results describe this checkout,
not a tested combined tree. Changes remain uncommitted for parent read-only review.
The user reported manual acceptance passed for the prior deployed version. This
phase did not redeploy the validator fix or repeat manual acceptance; the running
version must not be assumed to contain this phase's source changes. Coverage and
passing scoped tests are not a universal/exhaustive correctness guarantee.



## Authorised Event rollout and organiser/timezone checks — 27 October 2026

The reboot recovery and approved Event-only rollout are complete. Existing required
project containers were started in place; all non-Event IDs/settings/mounts were
preserved. The intentionally stopped Equipment Reservation service remains stopped.
Only Event was rebuilt/recreated, using the ordinary root Compose configuration.
Effective configuration matched the old container in memory without logging secrets.
The normal build hit an `uv: Exec format error`, including explicit-platform and
no-cache retries. A scratch build-only override reused the exact deployed Event
base/dependencies and copied the current `app` bytes; its dependency specification
and runtime source hashes were verified. No repository Dockerfile/config was changed.

The deployed source includes the previously tested explicit-destination validator.
Event/Notification health and existing-identity scoped GETs return 200 with matching
CORS. Automatic dispatcher claims return 200 and the consumer has an active explicit-
ACK subscription. These are readiness checks, not proof of a newly assigned delivery.
No shared assignment, synthetic publication, migration, replay or backfill was made.
Frontend port 5174 is down after reboot and was not started in this phase.

Added **22 parameter-expanded cases across five functions** in existing story files:
- Workflow HTTP adapter: User 404/200 blank name hold without freeze/publication/
  completion (4); User 503/read timeout retry, then recovery with original identity
  and captured content (4); Singapore midnight/equivalent offset messages (4).
- Event owner freeze: Singapore midnight/equivalent offset schedules for assignment
  and removal (4), retaining exact source facts and frozen envelope.
- Notification callback: increasing, reversed and equal actual instants represented
  with differing offsets, for both delivery types (6).

All new cases exercised existing correct behavior; no product RED was manufactured
and no additional production change was required or deployed. Temporary assertion
inversions yielded 22 ordinary failures; source was restored and full suites rerun.
Short outcome docstrings and readable parameter IDs retain the original AC headers;
repair/retry checks remain supporting design rules, not invented ACs.

| Owner | Full default suite | Whole-app line+branch coverage / unchanged floor | Complete integration tier |
|---|---|---|---|
| Event | 684 passed | 99.53% / 99.51% | 145 passed, including existing migration regressions |
| Workflow | 134 passed | 100% / 100% | 40 passed |
| Notification | 119 passed | 100% / 100% | 22 passed |

All six commands exit 0 after sensitivity-source restoration. Story collection:
**73 expanded cases / 29 functions** (Event unit/integration 18/6, Workflow 7/15,
Notification 22/5). PostgreSQL tiers used fixture-owned disposable containers and
unmodified migrations; teardown verified exact owned resources absent. Workflow
used strict HTTP doubles and a recording publisher; tests made no real broker or
external-service writes. No E2E/CI changes, generic timestamp hardening, rapid
reassignment expansion, commit or push was performed. Existing dirty work remains.

Current external evidence (logs, hashes, expanded node IDs and read-only verifier):
`/Users/daphnetok/.hermes/cache/scratch/scrum166-resume-20261027/index.json`.
The earlier Priority 1 and rollout evidence is retained, not rewritten.
