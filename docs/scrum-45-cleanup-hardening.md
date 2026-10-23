# SCRUM-45 cleanup hardening

Executed October 23, 2026 on `SCRUM-45-event-organiser-status-and-update-notifications`,
starting at `21c2169`. Follow-up to `scrum-45-test-strengthening.md`; historical
claims and logs are not rewritten. Changes are verification infrastructure only:
no application code, dependencies, migrations or production configuration changed.

## Regressions and fixes

- **Owned process group outlives its leader.** Added an actual POSIX subprocess
  regression: `start_new_session=True`, fork a child, wait for its installed
  SIGTERM-ignore handler, then invoke fixture cleanup. The leader dies on SIGTERM;
  success requires `killpg(pgid, 0)` to raise `ProcessLookupError` for the entire
  group. The RED run failed with `leader exited but owned process group still
  exists`; its `finally` killed only that test-created group and verified absence.
  Cleanup now checks group disappearance independently of leader `wait()`, allows
  a bounded one-second group grace period, escalates only the owned PGID, and
  checks absence for up to five seconds after SIGKILL. Leader waits remain bounded
  at ten/five seconds. Missing-group races are harmless. Zombies can keep a group
  observable until its parent/init reaps them: expiry reports **absence unverified**,
  not a false success or a claim that a zombie is still executing.
- **Browser diagnostics mask the primary exception / skip close.** Mechanically
  extracted the original catch/finally behavior into `e2e-real/journey-lifecycle.mjs`
  before running the new Node built-in regression. With journey, screenshot and
  request-log failures, RED observed the request-log error instead of the original
  journey error; close was unreachable. GREEN keeps the original exception object,
  reports screenshot/write errors separately, and attempts browser close in a
  nested `finally`. A second RED/GREEN slice verified that close rejection also
  cannot replace the primary error. Additional passing checks cover diagnostic
  write failure after success (reported and raised, not silent) and the success
  return/write/close path. Context/page creation now occurs inside the protected
  callback. No new test framework or application dependency was introduced.

`runBrowserJourney` defaults to reporting secondary diagnostics on stderr. With no
primary journey exception, diagnostic/close failures raise an `AggregateError`.
The boundary tests substitute only external I/O callbacks; the separate browser
integration uses actual Chromium, UI, HTTP services, PostgreSQL and RabbitMQ.

## Actual execution

Raw command logs and browser artifacts are retained outside Git at:

`/Users/daphnetok/.hermes/verification/scrum45-cleanup-hardening-20261023/`

| Log | Observed result |
|---|---|
| `process-red.log` | **1 failed / 3 deselected**, expected surviving-child assertion; emergency cleanup succeeded. |
| `process-green.log` | **4 passed**, including actual subprocess regression and existing failure aggregation/container checks. |
| `browser-lifecycle-red.log` | **1 failed**, original error replaced by `request-log disk full`. |
| `browser-lifecycle-green.log` | **1 passed** after the diagnostic/close-attempt fix. |
| `browser-close-red.log` | **1 failed / 1 passed**, close error replaced original exception. |
| `browser-close-green.log` | **2 passed** after separate close-error reporting. |
| `browser-lifecycle-final.log` | **4 passed**, zero failed/skipped/cancelled. |
| `workflow-unit.log` | **97 passed / 26 integration deselected**, application coverage **100%**, configured gate met. Includes all four cleanup regressions. |
| `real-browser.log` | **1 passed** in 8.21s, no teardown errors or skips. |
| `browser-tmp/test_lead_rejection_reaches_or0/browser.log` | Actual rejection/delivery/inbox/read-linked-details PASS. Request JSON has empty errors and every recorded response status is 200; linked-details PNG retained alongside it. |
| `containers-before.txt`, `containers-after.txt`, `resource-check.log` | Exact Docker ID/name/state sets equal; no additional SCRUM-45 containers remain. All pre-existing manual containers retained. |

Re-run from `services/event-workflow-service` (choose an external scratch `$E`):

```sh
uv run pytest --basetemp="$E/unit-tmp"
uv run pytest tests/unit/test_isolated_harness_cleanup.py --no-cov -v \
  --basetemp="$E/cleanup-tmp"
uv run --with psycopg2-binary python -m pytest \
  tests/integration/test_browser_journey.py -m integration --no-cov --tb=short \
  --basetemp="$E/browser-tmp"
```

From `frontend/event-management-ui`:

```sh
node --test e2e-real/journey-lifecycle.test.mjs
```

## Scope and limitations

- No shared Supabase/remote application database or production application API
  was contacted. All data API traffic in the browser fixture targets loopback.
  The existing UI **does load Google Fonts externally**; recorded hosts include
  `fonts.googleapis.com` and `fonts.gstatic.com`, so this is not an offline test.
- No broad `pkill`, Compose teardown, Docker prune or deletion by prefix was used.
  Only fixture-owned PGIDs and exact UUID-owned container names are cleanup targets.
  Before/after ID/name/state equality is not a general audit of unrelated activity
  on the host; no claim is made about every pre-existing process on the machine.
- Cleanup is bounded best effort with explicit failure reporting, not an
  unconditional guarantee under SIGKILL of the harness, machine crash, descendants
  escaping their owned process group, stuck external I/O or an OS that fails to
  reap orphan zombies. A close attempt is not proof a browser close succeeded.
- **Separate reproducibility recommendation (not changed here):** lock the
  `uv run --with psycopg2-binary` overlay and pin `postgres:17` /
  `rabbitmq:4-management` to immutable digests in a dedicated follow-up. Current
  runs reuse the existing environment/images; floating tags/overlay resolution
  can differ on another machine. This is a limitation, not a cleanup blocker.
- Static added-line security scan, `ruff check` for both touched Python files,
  Node syntax checks and `git diff --check` passed. Independent Codex CLI review
  exited 1 without a verdict; it is **unavailable**, not a passing review. Per
  user direction no CLI retry/fallback delays the local commit; parent-owned
  independent diff review remains pending.
- No push, shared-stack change or full backend/frontend acceptance rerun is
  claimed. Requested workflow unit, browser integration and cleanup scopes passed.
