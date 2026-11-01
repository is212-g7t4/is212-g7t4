# SCRUM-49 inherited migration-test maintenance

Base: `SCRUM-49-event-change-and-modification-notifications`,
`ec07017dead0a42ae7cfb4a84629e9f5226c472e`.

## Repair and boundary

- `disposable_database` (exposed by `migration_database`) always creates synthetic
  `NOLOGIN` roles `anon`, `authenticated`, and `service_role` (`BYPASSRLS`). Current
  unmodified migrations name these roles in `REVOKE` statements, so their existence
  is a migration prerequisite, not an optional hosted-platform simulation.
- Only `bootstrap=True` installs schema usage and default table/sequence grants.
  Two parameterized infrastructure cases independently check role attributes and
  the presence/absence of Event outbox table privileges in the two modes. Existing
  owner/BYPASSRLS/client-role access tests still exercise grants separately from RLS.
- Full-chain inventories in both migration test modules add
  `EquipmentNotificationOutbox` only. This branch has no
  `RegistrationNotificationOutbox` migration. Approval/assignment intermediate
  checks explicitly retain the original historical inventory; they must not expect
  a table created by a later migration.
- Exact table/RLS equality, column types, allowed/rejected notification types,
  indexes, seeded-row preservation and privilege checks remain enforced.

Real: disposable loopback-bound PostgreSQL 17.6, unmodified migrations, and the
Event integration tier's normal Flask/SQL paths. Synthetic SQL roles/default
privileges do not prove hosted Supabase authentication or platform parity. No
production code, migrations, RBAC business rules, CI, coverage floors, skips,
shared database, dotenv files, manual stack or frontend were changed.

## Observed verification

| Step | Actual result |
| --- | --- |
| Original entire Event integration tier | **11 failed, 167 passed**, 816 deselected: ten missing-role failures and one stale Equipment inventory |
| New roles/grants regression before fixture repair | **1 failed, 1 passed**; roles-only case failed its role-inventory assertion |
| Roles repaired, inventories still unchanged (focused migration tests) | **7 failed, 7 passed**; exposed seven stale Equipment inventory assertions, not additional application failures |
| Complete focused migration repair | **14 passed** |
| Final normal Event unit tier | **816 passed**, 180 deselected; **100.00% line/branch coverage**, unchanged 100% floor |
| Final entire Event integration tier after probe restoration | **180 passed**, 816 deselected |

No final failures, errors, skips or xfails. Two new parameterized cases account
for the integration count increasing from 178 to 180.

Assertion sensitivity followed integration guide §6 step 5: seven temporary
wrong-expectation probes caused nine genuine **failed assertions**, zero setup
errors: current table/RLS expectations in both modules, historical-stage table
inventory, role attributes in both modes, and default-grant expectations in both
modes. Each source file was restored byte-for-byte, checked by SHA-256, before
final full-tier runs. No deliberately wrong expectation remains.

All 69 Event Python/config/lock and migration source hashes were identical before
and after final verification. All 87 owned containers and 87 owned volumes named
in these runs' logs were independently confirmed absent; all 55 pre-existing
container IDs remained. The pre-existing dirty `.DS_Store` hash was unchanged.
No commit, staging, push, branch switch or merge was performed.

## Reproduce safely

From `services/event-service`, with Docker available (do not restart the manual
stack), use an allowlisted environment to exclude shared connection settings and
disable dotenv before imports. Keep coverage and reports outside the checkout:

```bash
EVIDENCE="$HOME/.hermes/cache/scratch/scrum49-test-maintenance"
mkdir -p "$EVIDENCE"
env -i HOME="$HOME" PATH="$PATH" TMPDIR="$TMPDIR" \
  PYTHON_DOTENV_DISABLED=1 TESTCONTAINERS_RYUK_DISABLED=true \
  COVERAGE_FILE="$EVIDENCE/replay-unit.coverage" \
  uv run --locked pytest --junitxml="$EVIDENCE/replay-unit.xml"
env -i HOME="$HOME" PATH="$PATH" TMPDIR="$TMPDIR" \
  PYTHON_DOTENV_DISABLED=1 TESTCONTAINERS_RYUK_DISABLED=true \
  uv run --locked pytest -m integration --no-cov -s \
  --junitxml="$EVIDENCE/replay-integration.xml"
```

Actual run commands, full logs, JUnit, baseline/verified SHA-256 manifests,
probe results and resource inventories are under
`~/.hermes/cache/scratch/scrum49-test-maintenance/`. Its `run.py` wraps
`uv run --locked pytest` in the allowlisted environment and captures reports;
`unit-green` used normal pytest defaults and `integration-green` added
`-m integration --no-cov -s`. Focused verification selected
`tests/integration/test_infra_migrations.py`, including
`test_submission_migration_upgrades_current_main_without_changing_existing_rows`.
These automated runs did not migrate any shared development database.
