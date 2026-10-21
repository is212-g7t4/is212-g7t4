# SCRUM-45 final review resolution

October 21, 2026 — `SCRUM-45-review-refinements`, based on `728dbbd`.
Scope: the two P3 review findings only; behavior-preserving REFACTOR.

## Disposition

- **Standards P3 — resolved:** the Event Workflow runner regression now patches
  only `subprocess.run` and `time.sleep`; real `run` → `attempt` executes.
  Assertions cover timeout and nonempty child failure, exponential backoff,
  exit-code-3 empty polling, reset after empty/success, no sleep on success,
  clean interruption, and bounded child invocation. Story/DR3 docstrings remain.
- **Judgement P3 — resolved:** one Event-local `_record_notification` helper
  consolidates recipient diagnosis, saved source facts and outbox insertion for
  approval, rejection and coordinator assignment. Each caller passes its existing
  cursor; event mutation and intent retain the same transaction and rollback.
  Message types, source fields and rendered legacy diagnostics are unchanged.
  No shared/cross-service library or new outward calls.
- Existing full suites were GREEN before edits. The runner-test-only change was
  verified GREEN before the production refactor. No behavior bug surfaced; no
  feature RED, fabricated failure or speculative behavior is claimed.

## Actual commands and results

All commands exited 0. Paths are relative to this checkout unless absolute.

| Working directory / command | Before edits | After edits |
| --- | --- | --- |
| `services/event-service`: `uv run pytest` | 532 passed; 99.12% | 532 passed; 99.11%, existing 99.11% gate met |
| `services/event-workflow-service`: `uv run pytest` | 87 passed, 20 integration deselected; 100% | 87 passed, 20 integration deselected; 100% (also passed after test-only edit) |
| `services/notification-service`: `uv run pytest` | 97 passed; 100% | 97 passed; 100% |

Integration prerequisite: `services/user-service`: `uv sync --locked` prepared
its ignored local virtualenv without changing dependency files.

From `services/event-workflow-service`:

```sh
uv run --with psycopg2-binary python -m pytest -m integration --no-cov --tb=short --basetemp=/Users/daphnetok/.hermes/cache/scratch/scrum45-review-integration
```

**20 passed, 87 unit deselected, 0 failures/skips**, 179.33s: approval 4,
combined/migrations 5, initial assignment 5, reassignment 2, rejection 4.
The entire real isolated suite ran: disposable UUID-named PostgreSQL/RabbitMQ,
separate owner databases, real Event/User/Notification HTTP, worker and consumer,
allowlisted subprocess environments and dotenv disabled; no production database.
`docker ps -a --filter name=scrum45- --format '{{.Names}}'` returned no rows
after fixture cleanup. Worktrees were not removed.

Root `git diff --check` passed. Root
`git merge --no-edit SCRUM-45-event-organiser-status-and-update-notifications`
returned **Already up to date**: latest local integration tip
`728dbbdfd7a421c83a67eada378e375184ddda4d` is already an ancestor, confirmed by
`git merge-base --is-ancestor SCRUM-45-event-organiser-status-and-update-notifications HEAD`.

Raw baseline/post/test-only/integration logs are outside Git at
`/Users/daphnetok/.hermes/artifacts/scrum45-review/`; service subprocess logs
remain in the explicit scratch basetemp above.

No remaining issue encountered within this scope. No push, ticket closure,
worktree cleanup, unrelated fixes or new browser-verification claim.
