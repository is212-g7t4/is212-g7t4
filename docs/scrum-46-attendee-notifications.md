# SCRUM-46 — Attendee Registration and Update Notifications

**Current verification status — 29 October 2026:** the approved SCRUM-49 dependency
merge resolves the previously deferred 11 Event migration-harness failures. The
combined tree passes **850 Event normal tests and all 188 Event integration cases**.
See the final dependency-merge section for the exact scope and other owner results;
earlier dated red runs remain historical evidence, not current blockers.

## Story and acceptance criteria

**Story:** As an Attendee, I want to receive notifications about my registration status, so that I can confirm my place and stay updated on event changes.

- **AC1:** Given an Attendee successfully registers for an event, the system sends an in-app notification confirming their registration with the event name, date, time, venue, and registration reference number.
- **AC2:** Given an Attendee successfully withdraws their registration, the system sends an in-app notification confirming the withdrawal with the event name.
- **AC3:** Given an event cancellation takes effect, or a change to its date, time or venue is approved and applied, all currently registered Attendees receive an in-app notification with the event name and cancellation status or updated details, as applicable.

Notifications use the existing bell/inbox, RabbitMQ queue and consumer. No email/SMS or new cancellation workflow was added. Cancellation does not withdraw registrations.

## Implementation

**Registration owns action intent.** Each successful register, withdraw or re-register writes a new UUID-identified intent in `RegistrationNotificationOutbox`, in the same PostgreSQL transaction as the registration mutation. A re-registration reuses the existing full registration UUID, not the notification/action UUID. Failed/duplicate mutations do not add intents. The owner never calls another service or publishes to a broker.

The Attendee Registration composite supplies event/name/schedule and the actual earliest-starting Approved VenueBooking's venue, before saving the action. Withdrawal supplies the event name. These snapshots are persisted with the intent, so normal composite-originated actions never reconstruct content from a later event. For backward compatibility, direct atomic calls without `notificationContext` still create an intent; the worker enriches those legacy calls at first preparation. **Those legacy calls do not provide an action-time display snapshot.** Direct callers needing historical content must supply the complete context.

**Event owns cancellation/update intent.** Existing durable transitions to Cancelled also save attendee fan-out work alongside the unchanged organiser/coordinator alerts. For edits requiring renewed safety approval, Event saves the original confirmed schedule in action history before editing. Safety Check supplies the original actual venue before booking changes and the final approved venue at safety approval. Only the final Confirmed transition compares original with final details. Changed start/end/venue fields share one message; unchanged fields are omitted. A net-zero edit stays silent, and cancellation supersedes the pending update. Later approved cycles have their own baseline and identity. Pending/rejected/unrelated changes do not create attendee-update work. Existing null-schedule history remains compatible with safety withdrawal. Authentic confirmed rechecks/venue withdrawals now refuse missing, blank or non-string original `venueBefore`; final approval with an active venue baseline likewise requires valid `attendeeVenue`. Registration display snapshots reject invalid dates and timestamps that cannot render after Singapore timezone conversion, before writing the registration. Legacy no-context direct registrations remain supported.

**Event Workflow owns preparation/delivery.** Its existing dispatcher supports `OUTBOX_OWNER=registration`; Compose adds a separate Registration polling process. Event fan-out reads Registration's event-filtered list and explicitly selects Confirmed rows, because that endpoint also returns Withdrawn rows. The first successfully persisted preparation freezes the audience as deterministic UUID5 child jobs. Subsequent membership changes cannot rewrite them. This is current membership at preparation, not event-time membership history. A failed lookup is not treated as an empty audience.

Both owner APIs fence work with leases, persist a frozen envelope before publication and complete only after publisher confirmation. Retries preserve source identity/content; inbox deduplication preserves read state. Delivery failure does not undo an already committed registration or event transition.

**Frontend/history.** Consumer and frontend accept the `attendee-registration` destination, restricted to UUID references. Links open `/registrations?registration=<uuid>`, never the internal Event details route. Historical summaries retain Cancelled and other non-Confirmed events. The attendee sees full references, Withdrawn history, and a separate **Event Cancelled** label while registration status remains Confirmed. Changing notification targets resets the detail component. Attendee filtering uses the existing selected-identity model; this does not add production authentication.

**Migration:** `20261028000300_attendee_notifications.sql` adds the Registration owner outbox and extends the existing Event outbox type constraint without removing prior allowances. RLS and explicit API-role privilege revocation protect the new internal queue. There is no backfill. Apply the migration before enabling the new worker. The migration has since been applied and independently read back in the authorised shared rollout; see the rollout status below. Do not drop pending outboxes as a code rollback.

## Local verification commands

Follow [the team integration guide](testing/integration-testing.md). Unit discovery remains automatic; service integration runs in its existing CI matrix and can be selected locally. Coverage thresholds are unchanged.

Use a clean allowlisted environment; do not load service `.env` files or point test processes at a shared database. From an owning service directory:

```sh
env -i HOME="$HOME" PATH="$PATH" PYTHON_DOTENV_DISABLED=1 UV_NO_ENV_FILE=1 \
  DATABASE_URL=postgresql://synthetic:synthetic@127.0.0.1:1/unused \
  uv run --no-env-file --locked pytest -q
```

Run the new owner persistence suites, substituting `registration-service` or `event-service` as the current service directory:

```sh
env -i HOME="$HOME" PATH="$PATH" PYTHON_DOTENV_DISABLED=1 UV_NO_ENV_FILE=1 \
  DATABASE_URL=postgresql://synthetic:synthetic@127.0.0.1:1/unused \
  uv run --no-env-file --locked pytest tests/integration/test_attendee_notifications.py \
  -m integration --no-cov -q -s
```

These fixtures provision their own PostgreSQL, load the complete unmodified migration chain, establish only synthetic SQL roles, and clean owned resources. Event's migration cases separately exercise clean installation and upgrading the pre-SCRUM-46 inventory with existing rows in every table, including all prior Event notification types. They do not establish hosted Supabase role parity.

The legacy root Python E2E harness has been retired and archived. Its earlier
results below are historical evidence, not a runnable command or current coverage.
Service unit/integration tests and frontend unit/component tests remain; maintained
real-stack journeys stay in `e2e/journeys/` and remain manual/opt-in.

From `frontend/event-management-ui`, the normal commands are `npm test`, `npm run test:coverage` and `npm run build` (includes TypeScript compilation). An earlier default-parallel run timed out in six existing calendar cases; that evidence is retained. The latest follow-up passed both normal commands without changing scheduling or timeouts, and also passed the equivalent serialized scheduling below:

```sh
./node_modules/.bin/vitest run --coverage --maxWorkers=1
npm run build
```

The four Node lifecycle tests and their unused adapter were subsequently archived
and retired. Historical four-test results below describe helper cleanup only,
not current application-test counts or browser acceptance.

## Historical test inventory and measurements

Each Python story module is named `test_attendee_notifications.py` and documents ACs, boundaries and limitations. The pre-retirement counts below are parameter-expanded cases, not function counts: **120 cases**, including supporting recovery/migration rules and the now-archived root E2E sequence. The earlier execution measurements following the table are historical; the latest follow-up results appear at the end.

| Owner / tier | New story cases | Observable outcomes |
| --- | ---: | --- |
| Registration unit | 36 | Atomic intent construction, separate action identity, display snapshots, invalid/non-renderable date refusal before writes, immutable freeze, configuration/auth/input rejection, lease fencing and retry/completion |
| Registration integration | 3 | Register/withdraw/re-register and duplicate failures; no phantom work on intent-write failure; persisted frozen retry, natural-backoff reclaim and obsolete-token rejection |
| Event unit | 34 | Durable cancellation; deterministic two-recipient expansion; date/time/venue and combined content; net-zero suppression; original baseline capture; incomplete original/final venue rejection; legacy null schedules; actual A-to-B-to-C endpoint sequence, combined start/end changes and later cancellation |
| Event integration | 8 | Safety-gated combined change, cancellation superseding a pending change, reversion silence, exact frozen recipient/reference pairing, second-child rollback and owner-API recovery, distinct later approved cycle, clean/upgrade data/type/privilege preservation |
| Event Workflow unit | 16 | Required action content/destination, first-preparation audience, immutable saved changes, actual HTTP lookup shapes, withdrawn filtering, empty/error audiences, Registration owner mode |
| Notification unit | 9 | Four attendee message types accepted; invalid destination/content/recipient/change pairs refused |
| Attendee Registration unit | 4 | Cancelled-history visibility, public-summary adapter, actual approved-venue snapshot and absent-arrangement refusal |
| Safety Check unit | 6 | Earliest approved original venue, final-approval venue, lookup failure, previous-cycle boundary, absent/unnamed venues |
| Frontend component/pure | 3 | UUID destination allowlist, cancelled targeted history/reference/status, switching an already-open notification target |
| Root E2E | 1 sequence | Real registration/withdraw/re-registration -> outbox -> worker -> RabbitMQ -> consumer -> inbox; read-preserving replay; update/cancellation audiences; membership changes before/after preparation; no cancellation registration mutation; existing identity scoping |

The full normal-discovery backend run passed **3,575 tests across 15 services**, including every unchanged coverage floor. The full serialized frontend run passed **985 tests in 79 files**, plus **4 Node lifecycle tests**; the build passed.

Additional full service integration runs: Registration **6 passed**, Event Workflow **48 passed**, Notification **31 passed**, Attendee Registration **4 passed**, Safety Check **4 passed**. The FINAL full Event integration run had **174 passed / 11 failed**, including all **7** SCRUM-46 cases. Venue Booking integration also passed **36** cases; isolated cross-service E2E passed **1** full sequence. Failure node IDs match the inherited list exactly: **no new final failures**. The same 11 migration-harness failures were reproduced from a scratch export of the exact dependency revision `ec07017dead0a42ae7cfb4a84629e9f5226c472e` (11 failed / 9 passed in the selected baseline migration/submission modules). They involve missing synthetic SQL roles and a stale exact-table inventory in earlier infrastructure tests, not a passing full Event tier. At that run those older tests remained unrepaired and visible; the narrow SCRUM-46 expectation follow-up below does not repair their inherited fixture/Equipment defects.

### Coverage denominators

Coverage is a measurement, not proof of exhaustive behavior. Whole affected services, statements / branch arcs:

| Service | Covered statements | Covered branch arcs |
| --- | ---: | ---: |
| Registration | 298 / 299 | 83 / 84 |
| Event | 1,950 / 1,950 | 714 / 714 |
| Event Workflow | 619 / 619 | 208 / 208 |
| Notification | 401 / 401 | 218 / 218 |
| Attendee Registration | 227 / 227 | 55 / 56 |
| Safety Check | 1,052 / 1,052 | 378 / 378 |

For backend executable statements added/changed against the dependency revision, all measured statements and branch arcs originating on added/changed lines were exercised: Registration **129/129, 46/46**; Event **99/99, 64/64**; Workflow **59/59, 34/34**; Notification **21/21, 22/22**; Attendee Registration **29/29, 10/10**; Safety Check **24/24, 14/14**. This uses coverage.py's executable-line set intersected with the diff, not all lines in a source file.

Frontend measurement now includes NotificationCenter, notifications, attendee registration adapters/page and App. Whole measured frontend: **1,177/1,264 statements**, **892/937 lines**, **1,091/1,224 branches**, **345/375 functions**. NotificationCenter and notifications are 100% measured. App remains **94/129 lines, 77/148 branches**; AttendeeRegistrationsPage remains **46/50 lines, 56/68 branches**. There is no blanket 100% frontend claim.

## Historical final verification after review fixes — 28 October 2026

**Historical pre-rollout verification.** Notification-only behavior and the isolated runs below passed apart from the same 11 inherited migration-harness failures. The pre-existing booking/safety concurrency race remains unresolved; no workflow fence or second-lookup workaround was added. The later authorised rollout and user-reported manual pass are recorded separately below.

- Final normal backend discovery: **3,575 passed across 15 non-template services**, all original configured floors passed.
- Final full affected integrations: Registration **6 passed**; Event **174 passed / 11 failed**; Event Workflow **48 passed**; Notification **31 passed**; Attendee Registration **4 passed**; Safety Check **4 passed**; Venue Booking **36 passed**. Total **303 passed / 11 inherited failures**; exact failed node IDs equal the previously recorded dependency failures, with **zero new final failures**.
- Final isolated cross-service E2E: **1 passed**. Frontend serialized coverage: **985 passed in 79 files**; Node lifecycle **4 passed**; normal TypeScript/Vite build **passed**. The latter four are adapter lifecycle tests, not browser acceptance.
- Authored story inventory: **119 parameter-expanded cases**: Registration unit 36 + integration 3; Event unit 34 + integration 7; Event Workflow unit 16; Notification unit 9; Attendee Registration unit 4; Safety Check unit 6; frontend component/pure 3; isolated E2E 1. Supporting DR and migration cases are included and explicitly labelled; these are not 119 independent acceptance requirements. No scenario padding was added in this final-verification pass.
- Existing successful direct fixtures now supply valid explicit `venueBefore` for confirmed rechecks/withdrawal and `attendeeVenue` for final approval/restoration when a venue baseline exists. The older Safety notification helper now leaves all three unrelated cancellation jobs leased rather than mistaking attendee fanout for its own decision. Its original content/state assertions remain unchanged. Initial failures (12 Event integration failures and 1 E2E failure) are retained, not overwritten; after these fixture corrections the **entire verification matrix** was rerun on stable source.
- Every new story module, including frontend and E2E, now carries the exact Story and all three accepted AC sentences above. Python header-only edits preserve executable ASTs; every case has an outcome docstring, and the checklist retains exact parameter-expanded case IDs.
- The historical assertion-sensitivity campaign `scrum46-integration-sensitivity-20261028-213613` recorded **10/10 genuine assertion failures, zero setup errors**, followed by **10/10 restored green** owner integration cases. Its two final integration modules have the same executable ASTs as the current modules; only exact header wording changed here. This is assertion sensitivity, not implementation mutation coverage or newly manufactured product RED; its production hashes precede the review fixes. The final current-source integration results above are separate evidence.

### Inherited concurrency risk — separately deferred, not silently repaired

The deterministic pause probe reproduces the same unsafe result on the feature source and the exact dependency revision `ec07017dead0a42ae7cfb4a84629e9f5226c472e`: venue-B booking write pauses after safety withdrawal; another safety review approves still-approved venue A; Event becomes Confirmed; the delayed B write then leaves venue B Pending Review. At approval the notification comparison correctly sees A-to-A and emits no update; the later booking write has no recheck. A second read cannot fence that in-flight write.

Evidence is retained in `review-fixes/race-current.log`, `race-base.log`, `orchestration_probe.py` and `REVIEW-FIXES.md`. This uses actual Venue Booking/Safety Check/Event route orchestration with in-process HTTP routing and SQL/storage doubles, **not PostgreSQL concurrency or full-stack race proof**. The normal composite A-to-B-to-C probe and the persistent Event endpoint regression establish the ordinary sequence, not a durable concurrency guarantee. A workflow/schema fence would require separately approved business-orchestration scope; it is deliberately not implemented in this notification-only story.

### Final evidence index

The external local evidence directory is `scratch/scrum46/final-verification` under the agent cache (not repository content):

- `command-results.json`, individual `.result.json`, raw `.log` and JUnit `.xml`: exact commands, exits, counts and per-command source stability. The orchestration runner finishing with exit 0 does **not** override Event's recorded child exit 1.
- `source-manifest.json`, `source-manifest-after.json`, `source-stability.json`, `production-preservation.json`: SHA-256 fingerprints before/after all final runs, independently matched to the live source; production files unchanged by this pass.
- `failure-comparison.json`, `inherited-failure-nodeids.json`: exact inherited/final failure equality.
- `case-inventory.json`, `CASE-INVENTORY.md`: every authored case, grouped by owner/tier, plain-English outcome, actual parameter-expanded identity and parameter definitions.
- `*-service-coverage.json`, `changed-coverage.json`, `frontend-coverage/`: final machine-readable coverage and denominators, without floor/exclusion changes.
- `initial-final-attempt/`: retained first-attempt failures and their original manifest. `resource-check.json` confirms no matching fixture test containers remained after the final run; this does not independently establish anonymous-volume absence for every older fixture.

## Narrow SCRUM-46 schema-expectation follow-up — 28 October 2026

Only `RegistrationNotificationOutbox` was added to the two older migration helpers' current-schema table/RLS expectations. Infrastructure checks explicitly retain the exact old inventory at the historical approval/assignment stage. Both table and RLS assertions still use exact equality; no unexpected table is ignored. The inherited `EquipmentNotificationOutbox` omission and missing synthetic-role bootstrap remain deferred to separately owned maintenance. No migration, fixture, production, CI or coverage-gate change was made in this follow-up.

Fresh isolated verification: Event normal unit discovery **850 passed / 185 deselected**, unchanged **100%** coverage gate (1,950 statements / 714 branch arcs); SCRUM-46 Event integration **7 passed**; SCRUM-46 Registration integration **3 passed**. The two selected older migration/submission modules remain **9 passed / 11 failed** (child exit **1**): ten failures lack SQL role `anon`; the bootstrapped exact-schema case now reports only the inherited extra `EquipmentNotificationOutbox`, not the Registration table. The failed case IDs exactly match the previously recorded dependency failures. This is not a green full Event integration claim.

A small external AST/source-contract inspection passed: it checks the current-only Registration addition, the explicit historical call stage, the deferred Equipment omission and preservation of every helper assertion after parameter-name normalization. This is source-scope evidence, not a synthetic passing database test or newly manufactured RED. Existing SCRUM-46 database cases already cover the table's creation, upgrade, RLS and grants and were rerun unchanged. Exact commands, raw logs, JUnit and inspection script/output are retained under the agent cache's `scratch/scrum46/scope-only-repair`, outside Git.

## Evidence and remaining limits

Actual RED->GREEN logs were retained outside Git for registration intent, dispatcher content, cancellation, fan-out, effective updates, consumer acceptance, original venue, historical visibility, UI destination, registration snapshot, legacy schedule, target switching and private-outbox grants. Intermediate unsuccessful files labelled `green` were retained as failures; later successful reruns are identified separately. Other additions characterize existing behavior rather than manufacturing RED.

Existing generic worker tests are reused for freeze-before-publish, freeze failure, owner-returned envelope, broker confirmation/NACK, per-job failure isolation and ambiguous publish/completion replay: `test_scrum45_notifications.py`, `test_scrum49_event_change_notifications.py` and their service-integration counterparts. Existing Notification persistence/dedup tests and the real E2E cover inbox replay/read preservation. Reuse is not a new attendee-specific fault-injection claim.

Remaining limits:

- The historical 11 Event migration-harness failures are resolved in the approved SCRUM-49 dependency merge, verified below on the combined SCRUM-46 tree. They are no longer a current deferred limitation. CI policy wording remains inconsistent between existing guides/configuration; no workflow was edited.
- There is no automated real-browser journey and no new production authentication. UI assertions use API doubles. The subsequent shared rollout/source checks and user-reported manual pass do not change that automated-test boundary.
- E2E enters final safety decisions through the Event owner API, not a complete Safety Check + Venue Booking user journey. The Event unit sequence proves A->B->C accumulation and a retained prior-cycle alert through later cancellation, but no intermediate A->B->C browser journey is proven. The inherited concurrency race described above is explicitly deferred to separate business-orchestration work; it is not a new SCRUM-46 CI gate.
- Registration's new outbox has real retry/reclaim/stale-token coverage, but elapsed-time lease expiry is only directly exercised by its unit boundary, not a new 60-second PostgreSQL expiry test.
- Existing generic infrastructure supplies failure/replay coverage; not every approved failure scenario has a separate attendee-specific persistence test. The new owner integration modules have 10/10 assertion-sensitivity evidence, which is not production mutation testing.
- Direct legacy atomic registrations without a display context retain first-preparation enrichment rather than immutable action-time content.

No commit, push, staging, deployment, shared database operation, private configuration edit or coverage-gate reduction was performed in this pre-push strengthening/documentation pass. Earlier authorised rollout is recorded below. The pre-existing dirty `.DS_Store` was preserved.


## Authorised rollout and manual status (supersedes pre-rollout limitations)

The parent-session rollout record reports migration **20261028000300** applied
and independently read back, with exact migration SHA-256
`0995aa27d7959f2e251109ef7cc9d506e7d8f55e07f24ad5a9426d5eb9aba5ce`.
The recorded **nine deployed-source comparisons matched** their checked local
sources. The user subsequently **reported manual testing passed**. These are
historical rollout/manual observations supplied to this pass, not a new shared
probe or an automated browser result. This pass changes tests/documentation only;
it neither reapplies the migration nor restarts any shared process.

The normal Docker build path encountered a **uv `Exec format error`**. The
approved existing-image fallback was verified and used for the scoped rollout;
that success does **not** establish that the normal Dockerfile build is fixed.
Keep that portability caveat distinct from application assertions and the passing
frontend TypeScript/Vite build.

The inherited booking/safety race remains explicitly deferred business-orchestration
work, not a newly added CI/merge gate. The **11 older Event integration failures**
were deferred at rollout time; the approved SCRUM-49 dependency merge below resolves
their test-harness prerequisites and inventory defects, with the complete combined
Event tier now passing. No workflow, gate, threshold, production implementation or
migration was changed for that maintenance.

## Pre-push strengthening and test readability follow-up

- Retained every existing case identifier and parameter value. Event's existing
  unit and PostgreSQL fanout cases now compare complete deterministic child-ID,
  recipient and registration tuples, not independent recipient/reference sets.
  The isolated E2E verifies each delivered update/cancellation's recipient,
  details reference and destination reference against its original registration.
- Added exactly **one** Event PostgreSQL scenario: fail the **second** child insert
  after the first has run, independently observe zero committed children and an
  unpublished retryable parent, then recover via normal retry/backoff/claim/expand
  APIs. Recovery preserves the original two recipient/reference pairs and rejects
  the old lease. The trigger and its sequence exist only in the fixture-owned DB.
- The interrupted attempt's sole failure was an expected-value adapter mismatch:
  its independent libpq reader returned a UUID string rather than a Python UUID
  object. The test expectation now uses the exact owner token string. After that
  fixture/assertion correction all eight Event story integrations passed with no
  production edit. This is **initially green characterization**, not a genuine
  product RED-to-GREEN repair.
- Two deliberate bad-result probes produced ordinary assertion failures (zero
  setup errors): swapped persisted registration links preserved the earlier
  independent-set assertions but failed the new tuple assertion; an inserted
  committed child after the controlled failure failed the no-partial-children
  read. These prove **assertion sensitivity**, not production mutation coverage
  or newly discovered product defects. Probe bytes were restored before green runs.
- Every authored Python story test and all three frontend cases now explain the
  scenario/setup, action, expected result, significance and real/doubled boundary.
  Parameter meanings are spelled out without renaming IDs. Full Story/AC wording
  remains once per module; supporting recovery/migration rules are not extra ACs.
  Complex sequences have Arrange/Act/Assert commentary, and story fixture/builders
  explain their inputs, outputs and isolation role.
- Documentation has a separate phase-boundary backup. Executable Python ASTs with
  docstrings removed and frontend TypeScript transpilation with comments removed
  are identical before/after that phase. Parameter-expanded Python collection IDs
  are unchanged. These comments improve explainability, **not executable coverage**.

Current raw command logs, JUnit case records, source hashes, before-documentation
backups, executable-equivalence proofs and sensitivity evidence are retained
outside Git under the agent cache's `scratch/scrum46/prepush-strengthening`.
The earlier dated verification sections remain historical evidence, not a claim
that their old counts include the additional rollback case.


### Verified follow-up results — 29 October 2026

| Verification | Actual result |
| --- | --- |
| Full normal backend discovery, 15 services | **3,575 passed**, all unchanged configured coverage floors passed |
| Complete Registration integration tier | **6 passed**, including all **3** story cases |
| Complete Event integration tier | **175 passed / 11 inherited failures**, including all **8** story cases |
| Event Workflow / Notification integration | **48 / 31 passed** |
| Attendee Registration / Safety Check / Venue Booking integration | **4 / 4 / 36 passed** |
| Combined affected service integrations | **304 passed / 11 inherited failures**, exact inherited failed IDs unchanged |
| Isolated cross-service E2E | **1 passed**, exact update/cancellation recipient-reference-destination pairing and owned cleanup assertions passed |
| Normal `npm test` | **985 Vitest cases in 79 files + 4 Node lifecycle cases passed** |
| Normal `npm run test:coverage` | **985 Vitest + 4 Node lifecycle cases passed**, unchanged coverage configuration |
| Serialized coverage equivalent | **985 passed in 79 files**; separate **4 Node lifecycle cases passed** |
| Normal `npm run build` | **Passed**, including TypeScript compilation and Vite build |

After the full matrix, targeted explanatory comments were added beside the
SCRUM-46-related changes in older tests. Full normal discovery was rerun for
Registration (**83**), Event (**850**), Attendee Registration (**50**) and Safety
Check (**523**), all passing their unchanged gates. The complete Event and
Attendee Registration integration tiers were rerun again with the same results
above. Their full collected execution identities are unchanged. All rerun source
hashes stayed stable; the full-matrix source hashes also stayed stable during its
own run. No executable change separates these two documentation stages.

The current story inventory is **117 Python parameter-expanded cases** in **44
Python test functions**, plus **3 frontend cases**, for **120 executed passing
story/supporting-rule cases**. All previous **119** case identifiers remain, with
only the approved second-child rollback/recovery case added. Normal whole-suite
counts include unrelated regression coverage and are not additional story cases.

Coverage denominators remain the earlier measured values: Event, Workflow,
Notification and Safety Check have no missing statements or branch arcs in their
whole-service reports; Registration remains **298/299 statements, 83/84 branch
arcs**, and Attendee Registration **227/227 statements, 55/56 arcs**. Frontend
remains **1,177/1,264 statements, 892/937 lines, 1,091/1,224 branches,
345/375 functions** across its configured measurement scope. Readability and
assertion strengthening do not increase those executable coverage measurements.

Evidence files in the external `prepush-strengthening` directory include:
`command-results.json`, `documented-command-results.json`, per-command logs and
JUnit, `case-inventory.json` / `CASE-INVENTORY.md`, `case-identity-comparison.json`,
`documentation-ast-proof.json` (**29 Python files**),
`documentation-typescript-proof.json`, `collection-proof.json`,
`failure-comparison.json`, `final-source-manifest.json` /
`final-source-manifest-after.json`, and `scope-preservation.json`.
The latter verifies **620 out-of-scope paths unchanged**, including production,
migrations, configuration and gates. `resource-check.json` independently found
all **23 named test containers** and **55 logged owned volume identities** absent;
E2E also asserted its owned process groups absent. Older fixtures without logged
volume identities are not silently included in that independent volume claim.
`git diff --check` passed. The work remained uncommitted and unstaged at that
historical handoff; no commit, push or deployment was part of that child task.

## Approved SCRUM-49 dependency merge verification — 29 October 2026

Verified the genuine pending merge of SCRUM-49
`d0f79e698e13a22493f125b3bd3ad308a56dccbe` into SCRUM-46 HEAD
`9e43147b51d2c0550d28f50fffe061dc5a4640f5`. Only the two approved conflict
paths were resolved and staged by this pass. The auto-merged Event integration
fixture was inspected: migration-required synthetic NOLOGIN roles always exist;
default grants remain opt-in. Both parameter-expanded role regression cases
(`roles-only`, `default-grants`) are retained and pass.

Current exact table and RLS inventories retain **both**
`EquipmentNotificationOutbox` and `RegistrationNotificationOutbox`. The historical
approval/assignment inventory is unchanged and passed explicitly at its old stage.
Exact equality assertions remain intact; no unexpected table is ignored. This is
test maintenance, not a migration or production repair.

| Complete owner tier | Normal discovery | Integration discovery |
| --- | ---: | ---: |
| Event | **850 passed** | **188 passed** |
| Registration | **83 passed** | **6 passed** |
| Event Workflow | **187 passed** | **48 passed** |
| Notification | **219 passed** | **31 passed** |
| Attendee Registration | **50 passed** | **4 passed** |
| Safety Check | **523 passed** | **4 passed** |
| Total executed in this pass | **1,912 passed** | **281 passed** |

All 12 child commands exited **0**, with zero failures, errors or skips. Normal
commands used `uv run --no-env-file --locked pytest -q`; integration commands added
`-m integration --no-cov -s`. Each recorded JUnit outside Git. The allowlisted
environment disabled dotenv and used an unreachable synthetic fallback DSN; only
fixtures provisioned databases. Event's unchanged 100% floor passed (1,950
statements / 714 branch arcs). All other existing owner floors passed unchanged.
The Event integration increase from the prior 186 collected cases to 188 is the
two incoming SQL-role regression parameters; all eight attendee Event integration
cases remain included.

Evidence is outside Git in the agent cache's `scratch/scrum46/dependency-merge`:
`command-results.json`, per-command `.log` / `.xml` / `.result.json`, before/after
source manifests, `source-stability.json`, `production-preservation.json` and
`resource-check.json`. Source hashes were stable throughout every run and across
the matrix. Independent cleanup readback found all **26 logged fixture container
names and 26 logged volume identities absent**. This does not extend the volume
claim to older fixtures that do not log volume identities.

The pending index, both conflicted worktree files and all six conflict-stage
blobs were archived before resolution. The unrelated dirty `.DS_Store` bytes were
preserved. Production application, migration, dependency and workflow paths were
unchanged against the pinned SCRUM-46 HEAD. No shared database, deployment or
private environment was accessed. Documentation changes remain unstaged for
parent review; the genuine merge remains pending, with no commit, push, branch
switch, PR creation or main merge performed.

The earlier dated 11-failure results above are preserved, but their role/bootstrap
and table-inventory limitations are no longer current. The separately deferred
booking/safety concurrency race, authentication/browser boundaries, legacy
snapshot caveat, normal Docker-build portability caveat and other remaining limits
still apply. Frontend, isolated cross-service E2E, all-service backend discovery,
hosted CI and compatibility with every other branch were **not** rerun or proven
by this scoped dependency-merge verification.
