# SCRUM-48: Equipment Request owner tests

## Story and acceptance criteria

As an Event Coordinator and Technical Support Staff, I want to receive
notifications about equipment requests and decisions, so that I can coordinate
equipment arrangements efficiently. (Copied from Jira; each test file's module
docstring carries the full story and ACs.)

- **AC1:** Given an Event Coordinator submits an equipment request, the system sends an in-app notification to Technical Support Staff with the event name, requested equipment list, and a link to review the request.
- **AC2:** Given equipment is confirmed as available or found to be unavailable, the system sends an in-app notification to the Event Coordinator with the event name, equipment list, and availability status.
- **AC3:** Given an equipment request is submitted and pending review, the system sends an in-app notification to Technical Support Staff that a request requires their review.

Tests follow the repo's unit test convention: each has a Summary, the AC it
checks (or `AC MISSING` for supporting rules no AC states, such as outbox
leasing), and the test double it uses. Each gets fresh test data, Flask client
and database connection/cursor doubles.

## What runs

From `services/equipment-request-service`:

```sh
uv run pytest
```

Settings in `pyproject.toml` measure every file in `app`, including branches.
The default run excludes the `integration` marker. `tests/conftest.py` disables
dotenv loading and rejects accidental Python network connections and native
`psycopg2.connect` calls. A test must replace its external adapters explicitly.
There is no shared database, broker, migration or worker in this suite.

## Where to read

`unit/test_scrum48_notifications.py` uses the real HTTP routes, validation,
models and outbox construction. The request API itself is covered per story in
`unit/test_scrum32_create_equipment_request.py`,
`unit/test_equipment_request_review.py` and
`unit/test_equipment_safety_reset.py`.

| Area | What the new tests check |
| --- | --- |
| Submission / AC1 | One frozen full-list SQL intent per unique eligible TSS, not per equipment unit; no invented recipient when the eligible list is empty. |
| Decisions / AC2 | One reason-free alert per changed request record for single and bulk reviews; exact event, item, quantity, recipient and destination. |
| Failed and no-op actions | Missing/already-decided requests create no alert intent; safety reset to Pending is not a new decision alert. |
| Transaction failure | Failure on the first or a later outbox INSERT exits the same owner transaction with an exception and closes the connection. Mocked INSERT RETURNING rows are Pending; review UPDATE RETURNING rows are Approved, matching the SQL contract. |
| Context validation / worker access | Notification-context names/UUIDs and event matching are validated. Worker API tests cover wrong/missing internal tokens and forged role headers; these do not establish approval-input provenance. |
| Worker API | Claim SQL eligibility/locking intent, empty claim, safe failures, lost/expired leases, freeze-before-published, retry delay cap and error truncation. |

## Limits and strict coverage

These are mocked unit tests. Seeing a SQL INSERT or an exceptional transaction
exit is **not** independent proof that PostgreSQL saved or rolled back data.
Eligibility SQL is not proof of concurrent row locking.

The approved minimal refactor removes only the redundant decision-status skip
from `record_decisions`: both HTTP review routes admit Approved/Rejected only,
and both owning model updates assign that status before `RETURNING`. Those are
the only callers; safety reset does not call the recorder. Route validation,
Pending-only SQL, event/name snapshot checks, missing-coordinator behavior and
worker lease/freeze/authentication guards remain intact. Existing invalid-status
and safety-reset regressions are retained; no impossible cursor row or direct
helper test was added for coverage.

Historical pre-allocation-refactor evidence: the then-current whole-owner run passed the unchanged **100** floor with
**423/423 executable lines and 146/146 branch outcomes**, no excluded lines.
Before the refactor all 153 tests passed but the strict coverage gate failed
at 424/425 lines and 147/148 branches. This is measured pre/post refactoring
regression evidence, not historical feature RED/GREEN evidence.

## Opt-in owner-only PostgreSQL integration

`integration/test_scrum48_transactions.py` (20 cases) and
`integration/test_scrum48_claims_permissions.py` (46 cases) execute only this
owner's production code plus disposable PostgreSQL. They prove first/later INSERT
rollback, atomic visibility, bulk/no-op behavior, claim/expiry/lock fencing and
ACL/RLS using independent fresh SQL observations. Their service-local conftest
starts one UUID-labelled loopback/tmpfs PostgreSQL container; each case owns a
fresh database. No other service, broker, consumer, dispatcher, HTTP proxy or
multi-owner loader is imported/started. Native libpq routing is allowlisted and
Python sockets denied; inherited PG routing/DSNs are cleared and dotenv disabled.
Those two original modules contained 66 cases. The current reorganisation collects 91 owner integration cases (including the moved allocation regressions); the normal unit run deselects all 91, with no Docker calls.

From this directory, only when deliberately opting in:

```sh
PYTHON_DOTENV_DISABLED=1 uv run --no-env-file --locked --python 3.12 pytest -m integration --no-cov tests/integration
```

Docker needs the pinned PostgreSQL digest already installed (`--pull=never`).
Missing image is a blocker; never prune Docker or point at shared Supabase.
Cleanup checks each database absent, deletes only the matching labelled container,
checks it absent and verifies all pre-existing containers unchanged. SIGKILL can
prevent teardown. Selected baseline FK tables are inert scaffolding, not other
services or a full migration chain; hosted ACL parity/power-loss/AMQP is not proved.

All new cross-service tests were removed after verified external archive, not
renamed into this service. The historical 80-case PG/MQ chain belongs only to
that handover. See the [Reservation test guide](../../equipment-reservation-service/tests/README.md)
for the separate composite boundary and its known snapshot timing limitation.

## Issues 6/7/8: current story-based layout

See [the equipment regression map](../../../docs/testing/equipment-regressions.md)
for the agreed SCRUM-35 revision, SCRUM-151 AC2/SCRUM-164 AC3, exact test
ownership, verified commands and remaining blockers. Jira synchronization is
not confirmed; revised headers say so explicitly.

- `unit/test_equipment_reservation.py`: SCRUM-35, 28 unit cases.
- `unit/test_equipment_availability.py`: SCRUM-34, 2 unit cases.
- `unit/test_equipment_request_review.py`: SCRUM-33, 40 unit cases.
- `unit/test_equipment_safety_reset.py`: SCRUM-164, 14 existing unit cases,
  **not** the absent PR115 Approved-only preservation regressions.
- Review authentication is in `unit/test_authentication.py`; reset modification
  authority is in `unit/test_safety_reset_modification_access.py`.
- `integration/test_equipment_reservation.py`: SCRUM-35, 19 collected cases.
- `integration/test_equipment_availability.py`: SCRUM-34, 1 collected case.
- `integration/test_equipment_review_modification_access.py`: SCRUM-10,
  4 collected cases. Outbox rollback stays under SCRUM-48 in the existing
  `integration/test_scrum48_transactions.py` (now 21 collected cases).

Current whole-owner unit result: **233 passed**, 91 integration cases
deselected; **563/563 executable statements, 206/206 branch outcomes**,
unchanged 100% gate. Focused reverse node order: **115 passed**.
Integration collection succeeded, but database execution/reverse execution is
blocked: unrelated `backend-ngrok-1` is auto-restarting and would invalidate
the fixture's unchanged pre-existing-container guard. No shared container was
stopped or changed. The pinned PostgreSQL image is available.

PR115 is merged in cached `origin/main`, but this local HEAD predates it;
the Approved-only reset predicate and `integration/test_equipment_safety_reset.py`
are absent here. This is an older checkout, not a lost merged fix. See the
[cached ancestry evidence](../../../docs/testing/equipment-regressions.md#blockers-and-evidence-limits).
No fetch, integration or production change was made by this documentation update.
