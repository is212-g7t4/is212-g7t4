# SCRUM-45 test-strengthening follow-up

Executed October 23, 2026 on
`SCRUM-45-event-organiser-status-and-update-notifications`, starting from clean
`9816f7b`. This is an additive audit follow-up: original specifications, historical
RED/GREEN records and their stated limitations are unchanged. No application
production code, migration, shared development database or production `.env` was
changed. No push or tracker closure is claimed; independent review remains pending.

## Approved fixes checked

| Audit item | Implemented evidence |
|---|---|
| Freeze before publication | `tests/unit/test_freeze_before_delivery.py`: approval, rejection and assignment × owner-success/freeze-outage. Ordered effects require successful freeze before broker I/O and completion after publish; outage requires zero broker calls/zero completion. A distinct owner-returned envelope must be published instead of the local draft. Existing content/retry tests retained. |
| Freeze really writes | Event's existing approval/rejection/assignment freeze unit cases now require one envelope UPDATE with independently prepared payload and source ID. `test_freeze_persistence.py` has three real PostgreSQL cases: freeze, retry/release, then new HTTP claim/new database transaction must read the saved envelope; a second freeze cannot replace it. No direct cross-service database read is used as the persistence assertion. |
| Replay synchronization | Decision integration tests replace queue-emptiness sampling with `replay_barrier`: publish duplicate, publish independent FIFO sentinel, observe sentinel in inbox, then require exact total of two, exactly one original source, stable original notification ID and unchanged non-null `readAt`. One consumer per isolated queue. |
| Legitimate Lead assignment | Harness seeds a real `Event Coordinator Lead` and starts the real Coordinator Assignment composite against real User/Event HTTP. Initial assignment checks organiser refusal (403/no work), valid Lead success and no-op (409). Rapid Alice→Bob reassignment goes through that composite, preserving both deliveries. Existing direct atomic mutation fault/name-hold/outage/rollback cases deliberately remain direct tests, not falsely described as authorised composite workflows. |
| Normal linked approval / rejection fixture assertions | Two new normal-ownership approval cases (approve/progress) follow the actual delivered destination as the original recipient and read the expected name/approval/no reason. The separate historical ownership-change case remains. Rejection integration independently requires exact type, literal event name, decision, reason, message, recipient and destination—not merely equality to the worker's own output. |
| Unmocked browser journey | `test_browser_journey.py` runs `e2e-real/scrum45-journey.mjs` using existing Playwright Chromium and real Vite. A legitimately assigned Lead rejects through UI; real Event/PostgreSQL/outbox worker/RabbitMQ/consumer delivery reaches the organiser inbox; organiser refreshes, opens the actual notification, reads linked rejection details and changes unread→read. Independent owner/inbox reads confirm persistence after browser assertions. Final browser request log has **zero failed requests/page errors**; all observed backend requests returned 200. Screenshot and request log are external artifacts. |
| Repeatable cleanup | Function-scoped synthetic fixtures use UUID-owned Docker containers, random loopback API/UI ports, four separate owner databases, migration-derived schemas and dotenv suppression. Owned process groups include worker children; composites/dispatcher receive no owning-service database URL. Teardown attempts every process/log/container despite earlier failures, checks `docker rm` status and reads back exact container absence. Setup failures retain the original exception with cleanup notes; ordinary cleanup failures are separate pytest teardown failures. Three hermetic cleanup regressions exercise failure aggregation, false-success removal and process timeout/missing groups. |

Every touched Python module contains the full canonical story; all test functions
have AC/DR + method/observation docstrings (AST-checked). No test imports another
test module. Shared fixture helpers remain in `tests/integration/system.py`.

## Test-first / failure-sensitivity evidence

Existing feature behaviour was already GREEN. These are **mutation REDs for
stronger tests**, not fabricated missing-feature REDs. No production fix was
needed. Mutations ran in a subprocess with exact original file bytes restored in
`finally`; final production diffs are empty. Coverage was disabled only for narrow
mutation/integration probes, never for the final unit gates.

Raw logs and runnable probe/config scripts are retained **outside the repository**:
`/Users/daphnetok/.hermes/verification/scrum45-test-strengthening-20261023/`.
The executed originals used sibling scratch directory
`/Users/daphnetok/.hermes/cache/scratch/scrum45-strengthening/` (`$E` below).

| Mutant | Before strengthening | After strengthening / exact observed kill |
|---|---|---|
| Worker publishes draft before freeze, preserving the already-frozen retry branch | Original workflow unit subset: **87 passed**, 26 integration deselected. Earlier focused original happy-path approval/rejection/assignment tests also **3 passed**. | New focused contract: **6 failed**, one per type × success/outage. Broker attempted too early; freeze never reached. `before-order-preserved-retry.log`, `after-order-preserved-retry.log`. |
| Worker ignores `freeze()` return and publishes local draft | Original workflow suite: **87 passed**, 20 integration deselected. | New focused contract: **3 failed / 3 passed**; owner-result success cases fail, freeze-outage cases remain green. `before-draft.log`, `after-focused-draft.log`. |
| Event envelope UPDATE replaced by parameter-compatible SELECT | Original Event unit suite: **532 passed**. | **3 failed / 529 passed**: each meaningful write/payload contract rejects zero envelope writes. `before-write.log`, `after-write.log`. |
| Same no-write SELECT, but first freeze HTTP response deliberately echoes the proposed envelope | Additional independent persistence probe; no historical baseline result claimed. | Real PostgreSQL **3 failed** precisely at independent reclaimed envelope comparison (`None` versus expected). Initial freeze response had passed. `after-write-real.log`. |
| Consumer replay conflict resets `read_at=NULL` instead of doing nothing | Additional replay sensitivity probe; no historical baseline result claimed. | Real decision cases **4 failed / 6 deselected**, each at preserved `readAt` assertion after observed sentinel. `after-replay-real.log`. |

An early exploratory ordering mutant accidentally also removed already-frozen
retry publication; its broad failures are **not** the accepted ordering evidence.
The corrected before/after probe above preserves that branch. Raw exploratory
logs remain available rather than being rewritten into a better chronology.

Reproduce the probes from repository root (external `mutate.py` contains the exact
single-site substitutions; `mutate_real.py` and `mutate_replay.py` contain the real
integration probes):

```sh
E=/Users/daphnetok/.hermes/cache/scratch/scrum45-strengthening
R="$PWD"
python3 "$E/mutate.py" "$R" before-order-preserved-retry order \
  --ignore=tests/unit/test_freeze_before_delivery.py \
  --ignore=tests/unit/test_isolated_harness_cleanup.py
python3 "$E/mutate.py" "$R" after-order-preserved-retry order tests/unit/test_freeze_before_delivery.py
python3 "$E/mutate.py" "$R" after-focused-draft draft tests/unit/test_freeze_before_delivery.py
python3 "$E/mutate.py" "$R" after-write write
python3 "$E/mutate_real.py" "$R"
python3 "$E/mutate_replay.py" "$R"
```

The ignore list recreates the original workflow unit subset only; it does not hide
any original tests. The before-write result was recorded before changing Event's
three existing assertions; rerunning that command now correctly fails the mutant.

## Final restored-code verification

| Command / scope | Actual result |
|---|---|
| Root `npm run test:backend` | **2,571 passed across 17 services**, **28 integrations deselected**, exit 0. |
| Event `uv run pytest` | **532 passed**, coverage **99.11%**, existing 99.11 gate met. |
| Event Workflow `uv run pytest` | **96 passed / 26 deselected**, coverage **100%**. |
| Notification `uv run pytest` | **97 passed**, coverage **100%**. |
| Coordinator Assignment `uv run pytest` | **37 passed**, coverage **87.85%**, inherited 87 gate met. |
| User `uv run pytest` | **8 passed**, coverage **97.87%**, inherited 97 gate met. |
| Venue Availability `uv run pytest` | **447 passed / 1 deselected**, coverage **100%**. |
| Event Workflow real integration command below | **26 passed / 96 unit deselected**, no skips or teardown errors, exit 0. Includes one unmocked browser journey, all four migration-order cases and all existing fault/outage cases. |
| UI `npm run test:coverage` | **720 passed / 59 files**; configured scoped coverage 98.1% statements / 92.4% branches / 96.6% functions / 98.76% lines. |
| UI complete mocked Playwright suite, scratch copied config below | JSON parsed: **73 expected passes / 0 unexpected / 0 flaky / 0 skipped**, exit 0. Separate from actual-delivery browser evidence. |
| UI `npm run build`; `npm run lint` | Both exit 0; three inherited Fast Refresh warnings remain. |
| `git diff --check`; production directory diff; exact Docker-name readback | Clean; no production changes; no `scrum45-` containers remaining. User's pre-existing `is212-g7t4-*` containers were not modified. |

```sh
# From services/event-workflow-service; no host psql needed:
uv run --with psycopg2-binary python -m pytest -m integration --no-cov --tb=short \
  --basetemp=/Users/daphnetok/.hermes/cache/scratch/scrum45-strengthening/integration-boundaries-final
# Browser alone, using the same isolated fixture:
uv run --with psycopg2-binary python -m pytest tests/integration/test_browser_journey.py \
  -m integration --no-cov --tb=short
# From frontend/event-management-ui; complete mocked suite on a random UI port:
node node_modules/@playwright/test/cli.js test \
  --config /Users/daphnetok/.hermes/cache/scratch/scrum45-strengthening/isolated-copied.config.ts
```

Integration prerequisites: Docker Desktop with `postgres:17` and
`rabbitmq:4-management`, service-local locked dependencies (`uv sync --locked` in
Event, User, Notification, Coordinator Assignment, Event Workflow and Venue
Availability), frontend `npm ci` and existing Playwright Chromium. No global
package installation and no shared Supabase development database access.
Real Vite uses an empty external `envDir`, explicitly pinned local service URLs
and a dynamic UI origin; no production/root/frontend `.env` is loaded.

## Resolved setup failures and limits

- Initial bare integration invocation lacked `psycopg2`: **25 setup errors**, not
  a behavioural RED. Reused established `uv run --with psycopg2-binary` command.
- Adding real availability for the Lead's unrelated reminder poll initially
  omitted the baseline VenueClosure dependency; included that owner table and
  synthetic `CALENDAR_DEV_MODE=true`. First browser attempt then exposed the real
  25-second inbox poll versus a 20-second wait; use the existing Refresh control
  with a bounded condition-based wait instead of changing product timing.
- Two scratch wrapper-config mocked-e2e attempts failed collection (`SERVICE_PORTS`
  named export), executing **zero** tests. Copying the complete existing config
  into scratch (absolute paths, dynamic port, empty envDir, external JSON/report
  paths; no config import wrapper) ran all 73. Not counted as product REDs.
- The real browser covers **one rejection journey**, not every approval/assignment
  combination in a browser; those have separate real backend and mocked UI
  coverage. It uses demo identities, not production authentication. Chromium is
  headless; this is not a deployment/Compose boot or a latency SLA. The app's
  existing Google Fonts stylesheet may load externally; all data APIs are local.
- Root backend intentionally deselects 28 integrations: the 26 SCRUM-45 cases ran
  separately; unrelated Venue Booking and Venue Availability integrations did not.
  Inherited coverage gaps/warnings are not silently reclassified as fixed.
- No unresolved execution blocker for the requested audit fixes. Parent-owned
  independent review remains the next gate; historical evidence is not closed,
  replaced or rewritten by this document.
