# SCRUM-45 latest-main sync — October 23, 2026

Local only; **no push/PR, shared database writes/migrations, env-file replacement,
or manual-stack restart**. Current manual instructions are
[`scrum-45-manual-testing.md`](scrum-45-manual-testing.md); older evidence retains
its historical commands/results, including the former test paths.

## Inputs and merge

- Worktree: `/Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-integration`.
- Branch: `SCRUM-45-event-organiser-status-and-update-notifications`.
- Initially clean tracked/untracked state; starting HEAD:
  `f008338474f25382d18069eafd6d6e770ec340cb`.
- `git fetch origin`; fetched `origin/main`:
  `dfaa52839ab76f437ff86448bef89b75abbf2f92` (`SCRUM-15: Edited integration tests`).
  Re-fetch/reverification at **2026-10-23T13:38:32Z** found the same main tip.
- Read main's AGENTS/test-layout changes; incorporated PR76's Notification
  root-env/database wiring, PR80's repo-root cross-service e2e layout, and newer
  Event draft/integration work. Used `git merge --no-commit origin/main`.
- Final merge commit: **`ba65c627701c23c0d514e743ad1fb1f7d48d4895`**,
  `SCRUM-45: merge latest main and align cross-service e2e layout`.
  Its parents are the starting HEAD and fetched main above. A later documentation
  commit records this evidence; it is not another main merge.
- Only textual conflict: Event `pyproject.toml` coverage floor, 99.11 vs main's
  98.76. Kept **99.11** (measured merged result 99.22%). Retained main's new
  testcontainers dependency/lock and all auto-merged application changes.

## Resolutions and actual RED → GREEN

- Moved the entire SCRUM-45 multi-service harness from Event Workflow's
  `tests/integration/` to **`e2e/scrum45/`**. Updated helper imports, repository-root
  calculation, fixture registration and hermetic cleanup-test imports; added the
  repository root to that service's pytest import path. Repo e2e no longer uses
  service `integration`/socket markers or service coverage settings. Single-service
  integration and live Supabase tests were not selected accidentally.
- Kept main's Notification API/consumer root configuration: no notification-specific
  env file is required by Compose. All ignored manual `.env` files, including the
  user's Notification file, were preserved. Event's existing service DB precedence
  and required root token remain intact; SCRUM-45's event dispatcher is retained.
- Full backend first run genuinely failed the existing TERM-ignoring-child cleanup
  case: macOS intermittently returned **EPERM from `killpg(group, 0)` after KILL**.
  Instrumentation reproduced it on the second repeat with no group in the following
  `ps` snapshot. Added transient-denial and persistent-denial tests: **2 failed /
  4 deselected** before the fix. Minimal fix polls EPERM within the existing bound;
  **only ESRCH proves absence**. All six cleanup cases passed **20 consecutive
  runs**. A mutant treating EPERM as success was killed by the persistent-denial
  assertion (**1 failed / 1 passed / 4 deselected**); restored bytes match the commit.
- Full frontend first run: **730 tests passed but one suite failed collection**:
  Vitest discovered `node:test`'s `e2e-real/journey-lifecycle.test.mjs` and reported
  “No test suite found.” Excluded that separate Node tier from Vitest and chained
  `node --test e2e-real/*.test.mjs` into **both** normal and coverage npm scripts,
  so the lifecycle regressions are executed, not silently dropped. No application
  behaviour was changed or artificial missing-feature RED manufactured.
- Removed one inherited trailing space in the newly merged testing guide.

## Verification on restored merged code

Raw logs, config/probe helpers and browser artifacts:
`/Users/daphnetok/.hermes/verification/scrum45-main-sync-20261023/`.
All final gates below exited **0**; initial RED/mutation logs remain separately.

| Gate | Actual result | Evidence |
|---|---|---|
| Root `npm run test:backend`, sanitized env / dotenv disabled | **2,608 passed across 17 services**, **61 deselected**; all configured coverage floors met | `scrum45-main-backend-green.log` |
| Event / Event Workflow / Notification, included above | **566 / 99 / 97 passed**; **99.22% / 100% / 100%** coverage | same |
| Owned-process cleanup, focused no-cov repeat | **6 passed × 20 runs**; restored focused check also 6 passed | `scrum45-main-cleanup-green.log` |
| Entire opt-in `e2e/scrum45` | **26 passed**, no skips or teardown errors, **226.83s**; earlier full post-layout run also 26 passed | `scrum45-main-e2e-final.log` |
| Real browser, included in those 26 | Lead rejection → real Event/DB/outbox/worker/broker/consumer → organiser inbox → linked rejection/read persistence; **zero browser/request errors**, all recorded responses 200 | `e2e-final/test_lead_rejection_reaches_or0/` |
| UI `npm run test:coverage` | Vitest **730 passed / 59 files** plus Node lifecycle **4 passed / 0 failed** | `scrum45-main-frontend-green.log` |
| Complete mocked Playwright suite, dynamic-port scratch config | **73 expected / 0 unexpected / 0 flaky / 0 skipped** | `tools/mocked.json` |
| UI `npm run build`; `npm run lint` | Both pass; lint **0 errors / 4 warnings** | `scrum45-main-build-final.log`, `scrum45-main-lint-final.log` |
| `docker compose config --quiet` | Effective manual configuration valid, no secrets rendered | terminal |
| `python3 -m unittest discover -s scripts -p test_notification_compose_config.py -v` | **8 passed** | terminal |
| `git diff --check`; main ancestry | Clean; `git merge-base --is-ancestor origin/main HEAD` exit 0 | terminal |
| Resource readback | No `scrum45-` containers remain; all **18 original `is212-g7t4-*` containers** still Up 44 hours | terminal |

Reproduction (from this repository root; `clean` deliberately does not inherit
shared DB/broker credentials):

```sh
clean() {
  env -i HOME="$HOME" PATH="$PATH" \
    TMPDIR=/Users/daphnetok/.hermes/cache/scratch \
    PYTHON_DOTENV_DISABLED=1 FLASK_SKIP_DOTENV=1 "$@"
}
clean npm run test:backend
clean uv run --no-project --with pytest --with httpx --with psycopg2-binary \
  python -m pytest e2e/scrum45 --tb=short -ra \
  --basetemp=/Users/daphnetok/.hermes/cache/scratch/scrum45-main-e2e-rerun
(cd frontend/event-management-ui && clean npm run test:coverage && \
  clean npm run build && clean npm run lint)
# Actual full mocked-browser command, after installing frontend deps:
(cd frontend/event-management-ui && clean node node_modules/@playwright/test/cli.js \
  test --config /Users/daphnetok/.hermes/cache/scratch/scrum45-main-tools/mocked.config.ts)
```

The mocked config is a full copy of the repository Playwright config, adjusted
only for absolute paths, an unused UI port, external outputs and empty Vite
`envDir`; no manual server is reused. Its copy is retained under `tools/` in the
artifact directory. Default `npm run test:e2e` uses fixed 5174, so was not used to
compete with the user's manual stack. Both browser tiers use existing Chromium.

## Shared DEVELOPMENT schema and remaining limits

A read-only transaction against the effective Compose Event DSN confirmed it is
identical to Notification's DSN. Root notification dev mode is enabled. Existing
`Notification`, `NotificationFailure`, `VenueNotificationOutbox` are installed;
**`EventNotificationOutbox` is missing**. Migration history contains the eight
baseline-through-`20261017000001` versions and none of the SCRUM-45 versions.
`tools/shared-schema.log` records schema names/columns only, no credentials or
personal rows. **Team-authorised application of `20261021000000`,
`20261021000100`, `20261021020000` remains the manual delivery prerequisite.**
No migration was applied and no shared delivery was attempted.

- The 61 deselections are Event's 60 new single-service integration cases and
  Venue Availability's one live case. They were **not run or claimed green**.
  SCRUM-45's 26 separate repo-e2e cases were all run; unrelated repo e2e was not.
- SCRUM-45 e2e keeps its existing owner-specific migration-derived schema, not
  the full unrelated monorepo migration chain. Four migration-order cases pass.
- Browser real-delivery coverage is **one rejection journey**, not every approval
  and reassignment combination. Those have real backend and mocked browser tests.
  This is a headless local-process test, not a successful Compose deployment,
  production auth test, or SLA. The existing Google Fonts resource can load online.
- UI coverage remains the configured calendar/venue scope: **98.1% statements /
  92.4% branches / 96.6% functions / 98.76% lines**, not whole-app coverage.
  Existing backend gaps remain; no coverage floor was lowered.
- Four lint warnings remain: three Fast Refresh exports in `ClosureDetails.tsx`
  and one `no-unsafe-finally` warning in the existing browser lifecycle helper.
  `npm ci` reported **3 moderate vulnerabilities**, no high/critical; dependency
  remediation was not undertaken. Its fsevents install-script approval warning
  is separate from the successful tests/build.
- `gh` is unavailable on this host. Git fetch/ancestry verification succeeded;
  remote CI, PR creation, review and ticket closure are not claimed.
- Shared-development startup awaits schema approval and port/worker ownership
  handover. Persistent manual Supabase data is **not** disposable automated data.
