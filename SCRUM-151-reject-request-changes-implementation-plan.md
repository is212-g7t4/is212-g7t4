# SCRUM-151 Reject or Request Changes to Safety Arrangements: implementation plan

Oct 14, 2026 · for Clarice Lim · written against `main` at `36f4048` (after PR #54 SCRUM-150 and PR #55 SCRUM-152)

Give the Safety Officer the other two decisions beside **Approve**. **Request changes** records which planning areas must be revisited and moves the event to **`Safety Changes Requested`**, leaving every booking and equipment request as it is. **Reject** (reason required, confirmed first) moves the event to **`Cancelled`** for good and releases its venue bookings so they stop blocking other events. Both decisions are recorded on the open `SafetyCheck` round (`Changes Requested` / `Safety Rejected`) with the officer, time and reason; a change request also writes one `SafetyCheckFlag` row per selected area.

The workflow lives in **Safety Check Service (composite)**, exactly like SCRUM-150's approve, which this story generalises. The decision and flags are stored by **Safety Check Record Service (atomic)**; the event's status and history by **Event Service (atomic)**; venue bookings are released through **Venue Availability Service (atomic)**. Equipment needs no write: the availability check already stops counting a `Cancelled` event's equipment.

## Step 0 for the agent: create the branch first

```
git fetch origin main
git checkout -b SCRUM-151-reject-or-request-changes-to-safety-arrangements origin/main
git push -u origin SCRUM-151-reject-or-request-changes-to-safety-arrangements
```

Name follows AGENTS.md (`<SCRUM-KEY>-<kebab-case-summary>`). Every commit starts with `SCRUM-151:`; confirm the key with Clarice before the first commit, as AGENTS.md requires. Open the PR into `main`.

## The story (Jira, word for word, read 14 Oct)

> As a Safety Officer, I want to reject an event's safety arrangement or request changes, stating which planning area must be revisited, so that the Event Coordinator knows exactly what to fix before the event can proceed.
>
> 1. Given an event is 'Pending Safety Check', when I request changes, then I must select at least one affected area (venue arrangement, technical/equipment arrangement, event details) and describe the change needed; otherwise the decision is not saved.
> 2. Given changes are requested, then the event status changes to 'Safety Changes Requested', the event returns to the planning stage for each selected area, and its existing arrangements are preserved.
> 3. Given an event is 'Pending Safety Check', when I reject it, then a reason is required and I must confirm the rejection before it is saved.
> 4. Given I confirm a rejection, then the event status changes to 'Cancelled', and the event cannot be resubmitted for a safety check or moved to any further stage.
> 5. Given an event is cancelled by a safety rejection, then its venue bookings and equipment reservations are released so they no longer block other events, while their records remain in the event's history.
> 6. Given either decision, then the safety check is recorded with the status 'Changes Requested' or 'Safety Rejected' respectively, together with my identity, the timestamp and the reason (plus the selected areas for a change request), and the original event information is retained.
> 7. Given an event is not 'Pending Safety Check', then these actions are not available and an API call is rejected without changing the event.

Jira comment (Clarice, 5 Oct): *"Assumptions: Rejecting the safety arrangement cancels the event entirely."* (This overrides the 3 Oct draft in `change-6-operational-feasibility/`, which said rejection does not cancel.)

5 points, Sprint 3 (7 to 18 Oct), High, To Do, assigned to Clarice. Week 7 change #6: *"The Safety Officer may approve the event, reject the safety arrangement, or request changes. If changes are required, the event returns to the relevant earlier planning stage and affected venue or technical arrangements may need to be reviewed again."*

Neighbouring stories: SCRUM-149 submit (Done), SCRUM-150 approve (merged, PR #54), SCRUM-152 gate (merged, PR #55), SCRUM-153 re-check (To Do, Clarice), SCRUM-162 queue (Claire), SCRUM-163 review page (Justin, its AC4 reads earlier decisions and requested changes), **SCRUM-164 revise and resubmit (Jun Wei)**, SCRUM-168 notifications (unassigned).

### Where 151 stops and 164 starts

This split matters for AC2 and is the main design decision in this plan.

| Concern | SCRUM-151 (this story) | SCRUM-164 (Jun Wei) |
| --- | --- | --- |
| Record which areas need work, and what change | Yes: `SafetyCheckFlag` rows, one per area | Reads them |
| Move the event to `Safety Changes Requested` | Yes | Moves it back to `Pending Safety Check` on resubmit |
| Bookings / equipment requests | **Untouched** ("existing arrangements are preserved") | Requires flagged areas' arrangements to be reviewed again before resubmit (its AC2 to AC4) |
| Show the coordinator the decision, reason and areas | Only the action-history line on the event | Full feedback view (its AC1) |

## Architecture after Week 7 (from `c4_diagram/`)

- **C2** (`c2.dsl`): one Front-End App, one API Application, the Hold Checker job, RabbitMQ; Supabase and MongoDB Atlas outside the boundary. The Safety Officer "reviews and decides safety checks" through the Front-End App.
- **C3** (`c3.dsl`): the Safety Check Module "owns safety check records and coordinates the safety-check workflow: submit, review, decide, resubmit". It reads/sets event status via the Event Module; "checks approval of, and reopens flagged, venue bookings" via Venue Availabilities; does the same for equipment via Equipment Availability; logs decision reasons to Forum; publishes decision notifications.
- **Service level** (`export/c4.png`): **Safety Check Service (Composite)** sits over **Safety Check (Atomic)**, whose store holds `SafetyCheck` and `SafetyCheckFlag (flagId, safetyCheckId, area, bookingId, equipRequestId, changeRequired)`. The composite links to Event, Venue Availability, Equipment Availability (= `equipment-request-service` in code), Venue, User, Forum and Notification.

So every write this story needs is already on the diagram as a Safety Check composite → atomic link. The one thing the C3 line does not mention is *releasing* bookings on rejection; task 7 adds those words.

## Where things stand on `main`

| Piece | State | What this story needs from it |
| --- | --- | --- |
| `services/safety-check-service/` (composite, 5012) | `POST /safety-checks` (submit), `POST /safety-checks/approve`, `GET /safety-checks/readiness`. Approve = role check → event `Pending Safety Check` → open round → decide record → move event, with `reopen` compensation (`routes.py:114`) | Two new routes sharing approve's steps; a venue-booking cancel client |
| `services/safety-check-record-service/` (atomic, 5013) | `RECORD_STATUSES` already has `Changes Requested` and `Safety Rejected`; `DECISION_STATUSES = (SAFETY_APPROVED,)` (`models.py:27`). `decide_round` / `reopen_round` built. Writes no `SafetyCheckFlag` rows (README says "those are SCRUM-151's") | Widen `DECISION_STATUSES`; write and read flags; reopen clears flags |
| `SafetyCheckFlag` table | Exists in `database/supabase/migrations/20261011140000_baseline_schema.sql:107`; seed has two `event details` flags on a `Changes Requested` round | **No migration.** Use as is |
| `services/event-service/` (atomic, 5003) | `SAFETY_TRANSITIONS = {"Approved": {"Pending Safety Check"}, "Pending Safety Check": {"Confirmed"}}` (`models.py:90`). `/safety-status` validates fields only for submit and approve; the comment there says SCRUM-151's moves fall through to `409`. Stale-round check exists for `Confirmed` only. `Cancelled` has no entry in `SAFETY_TRANSITIONS`, so it can never leave | Two new moves out of `Pending Safety Check`, their body fields, history entries |
| `services/venue-availability-service/` (atomic, 5008) | `PATCH /venue-bookings/<id>/cancel {eventId}` sets `status = 'Cancelled'`, keeps the row, is idempotent (`models.py:268`). Conflict checks ignore `Rejected`, `Cancelled`, `Expired` | **No change.** Called to release bookings (AC5) |
| `services/equipment-reservation-service/` (composite) | `RESERVING_EVENT_STATUSES` excludes `Cancelled` "deliberately (SCRUM-151 AC5)" (`availability.py:9`), so a cancelled event's approved requests stop holding stock | **No change.** This *is* AC5's equipment release; records stay as they are |
| `services/equipment-request-service/` (atomic) | Statuses `Pending/Approved/Rejected`; no cancel path | **No change** |
| Frontend | `SafetyDecisionPanel` has Approve only (its comment: "SCRUM-151 later adds Reject and Request changes"). `EventDetailPage` renders it for a Safety Officer on `Pending Safety Check`. `VenueBookingsPanel` shows for the coordinator at every status, including `Cancelled` | Two more actions in the panel; hide booking edits on `Cancelled`; show reasons in history |
| Identity | Composite looks the role up in User Service (SCRUM-150). `/safety-status` token lock is opt-in (`INTERNAL_SERVICE_TOKEN`) | Same |

## Which service does what

| Service | Type | Responsibility in SCRUM-151 | Change |
| --- | --- | --- | --- |
| **Safety Check Service** `services/safety-check-service/`, 5012 | Composite | **Owns both workflows.** Validates the request (AC1, AC3), checks the caller is a Safety Officer, checks the event is `Pending Safety Check` (AC7), decides the open round with its flags, moves the event, undoes the decision if the move fails; on rejection, then releases the event's venue bookings (AC5) | New `POST /safety-checks/request-changes`, `POST /safety-checks/reject`; shared decide helper refactored out of approve; new client `cancel_venue_booking`; `decide_safety_check_record` sends `flags` |
| **Safety Check Record Service** `services/safety-check-record-service/`, 5013 | Atomic | **Owns the decision record and flags (AC6).** Sets the round to `Changes Requested` / `Safety Rejected` with `decided_by`, `decided_at`, `remarks` (the reason), and inserts one `SafetyCheckFlag` per area, in one transaction | `DECISION_STATUSES` widened; per-status rules on `PATCH .../decision`; flags in responses; `reopen` deletes the round's flags |
| **Event Service** `services/event-service/`, 5003 | Atomic | **Owns the event's status (AC2, AC4) and its history entry (AC6, event side).** `Pending Safety Check → Safety Changes Requested` and `→ Cancelled`, only via `/safety-status`, only for the open round. No other event field changes (AC6 "original event information is retained") | `SAFETY_TRANSITIONS`, body validation, two history-entry shapes, shared stale-round check |
| **Venue Availability Service** `services/venue-availability-service/`, 5008 | Atomic | Marks each of the event's live bookings `Cancelled` (released, row kept) | None (existing `PATCH /venue-bookings/<id>/cancel`) |
| **Equipment Reservation Service** | Composite | Already ignores `Cancelled` events when counting held stock | None |
| **User Service** `services/user-service/`, 5001 | Atomic | Answers "is this caller a Safety Officer" | None |
| **Event Management UI** `frontend/event-management-ui/` | React SPA | Request changes form (areas + change per area + reason); Reject with required reason and confirm step; both offered only on `Pending Safety Check` (AC7, UI side); booking panel hidden on `Cancelled`; reasons and areas shown in action history | `SafetyDecisionPanel`, `safetyCheck.ts`, `EventDetailPage`, `submission.ts` types |
| Equipment Request, Venue, Equipment, Registration, Coordinator Assignment, Venue Booking, Attendee Registration | | Not involved | None |
| Event Workflow Service (planned, provisional), Forum, Notification, Broker | | Not built. The C3 diagram has the decision reason logged to Forum and a decision notification published; notifications are **SCRUM-168**. Cancellation cascade for a safety rejection: Safety Check Service (Clarice, 14 Oct) | None |

Why the composite and not an atomic owns the workflow: each decision writes entities owned by two (reject: three) atomics, and atomics never call each other (AGENTS.md). Same shape as 149 and 150.

## Design

### Lifecycle after this story

```
Approved ──(149 submit)──► Pending Safety Check ──(150 approve)──► Confirmed
                                   │
                                   ├──(151 request changes)──► Safety Changes Requested ──(164 resubmit)──► Pending Safety Check
                                   │
                                   └──(151 reject)──────────► Cancelled   (terminal: no outgoing move in either table)
```

### Flag areas and inputs

The three areas, stored verbatim in `SafetyCheckFlag.area` (lower case, matching `docs/db-structure.md` and the seed):

| Stored value | UI label |
| --- | --- |
| `venue arrangement` | Venue arrangement |
| `technical arrangement` | Technical / equipment arrangement |
| `event details` | Event details |

Defaults built into this plan:
- **Flags are area-level.** One row per selected area; `booking_id` and `equip_request_id` stay `NULL`. A flagged venue or technical area means *the event's arrangements in that area*; SCRUM-164 decides how they are reviewed again. (Question 1.)
- **Each selected area needs its own "change needed" text** (AC1), stored in `change_required`, ≤ 2000 chars, not blank.
- **Both decisions need an overall reason** (AC3, AC6), stored in `SafetyCheck.remarks`, ≤ 2000 chars, not blank. Approve keeps remarks optional.
- At most one flag per area; at least one area for a change request; no flags on a rejection or an approval.
- **The API enforces the reject confirmation too:** `POST /safety-checks/reject` needs `"confirmed": true`, so a client that skips the UI's confirm step gets `400` and nothing is saved (AC3).

### Order of writes

Both routes reuse approve's steps 1 to 6; extract them into one helper in `routes.py` (e.g. `_decide(event_id, officer_id, record_status, event_status, reason, flags)`) and make approve call it too, so the three decisions cannot drift.

```
UI ── POST /safety-checks/request-changes {eventId, safetyOfficerId, reason, flags:[{area, changeRequired}]}
UI ── POST /safety-checks/reject          {eventId, safetyOfficerId, reason, confirmed: true}
                                                                          ──► Safety Check Service
 1. validate body (UUIDs, reason, flags / confirmed)                      400, nothing saved (AC1, AC3)
 2. GET  User Service   /users/<officer>        role == Safety Officer?   403 NOT_SAFETY_OFFICER
 3. GET  Event Service  /events/<id>?coordinatorId=<officer>&viewerRole=Safety Officer
                                                status == Pending Safety Check?   409 EVENT_NOT_PENDING_SAFETY_CHECK (AC7)
 4. GET  Record Service /safety-check-records?eventId=<id>&status=Pending   one open round?  409 NO_OPEN_SAFETY_CHECK
 5. PATCH Record Service /safety-check-records/<roundId>/decision
          {status: "Changes Requested" | "Safety Rejected", decidedBy, remarks: reason, flags}
                                                                          409 SAFETY_CHECK_ALREADY_DECIDED
 6. PATCH Event Service /events/<id>/safety-status   (X-Internal-Service-Token)
          {status: "Safety Changes Requested" | "Cancelled", decidedBy, safetyCheckId, roundNumber, remarks, areas?}
        on any failure → POST Record Service /safety-check-records/<roundId>/reopen {decidedAt}
                         (also deletes the round's flags)
 7. reject only: release (AC5)
    GET  Venue Availability /events/<id>/venue-bookings
    for each booking whose status is not Cancelled / Expired / Rejected:
         PATCH Venue Availability /venue-bookings/<bookingId>/cancel {eventId}
 8. 200 {safetyCheck, event}            (+ release: {...} for reject)
```

**Record first, then event**, as in 149 and 150: the record service's `FOR UPDATE` is the race guard, so if one officer approves while another rejects, only one decision lands and the other gets `409` before the event is touched.

**Release last, and only for reject.** Cancelling a booking can't be undone (the slot may be taken a second later), so it happens only once the event is definitely `Cancelled`. If listing or cancelling a booking fails, the decision stands (the event really is cancelled): the route still returns `200`, lists the booking IDs it could not release in `release.venueBookingsNotReleased`, and logs each at ERROR. Cancel is idempotent, so clearing it by hand is safe; the README gets the `curl` (same approach as `_compensate`). `Rejected` bookings are left as they are: they already block nothing, and keeping their status keeps the history accurate.

`release` in the reject response:

```json
{
  "venueBookingsReleased": ["<bookingId>", "..."],
  "venueBookingsNotReleased": [],
  "equipment": "Released: equipment held by a Cancelled event no longer counts against availability."
}
```

### Safety Check Record Service (atomic)

`app/models.py`:

```python
DECISION_STATUSES = (SAFETY_APPROVED, CHANGES_REQUESTED, SAFETY_REJECTED)
FLAG_AREAS = ("venue arrangement", "technical arrangement", "event details")
FLAG_COLUMNS = "flag_id, safety_check_id, area, booking_id, equip_request_id, change_required"

def decide_round(database_url, safety_check_id, status, decided_by, remarks=None, flags=()):
    # unchanged checks under FOR UPDATE; after the UPDATE, one INSERT per flag
    # into public."SafetyCheckFlag" (safety_check_id, area, change_required),
    # same transaction, then attach the inserted flags to the returned round.

def reopen_round(database_url, safety_check_id, decided_at):
    # unchanged match on decided_at; also
    # DELETE FROM public."SafetyCheckFlag" WHERE safety_check_id = %s

def list_rounds(...):
    # after reading the rounds, one more query:
    # SELECT FLAG_COLUMNS FROM public."SafetyCheckFlag" WHERE safety_check_id = ANY(%s)
    # and attach each round's flags. create_round returns flags: [].
```

`serialize` adds `"flags": [{"id", "area", "bookingId", "equipmentRequestId", "changeRequired"}]`. Every round now carries `flags` (empty when none), which is what SCRUM-163 AC4 and SCRUM-164 AC1 read.

`app/__init__.py`, `PATCH /safety-check-records/<id>/decision` gains per-status rules (all checked before the database is touched):

| `status` | `remarks` | `flags` |
| --- | --- | --- |
| `Safety Approved` | optional (unchanged) | absent or `[]` |
| `Changes Requested` | required, not blank | 1 to 3 items, each `{area ∈ FLAG_AREAS, changeRequired: non-blank text ≤ 2000}`, no area twice |
| `Safety Rejected` | required, not blank | absent or `[]` |

Breaking either rule → `400` with a message naming the field. Everything else (404, `409 SAFETY_CHECK_ALREADY_DECIDED`, `409 NOT_LATEST_ROUND`, 503) is unchanged. Update the README (it currently says this service writes no flags).

### Event Service (atomic)

`app/models.py`:

```python
SAFETY_TRANSITIONS = {
    "Approved": {"Pending Safety Check"},
    "Pending Safety Check": {"Confirmed", "Safety Changes Requested", "Cancelled"},
    # 'Cancelled' has no entry: a rejected event can never move again (SCRUM-151 AC4).
    # SCRUM-164 adds "Safety Changes Requested": {"Pending Safety Check"}.
}
SAFETY_FLAG_AREAS = ("venue arrangement", "technical arrangement", "event details")  # mirrors safety-check-record-service
```

`update_event_safety_status`:
- Pull the existing `Confirmed` stale-round check (latest `Pending Safety Check` history entry must carry the request's `safetyCheckId`, else `StaleSafetyCheckError`) into a helper and apply it to **all three** decision moves.
- No coordinator check for the two new moves (the Safety Officer decides; the composite checked the role), same as `Confirmed`.
- Add an `areas=None` keyword argument. Append, under the same `FOR UPDATE`:

```python
# Safety Changes Requested
{"status": "Safety Changes Requested",
 "details": f"Operational Safety Check: changes requested (round {n}) for {', '.join(areas)}.",
 "decidedBy": decided_by, "safetyCheckId": safety_check_id,
 "remarks": remarks, "areas": areas, "recordedAt": now}

# Cancelled
{"status": "Cancelled",
 "details": f"Operational Safety Check rejected (round {n}). The event is cancelled.",
 "decidedBy": decided_by, "safetyCheckId": safety_check_id,
 "remarks": remarks, "recordedAt": now}
```

Only `status` and the history change; `decision`, `decisionHistory`, `actionDetails` and every event column stay as they are (AC6).

`app/__init__.py`, `PATCH /events/<id>/safety-status`: for `Safety Changes Requested` and `Cancelled`, require `decidedBy` (UUID) and `remarks` (non-blank, ≤ 2000); for `Safety Changes Requested` also `areas` (non-empty list of distinct `SAFETY_FLAG_AREAS` values). Remove the "SCRUM-151's falls through" comment. `409` codes as today (`INVALID_SAFETY_TRANSITION`, `STALE_SAFETY_CHECK`).

AC4's "cannot be resubmitted" needs no new code: submit's move is `Approved → Pending Safety Check`, and `Cancelled` has no transitions in either table. Tests pin it (below). `PATCH /progress` still allows a `Cancelled → Cancelled` notes save; that is not a stage move, so leave it.

### Safety Check Service (composite)

`app/clients.py`:
- `decide_safety_check_record(round_id, status, decided_by, remarks=None, flags=None)`: sends `flags` when given.
- `set_event_safety_status(...)`: new `areas=None` keyword, sent when given.
- `cancel_venue_booking(booking_id, event_id)` → `PATCH {VENUE_AVAILABILITY_SERVICE_URL}/venue-bookings/<id>/cancel` with `{"eventId": event_id}`. `404` → `RecordNotFoundError`; other failures → `DownstreamError` / `DownstreamTimeout`.

`app/routes.py`: constants `SAFETY_CHANGES_REQUESTED = "Safety Changes Requested"`, `CANCELLED = "Cancelled"`, `CHANGES_REQUESTED = "Changes Requested"`, `SAFETY_REJECTED = "Safety Rejected"`, `FLAG_AREAS`. Generalise `NOT_SAFETY_OFFICER` to "Only a Safety Officer can decide an event's Operational Safety Check." and `_approve_status_failure`'s message to "Only an event 'Pending Safety Check' can be decided". Responses for both routes:

| Case | Status | Body `code` |
| --- | --- | --- |
| Decided | `200` | `{safetyCheck, event}` (+ `release` for reject) |
| Bad UUIDs; reason missing, blank, not text or > 2000; no area / unknown area / duplicate area / blank or long `changeRequired` (AC1); `confirmed` not `true` on reject (AC3) | `400` | `REJECTION_NOT_CONFIRMED` for the last; plain message otherwise |
| Caller unknown or not a Safety Officer | `403` | `NOT_SAFETY_OFFICER` |
| Event not found | `404` | |
| Event not `Pending Safety Check` (AC7) | `409` | `EVENT_NOT_PENDING_SAFETY_CHECK`, with `currentStatus` |
| No open round | `409` | `NO_OPEN_SAFETY_CHECK` |
| Round already decided | `409` | `SAFETY_CHECK_ALREADY_DECIDED` |
| Event Service refused step 6 | `409` / `502` after reopening | as approve |
| Downstream timeout / error before step 6 | `504` / `502` | |
| Release failed (reject, step 7) | still `200` | `release.venueBookingsNotReleased` non-empty |

`docker-compose.yml`: no change (`VENUE_AVAILABILITY_SERVICE_URL` is already wired). README: the two routes, the order of writes, the release-by-hand `curl`.

### Frontend (`frontend/event-management-ui/`)

1. `src/features/safety/safetyCheck.ts`: `SafetyFlagArea` union and `FLAG_AREAS` (value + label from the table above); `SafetyCheckFlag` type; `flags: SafetyCheckFlag[]` on `SafetyCheckRecord`; `requestSafetyChanges({eventId, safetyOfficerId, reason, flags})` and `rejectSafetyCheck({eventId, safetyOfficerId, reason})` (sends `confirmed: true`, so call it only from the confirm button).
2. `src/features/safety/SafetyDecisionPanel.tsx`: three actions, **Approve**, **Request changes**, **Reject**, one open at a time. Rename prop `onApproved` → `onDecided`.
   - Request changes: a checkbox per area; ticking one reveals a required "Change needed" textarea for it (2000 chars, counter); a required "Reason" textarea. Submit is disabled until at least one area is ticked, every ticked area has text, and the reason is filled; show inline "Select at least one area" / "Describe the change needed" messages (AC1). Success: "Changes requested. The event has moved to Safety Changes Requested."
   - Reject: required "Reason" textarea; **Reject** opens a confirm step: "Reject and cancel this event? This can't be undone. Its venue bookings will be released." with **Yes, reject and cancel** / **Cancel** (AC3). Success: "Rejected. The event is cancelled and its venue bookings were released." If `release.venueBookingsNotReleased` is non-empty, show a warning that some bookings could not be released and must be cancelled by Venue Staff.
   - Any API error shows its `message`.
3. `src/pages/EventDetailPage.tsx`: pass `onDecided`; render `VenueBookingsPanel` only when `event.status !== 'Cancelled'`; in Action history, show an entry's `remarks` (as "Reason: …") and `areas` under its `details`, so the coordinator sees what to fix and why. The panel stays limited to `role === 'Safety Officer' && status === 'Pending Safety Check'` (AC7, UI side).
4. `src/features/event/submission.ts`: `EventAction` gains optional `remarks?: string | null` and `areas?: string[]`.
5. `eventStatus.ts`: no change (messages for both statuses already exist).

## Tests

Every test name or docstring cites the AC (e.g. "SCRUM-151 AC5: ..."). Unit tests are hermetic (pytest-socket); mock `psycopg2.connect` and `httpx` as the existing safety tests do. File names are story-based.

### Safety Check Record Service: new `tests/unit/test_safety_reject_changes.py`

| Test | AC |
| --- | --- |
| `Changes Requested` with two flags → `200`; one `UPDATE` + two `INSERT INTO "SafetyCheckFlag"` in the same connection; response has `decidedBy`, `decidedAt`, `remarks`, `flags` | AC1, AC6 |
| `Changes Requested` with no flags / unknown area / duplicate area / blank or 2001-char `changeRequired` / blank remarks → `400`, no SQL | AC1 |
| `Safety Rejected` with remarks → `200`, no flag insert; without remarks → `400`; with flags → `400` | AC3, AC6 |
| `Safety Approved` with flags → `400`; without remarks still `200` (SCRUM-150 unchanged) | regression |
| Already decided / not latest → `409`, no flag insert | AC7 / race |
| `reopen` deletes the round's flags and reverts the round | compensation |
| `GET /safety-check-records` returns each round's flags; rounds without flags get `[]` | AC6 |

Update existing tests whose cursor mocks assume `list_rounds` makes one query, and `test_safety_decision.py`'s "`Changes Requested` is rejected for now" case (it is now valid with flags).

### Event Service: new `tests/unit/test_safety_reject_changes_status.py`

| Test | AC |
| --- | --- |
| `Pending Safety Check → Safety Changes Requested` with areas → `200`; history entry has status, `decidedBy`, `safetyCheckId`, `remarks`, `areas`, `recordedAt` | AC2, AC6 |
| `Pending Safety Check → Cancelled` → `200`; history entry as above without `areas` | AC4, AC6 |
| Only `status` and `description.actionHistory` change: `decision`, `decisionHistory`, `actionDetails`, name, dates, attendance unchanged | AC6 |
| Each non-pending status → `409 INVALID_SAFETY_TRANSITION`, only the `SELECT` ran | AC7 |
| Wrong `safetyCheckId` → `409 STALE_SAFETY_CHECK` for both moves | AC7 |
| Missing `decidedBy` / blank `remarks` / missing, empty, unknown or duplicate `areas` → `400` | AC1, AC3 |
| From `Cancelled`: `/safety-status` to `Pending Safety Check` and to `Confirmed` → `409`; `/progress` can't reach any other status | AC4 |
| No coordinator check on either move | |

Update `test_safety_submit_status.py` / `test_safety_gate.py` parametrisations that still treat the two new targets as unreachable, and keep `test_only_pending_safety_check_leads_into_confirmed` green. Add: nothing in either table lists a move *out of* `Cancelled` except `/progress`'s self-save.

### Safety Check Service: new `tests/unit/test_safety_reject_changes.py`

| Test | AC |
| --- | --- |
| Request changes happy path: role, event, open round, decide with flags, event move with `areas` and token; `200` | AC1, AC2, AC6 |
| Request changes validation failures (no area, unknown, duplicate, blank change text, no reason) → `400`, **no downstream call at all** | AC1 |
| Request changes never calls Venue Availability or Equipment Request | AC2 (arrangements preserved) |
| Reject happy path: decide, event → `Cancelled`, list bookings, cancel each `Approved` / `Pending Review` booking, skip `Cancelled` / `Expired` / `Rejected`; `200` with `release` | AC4, AC5, AC6 |
| Reject without `confirmed: true` or without reason → `400`, no downstream call | AC3 |
| Reject: one cancel fails → still `200`, that ID in `venueBookingsNotReleased`, ERROR log; listing fails → `200`, ERROR log | AC5 |
| Reject never cancels bookings when step 5 or 6 failed | AC5 |
| Not a Safety Officer → `403`; event not pending (parametrised) → `409`; no open round → `409`; already decided → `409`; all with no writes | AC7 |
| Event move fails → `reopen` called with step 5's `decidedAt` | compensation |
| Approve still passes through the refactored helper (existing `test_safety_approve.py` unchanged and green) | regression |
| `test_clients.py`: `cancel_venue_booking`; `flags` / `areas` sent only when given | |

Safety Check Service and Safety Check Record Service sit at `fail_under = 100`; keep them there. Event Service is at 97; raise it if this lifts it.

### Frontend

- Vitest `SafetyDecisionPanel.test.tsx` (extend): three actions shown; request-changes button disabled until an area, its change text and the reason are filled, with the inline messages (AC1); sends the expected `flags`; reject needs a reason, then the confirm step, then calls the API (AC3); release warning shown when `venueBookingsNotReleased` is non-empty; API `message` shown on `409`.
- Vitest `EventDetailPage.test.tsx`: no decision panel on any status but `Pending Safety Check` (AC7); `VenueBookingsPanel` hidden on `Cancelled`; history shows reason and areas.
- Playwright `e2e/safety-request-changes.spec.ts` and `e2e/safety-reject.spec.ts` (mock every call via `mock()` in `e2e/fixtures.ts`): Safety Officer opens a pending event, requests changes on two areas / rejects with a reason and confirms; the mocked POST receives the expected body; the badge shows `Safety Changes Requested` / `Cancelled`. Existing `safety-approve`, `safety-submit`, `safety-gate`, `safety-gate-journey` specs must pass unchanged.

### Manual check (for the Jira attachment)

With `npm run dev` from the repo root: submit two `Approved` test events as their coordinator (SCRUM-149). As Nurul Huda (Safety Officer, `5af3e7c1-…9e21`), request changes on the first (venue arrangement + event details) and reject the second. Screenshot: the first event `Safety Changes Requested` with its bookings still `Approved`, and its `SafetyCheck` + two `SafetyCheckFlag` rows; the second `Cancelled`, its bookings `Cancelled` (rows still there), and the slot now free in the venue calendar. Then `curl -X POST localhost:5012/safety-checks/reject` on the cancelled event returns `409`, and a submit on it returns `409`. Restore any data you changed.

## Task breakdown

| # | Task | Service | Depends on | Est. (h) |
| --- | --- | --- | --- | --- |
| 0 | Branch (Step 0) | Git | | 0.1 |
| 1 | Widen `DECISION_STATUSES`, per-status rules, flag insert/read/delete, tests at 100%, README | Safety Check Record (atomic) | 0 | 2 |
| 2 | Two new moves, body validation, shared stale-round check, history entries, tests | Event (atomic) | 0 | 1.5 |
| 3 | Refactor approve into the shared decide helper (no behaviour change; existing tests green) | Safety Check (composite) | 0 | 0.5 |
| 4 | Request-changes and reject routes, `cancel_venue_booking`, release step, tests at 100%, README | Safety Check (composite) | 1, 2, 3 | 2.5 |
| 5 | `safetyCheck.ts`, `SafetyDecisionPanel`, `EventDetailPage`, types | UI | API contract above | 2.5 |
| 6 | Vitest + Playwright | UI | 5 | 1.5 |
| 7 | Docs: C3 Safety Check line ("…and releases, on rejection, venue bookings via"), `docs/db-structure.md` `SafetyCheckFlag` note on area-level flags, INDEX.md Safety Check rows | Repo | 4 | 0.5 |
| 8 | `npm run test:backend`, PR, CI green, manual evidence, Jira | All | 1 to 7 | 1 |

About 12 hours. Backend (1 to 4) and frontend (5, 6) can run in parallel once the two `POST` contracts above are accepted.

## Not in this story

- **Notifications** to the coordinator (decision, reason, areas): SCRUM-168. Publish after step 6 (and after release); a failure must not undo the decision (its AC3).
- **Re-review of flagged arrangements and resubmission**: SCRUM-164. It adds `Safety Changes Requested → Pending Safety Check` and reads this story's flags.
- **Forum entry** for the decision reason: Forum Service isn't built; the reason lives in `SafetyCheck.remarks` and the event's history.
- **Server-side block on new bookings or equipment requests for a `Cancelled` event** (Venue Booking / Equipment Reservation composites). This story hides the booking panel in the UI only. Worth a small follow-up ticket, since a new booking on a cancelled event would block a venue again.
- **Editing event details**: no endpoint exists for a coordinator to edit event fields; an `event details` flag is recorded and shown, and fixing it is 164's (or an edit story's) concern.

## How later stories build on this

- **SCRUM-164:** reads `flags` from `GET /safety-check-records?eventId=`; a `venue arrangement` / `technical arrangement` flag means that area's arrangements must be reviewed again before resubmit; adds `"Safety Changes Requested": {"Pending Safety Check"}` to `SAFETY_TRANSITIONS`; the new round is N+1 automatically.
- **SCRUM-163:** shows each earlier round's status, remarks and flags (AC4 there).
- **SCRUM-162:** decided events leave the queue already (it lists `Pending Safety Check` only).
- **SCRUM-168:** two more decision notifications, from the same routes.

## Decisions and defaults

From earlier threads and Jira:
- (5 Oct, Clarice, Jira comment) Rejecting the safety arrangement cancels the event entirely.
- (11 Oct, Clarice) Round statuses are `Safety Approved`, `Changes Requested`, `Safety Rejected`; `Approved` is only an event status.
- (13 Oct, Clarice) `/safety-status` is locked to Safety Check Service with the internal token (shipped in SCRUM-150).

Defaults built into this plan:
- (14 Oct, Clarice) Area-level flags only; bookings and equipment requests are untouched on a change request, and SCRUM-164 handles the re-review.
- (14 Oct, Clarice) Safety Check Service releases venue bookings on rejection.
- Equipment is released by the event's `Cancelled` status, which the availability check already honours; no write to `EquipmentRequest`.
- A reason is required for both decisions, plus a "change needed" text per selected area.
- The API itself requires `confirmed: true` on reject.
- Release failures don't undo a rejection; they are reported in the response and logged.

Open questions for Clarice:
1. ~~**On a change request, should flagged bookings and equipment requests be sent back for review now?** (A, recommended) No: record area-level flags only and leave every arrangement as it is, matching AC2's "existing arrangements are preserved"; SCRUM-164 handles the re-review. (B) Yes: reset flagged bookings to `Pending Review` now and add a re-review status to equipment requests, which is what the C3 line "reopens flagged" could be read as, but it touches two more services and overlaps 164.~~ **Answered 14 Oct: (A), flags only; SCRUM-164 handles the re-review.**
2. ~~**Who releases bookings when a rejection cancels an event?** (A, recommended) Safety Check Service, which the C4 diagram already links to Venue Availability. (B) The planned Event Workflow Service ("cascades cancellations"), which is still an open architecture question in AGENTS.md and isn't built, so AC5 would wait on it.~~ **Answered 14 Oct: (A), Safety Check Service releases them. Event Workflow Service's open question in AGENTS.md is untouched by this.**
