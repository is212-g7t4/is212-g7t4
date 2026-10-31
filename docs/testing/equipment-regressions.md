# Equipment regressions: issues 6/7/8

**Current owner-test update (October 31, 2026):** read-only live Jira captures
now confirm the story text; current owner test headers use the exact captured
wording, including SCRUM-35 AC3. Owner paths below follow the ticket-bearing
renames. Equipment Request now passes 233 unit / 105 integration cases in both
normal and exact reverse order; original 333 cases retained, 5 integrations added.
See the [owner service README](../../services/equipment-request-service/README.md)
and [integration guide](integration-testing.md) for ownership limits and test commands. Historical verification sections
below describe their named earlier checkouts, not this update.

This map records the story-based test reorganisation on
`fix/prevent-equipment-overallocation`, alongside the equipment approval fix
and integrated PR115 safety-reset fix. It is not a Jira update.
The original pending-sync exception is historical: current Equipment Request
headers (including Issue8) now carry the captured live story and all ACs. Other
services were not rewritten or certified by this owner-only update.

## Requirement ownership

| Behaviour | Primary owner |
| --- | --- |
| Own/overlapping Approved quantities, grouped bulk quantities, exact-stock boundary and competing approvals | SCRUM-35 AC1–AC6 |
| Unavailable or unknown catalogue items cannot contribute usable stock | SCRUM-34 AC2; unknown-item refusal is a supporting fail-closed check |
| Review decisions and existing missing/final-decision response compatibility | SCRUM-33 AC2 |
| Authenticated access and token propagation | Existing SCRUM-8 |
| Assignment-based viewing | Existing SCRUM-9 |
| Review/reset modification authority | Existing SCRUM-10 |
| Decision alerts and outbox rollback | Existing SCRUM-48 AC2; rejection-specific context/content also relates to AC3; rollback is a supporting reliability guarantee |
| Reset previously Approved equipment only | SCRUM-164 AC3; triggered by SCRUM-151 AC2 |

Exact malformed snapshot/ID/reason limits, transport details and status-code
contracts are supporting reliability checks, not newly invented ACs. They
remain visible as requirement gaps instead of deleting useful regressions.
Equipment Reservation supplies catalogue/event inputs; Equipment Request
protects fresh owner allocation reads and approval writes in the final locked
transaction. External input provenance is not proved by that transaction.
Concurrent catalogue quantities, event schedule/status changes, coordinator
reassignment and notification delivery are outside its guarantee.

## Agreed story text

SCRUM-35: Equipment Reservation

Live Jira description verified October 31, 2026 (read-only)

User Story
----------
As a Technical Support Staff member, I want approving equipment requests to reserve the requested quantities for a specific event, so that the total reserved equipment does not exceed the available stock, including when multiple requests are approved at the same time.

Acceptance Criteria
-------------------
AC1: Given a Pending equipment request has sufficient available stock for the event’s duration, when I approve it, then its status changes to Approved and its quantity is immediately counted as reserved when checking further requests.
AC2: Given an equipment request is approved, then its reservation remains associated with the specific event ID for which it was approved.
AC3: Given an equipment request is being checked for approval, then the system calculates the remaining usable quantity for that event’s time period by subtracting quantities already reserved through Approved requests for the same event and other overlapping events whose reservations remain active. Pending and Rejected requests do not reserve equipment.
AC4: Given I select multiple Pending equipment requests for bulk approval, when the system checks availability, then it adds together the selected quantities for each equipment item. If every item has sufficient stock, all selected requests are approved. If any item has insufficient stock, none of the selected requests is approved and all remain Pending.
AC5: Given multiple approval actions compete for the same available equipment, when they are processed at the same time, then the total approved quantity must not exceed the available stock. Any approval that no longer has sufficient stock leaves its selected requests Pending.
AC6: Given the quantity being approved exactly equals the remaining available quantity, when I approve it, then approval succeeds. If the quantity exceeds the remaining available quantity, approval is refused and the selected requests remain Pending.

SCRUM-151: Reject or Request Changes to Safety Arrangements

Live Jira description verified October 31, 2026 (read-only)

User Story
----------
As a Safety Officer, I want to reject an event's safety arrangement or request
changes, stating which planning area must be revisited, so that the Event
Coordinator knows exactly what to fix before the event can proceed.

Acceptance Criteria
-------------------
AC1: Given an event is 'Pending Safety Check', when I request changes, then I
     must select at least one affected area (venue arrangement,
     technical/equipment arrangement, event details) and describe the change
     needed; otherwise the decision is not saved.
AC2: Given changes are requested, then the event status changes to 'Safety Changes Requested', the event returns to the planning stage for each selected area, and its existing arrangements are preserved. For equipment requests affected by the requested changes, only requests with status 'Approved' return to 'Pending' for review. Requests already 'Pending' or 'Rejected' remain unchanged, including any recorded reviewer and rejection reason.
AC3: Given an event is 'Pending Safety Check', when I reject it, then a reason
     is required and I must confirm the rejection before it is saved.
AC4: Given I confirm a rejection, then the event status changes to 'Cancelled',
     and the event cannot be resubmitted for a safety check or moved to any
     further stage.
AC5: Given an event is cancelled by a safety rejection, then its venue bookings
     and equipment reservations are released so they no longer block other
     events, while their records remain in the event's history.
AC6: Given either decision, then the safety check is recorded with the status
     'Changes Requested' or 'Safety Rejected' respectively, together with my
     identity, the timestamp and the reason (plus the selected areas for a
     change request), and the original event information is retained.
AC7: Given an event is not 'Pending Safety Check', then these actions are not
     available and an API call is rejected without changing the event.

SCRUM-164: Revise Arrangements and Resubmit for Safety Check

Live Jira description verified October 31, 2026 (read-only)

User Story
----------
As an Event Coordinator, I want to see the Safety Officer's feedback and revise
the affected arrangements, so that I can resubmit the event for a safety check
without redoing unaffected planning.

Acceptance Criteria
-------------------
AC1: Given my event is 'Safety Changes Requested', when I open it, then I see
     the decision, reason, requested changes and affected areas.
AC2: Given the venue arrangement is flagged, then the affected venue booking
     must be reviewed again by Venue Staff (revised booking or replacement
     request) before the event can be resubmitted.
AC3: Given the technical arrangement is flagged, then the affected equipment requests that were previously 'Approved' return to 'Pending' and must be approved again by Technical Support Staff before the event can be resubmitted. The safety-change action does not reopen existing 'Rejected' requests or clear their rejection reasons, and requests already 'Pending' remain 'Pending'.
AC4: Given an arrangement was not flagged, then it stays confirmed and does not
     need to be reviewed again.
AC5: Given all flagged arrangements are confirmed again, when I resubmit, then
     the status returns to 'Pending Safety Check' as a new review round, and
     earlier rounds remain in the history.

## Maintained locations and verified collection

Paths are relative to the repository root.

| Story | Equipment Reservation unit path / cases | Equipment Request unit path / cases | Equipment Request integration path / collected cases |
| --- | --- | --- | --- |
| SCRUM-35 | `services/equipment-reservation-service/tests/unit/test_scrum35_equipment_reservation.py` / 32 | `services/equipment-request-service/tests/unit/test_scrum35_equipment_reservation.py` / 28 | `services/equipment-request-service/tests/integration/test_scrum35_equipment_reservation.py` / 21 |
| SCRUM-34 | `services/equipment-reservation-service/tests/unit/test_scrum34_equipment_availability.py` / 7 | `services/equipment-request-service/tests/unit/test_scrum34_equipment_availability.py` / 2 | `services/equipment-request-service/tests/integration/test_scrum34_equipment_availability.py` / 3 |
| SCRUM-33 | `services/equipment-reservation-service/tests/unit/test_scrum33_equipment_request_review.py` / 34 | `services/equipment-request-service/tests/unit/test_scrum33_equipment_request_review.py` / 40 | No new module: do not invent an empty tier |
| SCRUM-9 | `services/equipment-reservation-service/tests/unit/test_scrum9_equipment_review_access.py` / 5 | No new module | No new module |
| SCRUM-10 reset | No new module | `services/equipment-request-service/tests/unit/test_scrum10_equipment_safety_reset_access.py` / 10 | `services/equipment-request-service/tests/integration/test_scrum10_equipment_review_modification_access.py` / 4 (review authority) |
| SCRUM-164 | Existing feedback module unchanged in location | `services/equipment-request-service/tests/unit/test_scrum164_equipment_safety_reset.py` / 14 existing cases | `services/equipment-request-service/tests/integration/test_scrum164_equipment_safety_reset.py` / 9 PR115 cases |

Review authentication: the composite retains `tests/unit/test_scrum8_equipment_authentication.py`
(22 cases in the historical run); the owner uses
`tests/unit/test_scrum8_equipment_authentication.py` (24 current cases). The extra outbox rollback case joins the existing
`services/equipment-request-service/tests/integration/test_scrum48_equipment_notification_transactions.py`,
which collects 21 cases; the 46-case claims suite has its ticket-bearing
notification-leases/permissions name. Current stock modules collect 21 SCRUM-35
and 3 SCRUM-34 cases; the new SCRUM-32 FK module adds 1. With the other retained
cases, the current owner integration total is **105** (formerly 100).

## Historical pre-main verification on October 31, 2026

The results below record the earlier reorganisation checkout. They are not
the post-main counts; see the current verification section below.

From each named `services/<name>-service` directory:

```sh
PYTHON_DOTENV_DISABLED=1 uv run --no-env-file --locked --python 3.12 pytest
```

| Service | Passed unit cases | Executed statements | Executed branch outcomes |
| --- | ---: | ---: | ---: |
| equipment-request | 233 | 563/563 | 206/206 |
| equipment-reservation | 208 | 487/487 | 154/154 |
| event | 970 | 2042/2042 | 814/814 |
| safety-check | 594 | 1121/1121 | 398/398 |
| safety-check-record | 219 | 485/485 | 192/192 |
| venue-availability | 548 | 1021/1021 | 346/346 |
| venue-booking | 531 | 1141/1141 | 352/352 |

Every command exited zero and passed its unchanged whole-service 100% coverage
gate. The additional services received header-only story revisions. Counts
are whole suites, not counts of newly introduced tests. No production mutation
or new feature implementation was performed.

Owner/composite collection before and after used:

```sh
PYTHON_DOTENV_DISABLED=1 uv run --no-env-file --locked --python 3.12 pytest --collect-only -q --no-cov -m 'integration or not integration'
```

Owner: **324 = 233 unit + 91 integration** before and after.
Composite: **208 unit** before and after. Focused unit node IDs were then
passed to `pytest --no-cov` in exactly reverse collection order: **115 owner**
and **100 composite** cases passed. The full exact node-ID commands and
old-to-new mapping are in the durable verification archive.

Static comparison verified unchanged executable bodies for every affected
original test (including header-only files), allowing only names/docstrings
and the scoped fixture-name adjustment. Parametrized input multisets are
unchanged across deliberate story partitions; only readable IDs changed.
No assertion was weakened or removed.

## Current post-main verification and evidence limits

At `e7ff578` on October 31, 2026, main `7d9d727` was integrated, including
PR115's Approved-only reset SQL and maintained unit/integration sources.
The earlier missing-source and restarting-container preflight blockers below
are historical, not current publication blockers.

- Whole-service unit runs passed their unchanged 100% line/branch gates:
  Equipment Request **233**, Equipment Reservation **208**, Event **970**,
  Safety Check **601**, Safety Check Record **219**, Venue Availability **548**,
  Venue Booking **531**, Event Workflow **212**. The earlier table's statement
  and branch totals still apply; Safety Check gained 7 PR115 unit cases.
- Owner integrations: **100 passed**, including 9 PR115 reset cases and real
  PostgreSQL approval contention, persistence and outbox checks. The fixture's
  strict guard stayed unchanged: all six pre-existing containers were unchanged,
  its owned container was independently absent, and cleanup reported no errors.
- Safety Check PR115 HTTP-boundary integrations: **5 passed**. Real route/httpx;
  downstream APIs doubled, not real-owner persistence or browser execution.
- Frontend: **1016 tests / 82 files passed**; lint had 0 errors / 4 warnings;
  TypeScript/Vite build passed. Local Node 26.8.1 differs from CI's Node 22.
- Root journeys: **15 collected only**, with dotenv suppressed and Node network
  denied. No login, shared database setup or journey execution was performed.
- Notification's initial collection error was an inherited agent-environment
  collision: `PYTHONPATH` selected Hermes's unrelated `tests` package. With that
  agent-only variable removed (no project paths injected), the same service
  Python collected normally and **237 unit tests passed**, 31 integrations
  deselected, at the unchanged **100%** line/branch gate. No source, package,
  dependency or coverage changes were required.

From each service directory the isolated host invocation is:

```sh
env -u PYTHONPATH PYTHON_DOTENV_DISABLED=1 uv run --no-env-file --locked --python 3.12 python -m pytest
```

1. **Historical Jira-sync limit (superseded for current Equipment Request headers).** The agreed revision is not asserted to be the current
   Jira record. Incoming Issue8 narrow-bugfix headers were preserved rather than
   relabelled as complete Jira convention compliance.
2. **Historical preflight stop retained.** Before main integration, unrelated
   `backend-ngrok-1` restarted (counts 90 then 91); no database run was attempted
   then. The later 100-case run passed preservation/cleanup checks. The earlier
   focused reverse unit order passed 115 owner / 100 composite cases; reverse
   PostgreSQL order was not verified.
3. **Existing fixture policy exception.** Most owner integrations load selected
   baseline FK tables plus the exact owner outbox migration, not the full chain;
   PR115's `safety_reset_owner` fixture loads the full unmodified migration chain.
   Local I/O/libpq guards, pinned PostgreSQL and fresh per-case databases remain;
   these are documented service-specific exceptions, not full-guide compliance.
4. **Trust boundary.** The locked owner transaction protects allocation reads and
   writes against competing approvals. It does not establish provenance of the
   composite-supplied catalogue/event inputs, nor coordinate catalogue, schedule
   or assignment mutations. The separately deferred trust concern was not
   investigated or fixed in this publication work.
5. **Retired coverage.** Approved mocked frontend browser tests were archived and
   removed, not replaced. Frontend unit/component tests and maintained root
   journeys remain; service tests do not prove browser rendering/navigation.

The verification archive is external to Git. Unrelated `.DS_Store`, diagram
exports, ignored local documentation and their index entries remain preserved.
