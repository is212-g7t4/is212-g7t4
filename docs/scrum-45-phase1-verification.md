# SCRUM-45 Phase 1 verification

## Decision

Phase 1 isolated verification passed, including independent Standards and Spec reviews with no blocking findings in scope. This is NOT approval to change shared Supabase, deploy, commit, push or merge. Existing calendar, booking-approval, legacy permission and malformed-notification-timestamp findings remain open outside this SCRUM-45 verification scope.

## Exact tested state

Validation worktree: `/Users/daphnetok/.hermes/cache/scratch/scrum45-phase1`.
Base SCRUM-45 revision: `58f3986`; fetched main: `eb41a2b`.
Main was merged with `--no-commit` into the detached validation worktree. Conflicts were resolved there; the merge has NOT been committed or transferred to the original working branch. Original checkout received only the requested notification testing guide and this report.

## Actual results

| Check | Result |
|---|---|
| Root backend unit command | 2,672 passed; 91 deselected; 17 directories (15 services and 2 templates) |
| Configured backend coverage gates | Passed unchanged; Event 99.34% against retained 99.11% floor; Event Workflow and Notification 100% |
| Frontend Vitest | 750 passed across 62 files |
| Node browser lifecycle | 4 passed |
| Selected mocked notification Playwright | 8 passed; no retries/skips |
| Existing real SCRUM-45 acceptance | 26 passed, including an unmocked browser journey |
| Added full migration verification | 5 passed on PostgreSQL 17.6 |
| TypeScript + frontend production build | Passed |
| Lint | Exit 0; 5 warnings remain |
| Independent Standards / Spec reviews | No blocking findings in reviewed scope |

Equipment Request and Equipment Reservation still have no configured coverage gate; this run did not add one. Unit deselections are not passing integrations. No whole-application frontend coverage claim is made.

## Changes prepared in validation worktree

- Resolve OrganiserEventDetailPage merge while preserving both SCRUM-45 rejection details and main's change-request UI.
- Resolve Event pyproject conflict without lowering SCRUM-45's stronger coverage floor.
- Correct Event Workflow README's acceptance invocation and prerequisites.
- Add `e2e/scrum45/migration_helpers.py` and `test_migrations.py`.
- Add the requested `services/notification-service/TESTING_GUIDE.md` (also present in original checkout).

No migration SQL edits or additional application bug fixes were required in this scope.

## What migration tests prove

All 12 SQL files were applied in full without rewriting/filtering. Scenarios cover clean install, populated pre-SCRUM45 upgrade, rejection-only upgrade, latest-main installation followed by the three pending backdated SCRUM-45 migrations, and explicitly limited Supabase-like roles.

Tests verify schema/types, all supported notification types, invalid-type rejection, held_at timezone behaviour, indexes/RLS and preservation of every preexisting column value/row count in populated tables. Synthetic role checks do not establish actual hosted Supabase configuration, live data compatibility or the deployment tool's migration-ledger policy.

## Evidence and caveats

Raw logs: `/Users/daphnetok/.hermes/cache/scratch/scrum45-phase1-evidence/` under `backend/`, `frontend/`, `migrations/`.

- Backend `all-backend-root.log`, `unit-counts.json`, `acceptance-original.log`, `cleanup-readback.json`.
- Frontend `full-tests.log`, `build.log`, `lint.log`, `browser.json`.
- Migrations `pytest-final.log`, `junit.xml`, `metadata.json`, sensitivity logs.

An initial synthetic nonempty internal token caused 18 existing main change-request unit tests to fail because they assume default token configuration. The final no-secrets default run passed without code/assertion changes; the initial log is retained. Do not interpret the first runner's exit code alone as proof all its tests passed.

Temporary wrong-expected-value checks exercised assertions in migration tests; these are NOT evidence of a discovered migration defect, a production mutation test or a new RED/GREEN fix cycle.

Owned test processes/containers and migration volumes were checked absent after completion. Shared manual stack and Supabase were untouched. The successful main-sync validation does not fix previously reported unrelated release defects.

## Review checkpoint / next actions

Stop here for user review. Before later rollout, integrate the tested changes deliberately, preserve the exact tested baseline, coordinate team review, recheck actual shared schema, and apply only approved missing migrations using the team's migration process. Then coordinate worker/stack ownership and perform manual acceptance. No later-phase actions were executed.
