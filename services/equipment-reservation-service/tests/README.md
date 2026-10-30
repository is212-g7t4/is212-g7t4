# SCRUM-48: Equipment Reservation single-service contract tests

## Story and acceptance criteria (copied from Jira)

As an Event Coordinator and Technical Support Staff, I want to receive
notifications about equipment requests and decisions, so that I can coordinate
equipment arrangements efficiently.

- **AC1:** Given an Event Coordinator submits an equipment request, the system sends an in-app notification to Technical Support Staff with the event name, requested equipment list, and a link to review the request.
- **AC2:** Given equipment is confirmed as available or found to be unavailable, the system sends an in-app notification to the Event Coordinator with the event name, equipment list, and availability status.
- **AC3:** Given an equipment request is submitted and pending review, the system sends an in-app notification to Technical Support Staff that a request requires their review.

At this service boundary the tests check that a submission carries the full
list and every Technical Support recipient (AC1, AC3), and that a decision goes
to the event's current coordinator without the private rejection reason (AC2).

These are not connected delivery tests. The Request owner separately tests exact
full-list/per-changed-record, reason-free frozen envelopes. Notification separately
tests accepting those envelopes at its public process seam. Bulk, validation,
security, retry and isolation are supporting design rules, not extra ACs.

## Run and test map

```sh
# From services/equipment-reservation-service
PYTHON_DOTENV_DISABLED=1 uv run --no-env-file --locked --python 3.12 pytest
```

The normal service command retains whole-app branch/source measurement and its
strict 100 gate, zero exclusions.
Every external service/AMQP/subprocess boundary is doubled; sockets are blocked
and dotenv disabled. There is no DB driver/dotenv test dependency just to load
another owner. The production dispatcher still legitimately depends on pika.

| File under tests/unit | Behavior and boundary |
|---|---|
| `test_equipment_notifications.py` | Exactly three original AC contract scenarios through real local routes/adapters to HTTP doubles |
| `factories.py` | Fresh synthetic HTTP responses and call log only; no SQL, inbox/outbox emulator, delivery drain, app loader or sys.modules swapping |
| `test_scrum48_p0_side_effects.py` | One bulk PATCH preserves owner-reported result; downstream refusal is propagated; insufficient stock prevents mutation; malformed reason is rejected before HTTP; forged public context/token is discarded |
| `test_scrum48_snapshot_security.py` | Trusted context/token selection; TSS spellings/deduplication/empty recipients; malformed event/missing configuration/upstream outage prevents write |
| `test_scrum48_dispatch_reliability.py` | Only local dispatcher/publisher code; owner HTTP/AMQP/process doubles check frozen identity, publish-before-finalize, safe failure/retry/backoff/CLI/subprocess contract |

Older service tests remain in their original locations. No test imports another
test module or another service's production package. The original cross-service
support and its SQL/broker/inbox doubles were externally archived and removed;
this is a boundary rewrite, not merely relabeling that harness.

## Limits / separate scope

A doubled HTTP result does not prove remote Pending-only writes, rollback or
per-record durable alerts. Those owner rules are independently unit-tested and
66 real PostgreSQL cases live only in Equipment Request's integration folder.
Requested AMQP confirm/durability flags do not prove broker acceptance or delivery;
subprocess doubles do not prove real OS child kill/reap. No production worker runs.
Additional Notification PG tests were not duplicated; existing owner-local storage
contracts are retained, without claiming connected live transport.

Recipient is the latest pre-write Event snapshot, not an assignee locked at owner
commit. Reassignment can race; frozen retries preserve the captured recipient,
not repair that race. No browser journey or shared-stack verification is added.
Frontend mocked component tests remain separate. Historical chain-test evidence
is handed off outside the branch. See the
[Request owner test guide](../../equipment-request-service/tests/README.md)
for the separate disposable PostgreSQL boundary.
