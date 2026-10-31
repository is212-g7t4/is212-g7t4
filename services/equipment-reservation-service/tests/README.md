# SCRUM-48: Equipment Reservation single-service contract tests

## Story and acceptance criteria (copied from Jira)

As an Event Coordinator and Technical Support Staff, I want to receive
notifications about equipment requests and decisions, so that I can coordinate
equipment arrangements efficiently.

- **AC1:** Given an Event Coordinator submits an equipment request, the system sends an in-app notification to Technical Support Staff with the event name, requested equipment list, and a link to review the request.
- **AC2:** Given Technical Support Staff approves or rejects an Equipment Request, the system sends an in-app notification to the Event Coordinator assigned to that event with the event name, the equipment covered by the decision, and the decision status (Approved or Rejected).
- **AC3:** Given a Technical Support Staff rejects the equipment request, the system sends an in-app notification to the Event Coordinator with the rejection message, event name, equipment request and link to the equipment request.

At this service boundary the tests check that a submission carries the full
list and every Technical Support recipient (AC1), and that an Approved/Rejected
decision goes to the event's current coordinator (AC2). Rejection-specific
context supports AC3: the rejection message states that the Equipment Request
was rejected, not that the event was rejected and not why. The private
`rejectionReason` stays in the review workflow, outside notification content.
These HTTP doubles do not assert the owner-generated rejection message or
prove delivery; the Request unit case checks its exact reason-free message.

These are not connected delivery tests. The Request owner separately tests exact
full-list/per-changed-record, reason-free frozen envelopes. Notification separately
tests accepting those envelopes at its public process seam. Bulk, validation,
security, retry and isolation are supporting design rules, not extra ACs.

## Run and test map

```sh
# From services/equipment-reservation-service
env -u PYTHONPATH PYTHON_DOTENV_DISABLED=1 uv run --no-env-file --locked --python 3.12 python -m pytest
```

The normal service command retains whole-app branch/source measurement and its
strict 100 gate, zero exclusions.
Every external service/AMQP/subprocess boundary is doubled; sockets are blocked
and dotenv disabled. There is no DB driver/dotenv test dependency just to load
another owner. The production dispatcher still legitimately depends on pika.

| File under tests/unit | Behavior and boundary |
|---|---|
| `test_scrum48_request_submission_and_decision_notifications.py` | Submission and review actions: the three original AC scenarios plus bulk result/refusal, insufficient-stock and forged-context checks; real local routes/adapters with the same HTTP boundary fixture |
| `test_scrum48_notification_context_validation.py` | Trusted upstream context: context/token selection; TSS spellings/deduplication/empty recipients; malformed event/missing configuration/upstream outage prevents write |
| `test_scrum48_notification_delivery_and_retries.py` | Background delivery and retries: only local dispatcher/publisher code; owner HTTP/AMQP/process doubles check frozen identity, publish-before-finalize, safe failure/retry/backoff/CLI/subprocess contract |
| `factories.py` | Fresh synthetic HTTP responses and call log only; no SQL, inbox/outbox emulator, delivery drain, app loader or sys.modules swapping |

Notification suites retain their existing locations; equipment review, availability and reservation tests now use feature filenames (see the current map below). No test imports another
test module or another service's production package. The original cross-service
support and its SQL/broker/inbox doubles were externally archived and removed;
this is a boundary rewrite, not merely relabeling that harness.

## Limits / separate scope

A doubled HTTP result does not prove remote Pending-only writes, rollback or
per-record durable alerts. Those owner rules are independently unit-tested and
the Equipment Request integration tier owns those PostgreSQL checks; this audit does not execute that separate service.
Requested AMQP confirm/durability flags do not prove broker acceptance or delivery;
subprocess doubles do not prove real OS child kill/reap. No production worker runs.
Additional Notification PG tests were not duplicated; existing owner-local storage
contracts are retained, without claiming connected live transport.

Recipient is the latest pre-write Event snapshot, not an assignee locked at owner
commit. Reassignment can race; frozen retries preserve the captured recipient,
not repair that race. No browser journey or shared-stack verification is added.
Frontend mocked component tests remain separate. Historical chain-test evidence
is handed off outside the branch. See the
[Request owner test guide](../../equipment-request-service/README.md)
for the separate disposable PostgreSQL boundary.

Current consolidation verification: **213 unit cases**, all passing in normal and
exact reverse order at 100% statements and branches. The three SCRUM-48 modules
retain all 48 collected cases (8 submission/decision, 12 context-validation and
28 delivery/retry cases); only their file locations and module explanations changed.

The existing two-line review projection
checks nonempty equipment names, types, quantities and technical instructions.
SCRUM-48 AC2 specifies Approved/Rejected decisions, not availability status.
AC3 applies only to rejection parameters in mixed decision tests, never approval
or submission. Worker retry/lease/security checks are supporting contracts, not
complete acceptance-criterion delivery evidence.

## Issues 6/7/8: current story-based layout

See [the equipment regression map](../../../docs/testing/equipment-regressions.md).

| Feature file under `tests/unit/` | Primary story | Historical cases before this audit |
| --- | --- | ---: |
| `test_scrum35_equipment_reservation.py` | SCRUM-35 current Jira requirements | 32 |
| `test_scrum34_equipment_availability.py` | SCRUM-34 unavailable-item filtering | 7 |
| `test_scrum33_equipment_request_review.py` | SCRUM-33 review/status compatibility | 34 |
| `test_scrum9_equipment_review_access.py` | SCRUM-9 assignment-based visibility | 5 |

Authentication/token propagation moved to the existing
`test_scrum8_equipment_authentication.py` (SCRUM-8). Notification cases remain SCRUM-48.
`test_scrum35_equipment_reservation.py` consolidates the former SCRUM-35 module,
new overallocation regressions and stock-sensitive approval cases formerly
in the review module. No assertions or parametrized inputs were removed.

The whole-composite unit command retains the unchanged 100% statement and branch
coverage gate. The token clock is fixed and expiry is checked immediately before,
at and after its deadline. All other service, broker and child-process boundaries
are doubled. This service has no HTTP-boundary integration tier, so these tests
do not prove real downstream acceptance, owner SQL persistence or concurrency.

The malformed rejection-reason check now lives with SCRUM-33 review validation;
health/CORS checks live in `test_infra_equipment_reservation_service.py`.
Unexpected downstream errors are mapped to a generic 502 message rather than
exposing downstream detail; the regression asserts both status and redacted
message. Recognised pass-through errors retain their existing public contract.
