# Equipment regressions: issues 6/7/8

**Agreed revision from this conversation; pending confirmation that Jira has been updated.**

This is a test/documentation reorganisation on
`fix/prevent-equipment-overallocation`, not a production fix or Jira update.
The exact-Jira-copy convention cannot be certified until Jira is synchronized.
All revised module headers flag this exception; unchanged AC text is preserved.

## Requirement ownership

| Behaviour | Primary owner |
| --- | --- |
| Own/overlapping Approved quantities, grouped bulk quantities, exact-stock boundary and competing approvals | SCRUM-35 AC1–AC6 |
| Unavailable or unknown catalogue items cannot contribute usable stock | SCRUM-34 AC2; unknown-item refusal is a supporting fail-closed check |
| Review decisions and existing missing/final-decision response compatibility | SCRUM-33 AC2 |
| Authenticated access and token propagation | Existing SCRUM-8 |
| Assignment-based viewing | Existing SCRUM-9 |
| Review/reset modification authority | Existing SCRUM-10 |
| Decision alerts and outbox rollback | Existing SCRUM-48 AC2; rollback is a supporting reliability guarantee |
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

Agreed revision from this conversation; pending confirmation that Jira has been updated

User Story
----------
As a Technical Support Staff member, I want approving equipment requests to reserve the requested quantities for a specific event, so that the total reserved equipment does not exceed the available stock, including when multiple requests are approved at the same time.

Acceptance Criteria
-------------------
AC1: Given a Pending equipment request has sufficient available stock for the event’s duration, when I approve it, then its status changes to Approved and its quantity is immediately counted as reserved when checking further requests.
AC2: Given an equipment request is approved, then its reservation remains associated with the specific event ID for which it was approved.
AC3: Given equipment already has Approved requests for the same event or other overlapping events whose reservations still apply, when the system checks a new approval, then it subtracts those reserved quantities from the usable stock. Pending and Rejected requests do not reserve stock.
AC4: Given I select multiple Pending equipment requests for bulk approval, when the system checks availability, then it adds together the selected quantities for each equipment item. If every item has sufficient stock, all selected requests are approved. If any item has insufficient stock, none of the selected requests is approved and all remain Pending.
AC5: Given multiple approval actions compete for the same available equipment, when they are processed at the same time, then the total approved quantity must not exceed the available stock. Any approval that no longer has sufficient stock leaves its selected requests Pending.
AC6: Given the quantity being approved exactly equals the remaining available quantity, when I approve it, then approval succeeds. If the quantity exceeds the remaining available quantity, approval is refused and the selected requests remain Pending.

SCRUM-151: Reject or Request Changes to Safety Arrangements

Agreed revision from this conversation; pending confirmation that Jira has been updated

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

Agreed revision from this conversation; pending confirmation that Jira has been updated

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
| SCRUM-35 | `services/equipment-reservation-service/tests/unit/test_equipment_reservation.py` / 32 | `services/equipment-request-service/tests/unit/test_equipment_reservation.py` / 28 | `services/equipment-request-service/tests/integration/test_equipment_reservation.py` / 19 |
| SCRUM-34 | `services/equipment-reservation-service/tests/unit/test_equipment_availability.py` / 7 | `services/equipment-request-service/tests/unit/test_equipment_availability.py` / 2 | `services/equipment-request-service/tests/integration/test_equipment_availability.py` / 1 |
| SCRUM-33 | `services/equipment-reservation-service/tests/unit/test_equipment_request_review.py` / 34 | `services/equipment-request-service/tests/unit/test_equipment_request_review.py` / 40 | No new module: do not invent an empty tier |
| SCRUM-9 | `services/equipment-reservation-service/tests/unit/test_equipment_review_access.py` / 5 | No new module | No new module |
| SCRUM-10 reset | No new module | `services/equipment-request-service/tests/unit/test_safety_reset_modification_access.py` / 10 | `services/equipment-request-service/tests/integration/test_equipment_review_modification_access.py` / 4 (review authority) |
| SCRUM-164 | Existing feedback module unchanged in location | `services/equipment-request-service/tests/unit/test_equipment_safety_reset.py` / 14 existing cases | **Absent PR115 source**, not restored |

Review authentication cases join each service's existing
`tests/unit/test_authentication.py`; those modules now collect 22 composite
and 21 owner cases. The extra outbox rollback case joins the existing
`services/equipment-request-service/tests/integration/test_scrum48_transactions.py`,
which now collects 21 cases; its legacy filename and unrelated test bodies
are retained to avoid unrelated broad reformatting. The 46-case claims suite
is unchanged. Thus the owner integration tier still collects **91** cases.

## Recorded verification on October 31, 2026

The results below predate the documentation refresh; no application tests or
services were run during that refresh.

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

## Blockers and evidence limits

1. **Jira sync pending.** This agreed revision is not asserted to be the current
   Jira record. Other SCRUM-151/164 ACs and story text are unchanged.
2. **Issue8 is merged on cached main; this checkout is older.** Cached Git
   ancestry confirms fix `cdd3112` via PR115 merge `6027e82` is in
   `origin/main` at `946af5e4055523f7fa83c0b849ffe58a74843252`, not local
   HEAD `0f00da3ca290bdb9e4f5fd017f306465020ddc0e`. HEAD is an ancestor of
   cached main; this is not evidence that the merged fix was lost. The local
   Approved-only reset predicate and its integration module remain absent, so
   that published regression suite cannot be verified on this checkout. No
   fetch, branch switch, restore or integration was performed. Existing local
   doubles do not prove preservation during a concurrent rejection/reset.
3. **Database execution stopped at preflight.** Docker and the pinned image
   are available, but unrelated `backend-ngrok-1` was auto-restarting. Read-only
   inspection observed restart count 90 then 91 and different StartedAt values.
   This conflicts with the existing integration fixture's strict unchanged-
   preexisting-container guard. No test container, shared DB, broker or worker
   was started; no unrelated container was stopped; no guard was weakened.
   Normal and reverse-order PostgreSQL execution remain unverified until the
   user stabilizes that unrelated container or authorizes the next step.
4. **Existing fixture policy exception.** Owner integrations use a pinned
   PostgreSQL digest, a labelled loopback/tmpfs container, fresh database per
   case, explicit libpq allowlist and denied Python connections. They install
   selected baseline FK tables plus the exact owner outbox migration, **not**
   the full unmodified migration chain required by the general guide. The
   service uses its local I/O guards, not pytest-socket. This pre-existing
   exception was documented, not silently repaired or presented as full-guide
   compliance. Composite HTTP tests remain unit tests, not real-owner tests.

No commits, pushes, merges, branch changes, CI/config changes or Jira edits
were performed. Existing production/C4/.DS_Store dirty bytes and staged
entries were preserved against an external durable backup.
