# SCRUM-48: Equipment Request owner tests

## Story and acceptance criteria

Technical Support Staff and Event Coordinators receive equipment alerts so they
can coordinate equipment arrangements. The original three criteria stay unchanged:

- **AC1:** A submission alert identifies the event and the full submitted list.
- **AC2:** An approval alert identifies the event, equipment and requested quantity.
- **AC3:** A rejection alert contains those facts but not the workflow rejection reason.

`DR` in a test means a supporting design rule, not a fourth acceptance criterion.
Each test explains what it arranges, does and checks. Each gets fresh test data,
Flask client and database connection/cursor doubles.

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
models and outbox construction. The older `test_equipment_requests.py` remains
in its original location and continues to check the pre-existing request API.

| Area | What the new tests check |
| --- | --- |
| Submission / AC1 | One frozen full-list SQL intent per unique eligible TSS, not per equipment unit; no invented recipient when the eligible list is empty. |
| Decisions / AC2–AC3 | One reason-free alert per changed request record for single and bulk reviews; exact event, item, quantity, recipient and destination. |
| Failed and no-op actions | Missing/already-decided requests create no alert intent; safety reset to Pending is not a new decision alert. |
| Transaction failure | Failure on the first or a later outbox INSERT exits the same owner transaction with an exception and closes the connection. Mocked INSERT RETURNING rows are Pending; review UPDATE RETURNING rows are Approved, matching the SQL contract. |
| Trusted context | Wrong/missing token, malformed names/UUIDs and mismatched event context are rejected; role headers cannot authenticate the worker APIs. |
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

The normal whole-owner run now passes the unchanged **100** floor with
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
The default suite deselects all 66 cases, with no Docker calls.

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
