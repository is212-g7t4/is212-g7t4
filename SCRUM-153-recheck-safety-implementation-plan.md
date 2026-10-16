# SCRUM-153 Re-check Safety After High-Impact Changes: implementation plan

Oct 14, 2026 · for Clarice Lim · written against `main` at `8c7ad5c`, with the unmerged `SCRUM-151-reject-or-request-changes-to-safety-arrangements` branch (`9bede9f`) and the stale `SCRUM-20-event-information-management-impact-validation` branch (`1242bec`, 19 Sep) read for context

When the assigned Event Coordinator changes a **high-impact** detail (date/time, expected attendance, venue requirements, equipment requirements, accessibility needs) of a **`Confirmed`** event, the safety approval is withdrawn: the approved `SafetyCheck` round is marked **`Approval Withdrawn`** (kept, with who, when and why), a new **`Pending`** round N+1 is opened, and the event moves back to **`Pending Safety Check`** with an action-history line that names the changed fields. A **low-impact** change (name, description, purpose, registration needs) is saved and the event stays `Confirmed`.

The workflow lives in **Safety Check Service (composite)**, which already owns every safety-round write and is the only caller allowed into an event's safety status. **Safety Check Record Service (atomic)** stores the withdrawal and opens the new round; **Event Service (atomic)** owns the field classification, the edit write, and a gate that refuses a high-impact edit of a `Confirmed` event unless it comes through the safety workflow (the same idea as SCRUM-152's gate on `Confirmed`).

> **Decided (16 Oct, Clarice): every recommended option (A) in "Decisions from Clarice" at the end.** The markers **(Q1)**, **(Q2)**, **(Q3)** below point to those answers; build exactly as written.

## Step 0 for the agent: create the branch first

SCRUM-151 is `Done` in Jira but **not on `main` yet** (its branch is 10 commits ahead, including two fixes this story relies on: `b655d77` "a progress save no longer makes the open safety round look stale" and the widened `SAFETY_TRANSITIONS`). Check first:

```
git fetch origin main SCRUM-151-reject-or-request-changes-to-safety-arrangements
git merge-base --is-ancestor origin/SCRUM-151-reject-or-request-changes-to-safety-arrangements origin/main && echo "151 is on main"
```

- If 151 is on `main`: `git checkout -b SCRUM-153-re-check-safety-after-high-impact-changes origin/main`
- If not: branch off the 151 branch instead (`git checkout -b SCRUM-153-re-check-safety-after-high-impact-changes origin/SCRUM-151-reject-or-request-changes-to-safety-arrangements`), open the PR as a draft, and merge `main` in once 151 lands so the PR diff shows only 153's work.

Then `git push -u origin SCRUM-153-re-check-safety-after-high-impact-changes`. Name follows AGENTS.md (`<SCRUM-KEY>-<kebab-case-summary>`). Every commit starts with `SCRUM-153:`; confirm the key with Clarice before the first commit, as AGENTS.md requires. Open the PR into `main`.

## The story (Jira, word for word, read 14 Oct)

> As an Event Coordinator, I want a safety approval to be withdrawn when a high-impact detail changes afterwards, so that the event is never prepared on the basis of an outdated safety review.
>
> 1. Given an event is 'Confirmed', when its date/time, expected attendance, venue requirements, equipment requirements or accessibility needs change, then its status returns to 'Pending Safety Check' and the coordinator is told why.
> 2. Given only a low-impact field changes (name, description, purpose, registration needs), then the event stays 'Confirmed'.
> 3. Given a safety approval is withdrawn, then it stays visible in the event's safety history.

5 points, Sprint 3 (7 to 18 Oct), Medium, To Do, assigned to Clarice. No comments. Origin: `change-6-operational-feasibility/change-6-user-stories-draft.md` §6.10, marked *assumption-based*: "the brief says affected arrangements 'may need to be reviewed again'; extending that to edits after approval is our interpretation." Week 7 change #6: *"The event cannot proceed to preparation until the Safety Officer has approved it."*

### Neighbouring stories this one depends on or touches

| Story | Owner | State | Why it matters here |
| --- | --- | --- | --- |
| **SCRUM-20** Event Information Management & Impact Validation | Justin | In Progress; branch last pushed **19 Sep**, not merged | Defines the *same* low/high-impact split and owns "edit event details". Its AC2 to AC4 check a high-impact edit against existing bookings/equipment and block contradictions. **No edit endpoint exists on `main`.** See Q1. |
| SCRUM-149 / 150 / 152 | Clarice | Done, on `main` | Submit, approve, the gate on `Confirmed`. This story reuses their round model, the `X-Internal-Service-Token` lock and the stale-round check. |
| SCRUM-151 | Clarice | Done in Jira, branch not merged | Widens `SAFETY_TRANSITIONS`, adds flags, and fixes the stale-round check (`b655d77`). Build on it (Step 0). |
| SCRUM-163 Review Event Safety Information | Justin | To Do | Its AC4 shows earlier decisions; a withdrawn round is one of them. |
| SCRUM-164 Revise and Resubmit | Jun Wei | To Do | Owns `Safety Changes Requested → Pending Safety Check`. Unaffected; an edit on a `Safety Changes Requested` event is ordinary rework and withdraws nothing. |
| SCRUM-168 Safety Check Notifications | unassigned | To Do | Its AC1 ("submitted **or resubmitted**") covers telling Safety Officers about the re-check round. Not built here. |
| SCRUM-157 Manage Individual Venue Arrangements | Wai Yee | In Review | Lets a coordinator modify a booking. Whether that should also withdraw approval is Q3. |

## Architecture after Week 7 (from `c4_diagram/`)

- **C2** (`c2.dsl`): Front-End App → one API Application (Flask services) → Supabase / MongoDB Atlas outside the boundary; RabbitMQ for notifications only; Hold Checker job. The Event Coordinator "plans events … and submits safety checks"; the Safety Officer "reviews and decides safety checks".
- **C3** (`c3.dsl`): composite logic is folded into the atomic module that owns the resulting record. **Event Module** "owns the Event entity and coordinates … change/cancellation, and status workflows. Only a safety approval sets Confirmed." **Safety Check Module** "owns safety check records and coordinates the safety-check workflow: submit, review, decide, resubmit"; it "reads event details from, and sets event status via" the Event Module.
- **Service level** (`export/c4.png`): **Safety Check Service (Composite)** sits over **Safety Check (Atomic)** (`SafetyCheck`, `SafetyCheckFlag`). An **Event Workflow Service (Composite)** is also drawn (links to Event, Venue Availability, Equipment Availability, Forum, Notification) with an `EventChangeReq` table, but it is **not built** and AGENTS.md lists "whether Event Workflow Service is needed at all" as an **open architecture question** that must not be resolved silently. See Q2.

What the diagrams settle for this story: every write to a safety round goes through Safety Check (atomic) via Safety Check Service (composite), and only the safety workflow moves an event into or out of the safety statuses. Nothing on the diagram lets Event Service or any other composite write safety rounds.

## Where things stand (main + 151 branch)

| Piece | State | What this story needs from it |
| --- | --- | --- |
| `services/event-service/` (atomic, 5003) | `FIELDS` lists the 9 editable columns. **No endpoint edits them**: `PATCH /events/<id>` only assigns a coordinator, `/progress` only changes status + notes, `/safety-status` only safety moves. `SAFETY_TRANSITIONS` (151 branch) has no move out of `Confirmed`. Stale-round check finds "the latest action entry with status `Pending Safety Check` **and** a `safetyCheckId`" (`b655d77`) | New edit write with the impact classification; a `Confirmed → Pending Safety Check` move that can only happen together with a high-impact edit |
| SCRUM-20 branch (`1242bec`) | `PATCH /events/<id>/update` in the atomic, `LOW_IMPACT_FIELDS` / `HIGH_IMPACT_FIELDS` as here, a placeholder `ARRANGEMENT_CONFLICT_CHECKER`. Written against the old `public.event_service` table and **drops `decisionHistory` / `actionHistory`** when it rewrites `description` | Don't merge it as is. Reuse its field sets and naming; see Q1 |
| `services/safety-check-record-service/` (atomic, 5013) | Statuses `Pending`, `Safety Approved`, `Changes Requested`, `Safety Rejected`. `create_round` refuses while a round is `Pending`; `decide_round`, `reopen_round`, `delete_open_round` exist. No status check constraint in SQL | New `Approval Withdrawn` status, a withdraw-and-reopen endpoint and its undo |
| `SafetyCheck` table | `safety_check_id, event_id, round_number, submitted_by, submitted_at, equipment_placement_notes, crowd_movement_notes, status, decided_by, decided_at, remarks`; `UNIQUE (event_id, round_number)` | One migration adding three nullable withdrawal columns (Q-free default, see "Decisions") |
| `services/safety-check-service/` (composite, 5012) | `POST /safety-checks` (submit), `/approve`; 151 adds `/request-changes`, `/reject`, shared `_decide`, `_compensate*` helpers; holds `INTERNAL_SERVICE_TOKEN` | New `POST /safety-checks/recheck` |
| Attendee side | `GET /events/registration` lists `Confirmed` events only; Attendee Registration Service requires `Confirmed` | **No change.** A re-check closes new registrations until re-approval; existing registrations are untouched (see Decisions) |
| Frontend | No edit UI on `main` (SCRUM-20's pop-up is only on its stale branch). `EventDetailPage` renders action history; `safetyCheck.ts` has submit/approve (151 adds decide calls) | Edit dialog for the assigned coordinator, the withdrawal confirm step, and the history line |

## Which service does what

| Service | Type | Responsibility in SCRUM-153 | Change |
| --- | --- | --- | --- |
| **Safety Check Service** `services/safety-check-service/`, 5012 | Composite | **Owns the re-check workflow.** Checks the caller is the assigned coordinator, the event is `Confirmed`, the edit really changes a high-impact field, and the latest round is `Safety Approved`; then withdraws that round and opens round N+1 (Record), then saves the edit and moves the event (Event, with the internal token); undoes the withdrawal if the event write fails | New `POST /safety-checks/recheck`; new clients `withdraw_safety_approval`, `restore_safety_approval`, `update_event_details`; README |
| **Safety Check Record Service** `services/safety-check-record-service/`, 5013 | Atomic | **Owns the safety history (AC3).** In one transaction: round N `Safety Approved → Approval Withdrawn` with `withdrawn_at`, `withdrawn_by`, `withdrawal_reason` (decision fields kept), and round N+1 inserted as `Pending`, carrying round N's placement/crowd notes forward. Undo endpoint for the composite's compensation | `APPROVAL_WITHDRAWN` status; `POST /safety-check-records/<id>/withdraw`, `POST /safety-check-records/<id>/restore`; serialize the new columns; migration; README |
| **Event Service** `services/event-service/`, 5003 | Atomic | **Owns the event's fields, status and history (AC1, AC2).** Classifies each changed field; saves low-impact edits in place (AC2); refuses a high-impact edit of a `Confirmed` event with `409 SAFETY_RECHECK_REQUIRED` unless it carries the internal token and the new round (gate); with them, saves the fields **and** moves `Confirmed → Pending Safety Check` in the same `FOR UPDATE` transaction and writes the "approval withdrawn because …" history line (AC1 "told why") | `LOW_IMPACT_FIELDS`, `HIGH_IMPACT_FIELDS`; new `PATCH /events/<id>/details` and `update_event_details()` (Q1); history entry; README |
| **Event Management UI** `frontend/event-management-ui/` | React SPA | Edit dialog on the event page for the assigned coordinator; on `SAFETY_RECHECK_REQUIRED`, a confirm step naming the changed fields and the consequence, then the re-check call; success message saying why the status changed; withdrawal line in Action history | `EventEditDialog.tsx` (new), `eventDetails.ts` (new), `safetyCheck.ts`, `EventDetailPage.tsx`, `submission.ts` types |
| `docker-compose.yml` | | `INTERNAL_SERVICE_TOKEN` is already passed to both services | None |
| Venue Availability, Venue Booking, Equipment Request, Equipment Reservation, Venue, Equipment, User, Registration, Attendee Registration, Coordinator Assignment | | Not called. Bookings and equipment requests are left as they are: the Safety Officer re-reviews them in round N+1 | None |
| Event Workflow Service, Forum, Notification, Broker | | Not built. Notification of the re-check round is SCRUM-168. Event Workflow Service's open question is **not** resolved by this plan (Q2) | None |

Why a composite owns this and not Event Service: the withdrawal writes two entities owned by two atomics (`Event`, `SafetyCheck`), and atomics never call each other (AGENTS.md). Same shape as 149, 150 and 151.

## Design

### Field classification (shared with SCRUM-20)

Defined once in `services/event-service/app/models.py`, using SCRUM-20's names so its later work reuses them:

| API field | Column | Impact |
| --- | --- | --- |
| `preferredStartDate`, `preferredEndDate` | `preferred_start_date`, `preferred_end_date` | **High** ("Date/time") |
| `expectedAttendance` | `expected_attendance` | **High** |
| `venueRequirements` | `venue_requirements` | **High** |
| `equipmentRequirements` | `equipment_requirements` | **High** |
| `accessibilityNeeds` | `accessibility_needs` | **High** |
| `eventName` | `event_name` | Low |
| `description`, `purpose` | inside the `description` JSON | Low |
| `registrationNeeds` | `registration_needs` | Low |

```python
LOW_IMPACT_FIELDS = ("eventName", "description", "purpose", "registrationNeeds")
HIGH_IMPACT_FIELDS = (
    "preferredStartDate", "preferredEndDate", "expectedAttendance",
    "venueRequirements", "equipmentRequirements", "accessibilityNeeds",
)
EDITABLE_FIELDS = (*LOW_IMPACT_FIELDS, *HIGH_IMPACT_FIELDS)
# Human labels for the history line and the UI (AC1 "told why").
FIELD_LABELS = {
    "preferredStartDate": "Date/time", "preferredEndDate": "Date/time",
    "expectedAttendance": "Expected attendance",
    "venueRequirements": "Venue requirements",
    "equipmentRequirements": "Equipment requirements",
    "accessibilityNeeds": "Accessibility needs",
    "eventName": "Event name", "description": "Description",
    "purpose": "Purpose", "registrationNeeds": "Registration needs",
}
```

**"Changed" means the normalised value differs**, compared after the same normalisation `serialize` applies: strings stripped; `expectedAttendance` compared as an int; dates compared as naive Singapore-local `datetime`s (`_local(_aware(value))`). Sending the current value back unchanged is not a change, so re-saving the form without edits never withdraws an approval. Both date fields map to one label, so the reason says "Date/time" once.

### Lifecycle after this story

```
Approved ──(149 submit)──► Pending Safety Check ──(150 approve)──► Confirmed
                                  ▲                                    │
                                  └──(153 high-impact edit)────────────┘
                                         round N → Approval Withdrawn
                                         round N+1 opened as Pending
```

`Confirmed` gains exactly one outgoing move, and only through the re-check. `Cancelled` stays terminal (151). `SAFETY_TRANSITIONS` gets `"Confirmed": {"Pending Safety Check"}`, but `/safety-status` must **not** accept it on its own (see Event Service below): the move is only legal when the high-impact edit that justifies it is saved in the same transaction.

### Order of writes

```
UI ── PATCH Event Service /events/<id>/details {coordinatorId, changes:{...}}
        low-impact only, or event not Confirmed   → 200, saved (AC2)
        Confirmed + a high-impact field changed   → 409 SAFETY_RECHECK_REQUIRED
                                                    {changedFields, highImpactFields, labels}
UI shows the confirm step; on confirm:

UI ── POST /safety-checks/recheck {eventId, coordinatorId, changes:{...}}   ──► Safety Check Service
 1. validate body: UUIDs; `changes` an object of EDITABLE_FIELDS only        400, nothing written
 2. GET Event Service /events/<id>?coordinatorId=<c>                         403 not assigned / 404
 3. event.status == Confirmed?                                               409 RECHECK_NOT_NEEDED (currentStatus)
 4. high-impact fields that actually change (same normalisation) non-empty?  409 RECHECK_NOT_NEEDED
 5. GET Record Service /safety-check-records?eventId=<id>   latest round is Safety Approved?
                                                                             409 NO_APPROVED_SAFETY_CHECK
 6. POST Record Service /safety-check-records/<roundN>/withdraw
        {withdrawnBy: <c>, reason: "<labels> changed after safety approval."}
        → {withdrawn: round N, opened: round N+1 (Pending)}                  409 ROUND_NOT_APPROVED / NOT_LATEST_ROUND
 7. PATCH Event Service /events/<id>/details   (X-Internal-Service-Token)
        {coordinatorId, changes, safetyRecheck:{withdrawnSafetyCheckId: N.id,
                                                safetyCheckId: N+1.id, roundNumber: N+1}}
        on any failure → POST Record Service /safety-check-records/<roundN>/restore
                          {openedSafetyCheckId: N+1.id}
 8. 200 {event, safetyCheck: round N+1, withdrawnSafetyCheck: round N, changedFields, reason}
```

**Record first, then event**, as in 149 to 151: the record service's `FOR UPDATE` on the event's latest round is the race guard, so two concurrent re-checks can't both open round N+1 (the second gets `409 ROUND_NOT_APPROVED`).

**Event Service re-checks everything under its own lock** (step 7): status still `Confirmed`; the latest approval entry in `actionHistory` (status `Confirmed` with a `safetyCheckId`) names `withdrawnSafetyCheckId`, else `409 STALE_SAFETY_CHECK`; at least one high-impact field still changes. So an edit landing between steps 2 and 7 can't leave a mismatched state, and a made-up round id can't move the event.

**Why the UI calls Event Service first**: Event Service is the single authority on what is high-impact, and the low-impact path (AC2) must work with no safety call at all. The `409` carries everything the confirm step needs. A client that skips the UI still can't change a `Confirmed` event's high-impact fields without the safety workflow: that's the gate.

**Compensation** (`restore`): deletes round N+1 only if it is still `Pending` and still the latest, and sets round N back to `Safety Approved` with the three withdrawal columns cleared. If the restore itself fails, log at ERROR with both ids and return the original failure; the README gets the `curl` to do it by hand (same approach as `_compensate`).

### Safety Check Record Service (atomic)

Migration `database/supabase/migrations/<timestamp>_safety_check_withdrawal.sql`:

```sql
ALTER TABLE public."SafetyCheck"
    ADD COLUMN IF NOT EXISTS withdrawn_at timestamptz,
    ADD COLUMN IF NOT EXISTS withdrawn_by uuid,
    ADD COLUMN IF NOT EXISTS withdrawal_reason text;
```

Nullable, no backfill; existing rows are untouched. (Apply it to the shared Supabase project only when Clarice says so; unit tests mock `psycopg2` and don't need it.)

`app/models.py`:

```python
APPROVAL_WITHDRAWN = "Approval Withdrawn"
RECORD_STATUSES = (PENDING, SAFETY_APPROVED, CHANGES_REQUESTED, SAFETY_REJECTED, APPROVAL_WITHDRAWN)
COLUMNS += ", withdrawn_at, withdrawn_by, withdrawal_reason"

class RoundNotApprovedError(Exception): ...   # round N isn't 'Safety Approved'

def withdraw_approval(database_url, safety_check_id, withdrawn_by, reason):
    # one transaction:
    # SELECT ... WHERE safety_check_id = %s FOR UPDATE         → 404 if missing
    # _latest_round(cursor, event_id, lock=True) must be this one → RoundNotLatestError
    # status must be SAFETY_APPROVED                           → RoundNotApprovedError
    # UPDATE ... SET status = 'Approval Withdrawn', withdrawn_at = now(),
    #        withdrawn_by = %s, withdrawal_reason = %s   (decided_by/decided_at/remarks kept)
    # INSERT round_number + 1, status 'Pending', submitted_by = withdrawn_by,
    #        submitted_at = now(), equipment_placement_notes / crowd_movement_notes copied from round N
    # return (withdrawn, opened)

def restore_approval(database_url, safety_check_id, opened_safety_check_id):
    # one transaction: round N must be 'Approval Withdrawn'; opened round must be
    # round N+1, same event, still 'Pending' → DELETE it; set round N back to
    # 'Safety Approved', withdrawn_* = NULL. Idempotent: if N is already
    # 'Safety Approved' and N+1 is gone, return N unchanged.
```

`serialize` adds `withdrawnAt`, `withdrawnBy`, `withdrawalReason` (null when not withdrawn). Every round response carries them, which is what SCRUM-163 AC4 reads.

`app/__init__.py`:

| Route | Body | Responses |
| --- | --- | --- |
| `POST /safety-check-records/<id>/withdraw` | `{withdrawnBy: uuid, reason: non-blank ≤ 2000}` | `201 {withdrawn, opened}`; `400` bad body; `404`; `409 ROUND_NOT_APPROVED` (with `currentStatus`); `409 NOT_LATEST_ROUND`; `503` |
| `POST /safety-check-records/<id>/restore` | `{openedSafetyCheckId: uuid}` | `200 {round}`; `400`; `404`; `409 NOT_RESTORABLE` (N+1 already decided or not N+1); `503` |

Both are for Safety Check Service only (README says so, like `reopen`). `decide_round` must keep refusing an `Approval Withdrawn` round (it already refuses anything not `Pending`; add a test).

### Event Service (atomic)

`app/models.py`:

```python
SAFETY_TRANSITIONS = {
    "Approved": {"Pending Safety Check"},
    "Pending Safety Check": {"Confirmed", "Safety Changes Requested", "Cancelled"},
    # SCRUM-153: only together with a high-impact edit, via update_event_details.
    # PATCH /safety-status refuses it (see RECHECK_ONLY_MOVES).
    "Confirmed": {"Pending Safety Check"},
}
RECHECK_ONLY_MOVES = {("Confirmed", "Pending Safety Check")}

class SafetyRecheckRequiredError(Exception):   # carries changed_fields
class EventNotEditableError(Exception):        # carries current_status

EDITABLE_STATUSES = (
    "Submitted", "Under Review", "Approved",
    "Safety Changes Requested", "Confirmed",
    "Pending Safety Check",   # low-impact only, see Q3 (decided)
)

def update_event_details(database_url, event_id, coordinator_id, changes,
                         safety_recheck=None, internal=False):
```

Inside one `SELECT … FOR UPDATE`:

1. Not found → `EventNotFoundError`; not the assigned coordinator → `EventNotAssignedError` (first, as elsewhere, so a stranger learns nothing).
2. Status not in `EDITABLE_STATUSES` (`Rejected`, `Cancelled`) → `EventNotEditableError`.
3. Merge `changes` over `serialize(event)`, run `validation.validate` on the merged values (same rules as submit: required fields, attendance range, end after start) → `ValueError({missingFields, errors})` → `400`.
4. `changed = [f for f in changes if normalised(new) != normalised(old)]`; `high = [f for f in changed if f in HIGH_IMPACT_FIELDS]`. Nothing changed → return the event unchanged (`200`, no history line).
5. **Gate.** If status is `Confirmed` and `high`:
   - no `safety_recheck` or not `internal` → `SafetyRecheckRequiredError(high)` → `409 SAFETY_RECHECK_REQUIRED`.
   - with both: the latest `actionHistory` entry with status `Confirmed` and a `safetyCheckId` must equal `safety_recheck["withdrawnSafetyCheckId"]`, else `StaleSafetyCheckError`.
6. If status is `Pending Safety Check` and `high` → `409 EVENT_UNDER_SAFETY_REVIEW` ("This event is waiting for its Operational Safety Check. Change date/time, attendance, venue, equipment or accessibility details after the Safety Officer's decision.") **(Q3, decided)**.
7. Write the columns (`expected_attendance` as int, dates through `_aware`), rebuild `description` JSON **preserving `decision`, `decisionHistory`, `actionDetails`, `actionHistory`** (the SCRUM-20 branch loses these; don't copy that), and append one action entry:

```python
# low-impact edit, or any edit on a non-Confirmed event: status unchanged
{"status": event_status, "details": "Event details updated: Event name, Purpose.",
 "changedFields": changed, "coordinatorId": coordinator_id, "recordedAt": now}

# re-check (AC1): status → 'Pending Safety Check'
{"status": "Pending Safety Check",
 "details": "Safety approval withdrawn because Date/time and Expected attendance "
            "changed after approval. The event needs a new Operational Safety "
            "Check (round 3) before it can proceed to preparation.",
 "changedFields": changed, "highImpactFields": high,
 "coordinatorId": coordinator_id,
 "withdrawnSafetyCheckId": safety_recheck["withdrawnSafetyCheckId"],
 "safetyCheckId": safety_recheck["safetyCheckId"],      # round N+1: approve/151's
 "recordedAt": now}                                      # stale-round check finds this
```

The re-check entry carries `safetyCheckId` deliberately: SCRUM-150/151's stale-round check identifies the open round as the latest `Pending Safety Check` entry with a `safetyCheckId`, so the Safety Officer can approve, reject or request changes on round N+1 with **no change** to those code paths. Add a test that pins this.

`app/__init__.py`, new `PATCH /events/<uuid:event_id>/details`:

- Body `{coordinatorId: uuid, changes: {<EDITABLE_FIELDS>: text}, safetyRecheck?: {withdrawnSafetyCheckId, safetyCheckId: uuid, roundNumber: int ≥ 1}}`. Unknown keys in `changes` → `400`; empty `changes` → `400`; values must be text (as submit).
- `internal` is true only when `INTERNAL_SERVICE_TOKEN` is configured and `X-Internal-Service-Token` matches (`hmac.compare_digest`), the same opt-in lock as `/safety-status`. When the token isn't configured, treat `safetyRecheck` as sufficient (dev behaviour matches `/safety-status` today) and log the existing warning.
- Responses: `200` event; `400`; `403` not assigned; `404`; `409 EVENT_NOT_EDITABLE` (`currentStatus`); `409 SAFETY_RECHECK_REQUIRED` with `changedFields`, `highImpactFields`, `labels` and the message "Changing Date/time, Expected attendance will withdraw this event's safety approval. It will return to Pending Safety Check."; `409 EVENT_UNDER_SAFETY_REVIEW`; `409 STALE_SAFETY_CHECK`; `503`.
- CORS needs no change (`PATCH` is already allowed). `X-Internal-Service-Token` stays out of `Access-Control-Allow-Headers`, so a browser can't send it.

`PATCH /events/<id>/safety-status`: refuse any move in `RECHECK_ONLY_MOVES` with `409 INVALID_SAFETY_TRANSITION` before touching the database, so `Confirmed → Pending Safety Check` without an edit stays impossible. `update_event_safety_status` gets the same guard (belt and braces; tests hit both).

### Safety Check Service (composite)

`app/clients.py`:

- `update_event_details(event_id, coordinator_id, changes, safety_recheck)` → `PATCH {EVENT_SERVICE_URL}/events/<id>/details` with the token header. `409` → `ConflictError(code, body)`; `403/404` mapped as `set_event_safety_status` does.
- `withdraw_safety_approval(round_id, withdrawn_by, reason)` → `POST …/safety-check-records/<id>/withdraw`; `409` → `ConflictError`.
- `restore_safety_approval(round_id, opened_round_id)` → `POST …/restore`.

`app/routes.py`, `POST /safety-checks/recheck` following the order of writes above. Constants `CONFIRMED`, `PENDING_SAFETY_CHECK`, `SAFETY_APPROVED`, and `HIGH_IMPACT_FIELDS` / `FIELD_LABELS` copied from Event Service (no shared package, AGENTS.md; comment that they mirror `event-service/app/models.py`). The composite's step 4 is an early, friendly check only; Event Service's step 7 is the authority.

| Case | Status | Body `code` |
| --- | --- | --- |
| Re-checked | `200` | `{event, safetyCheck, withdrawnSafetyCheck, changedFields, reason}` |
| Bad UUIDs, `changes` missing/empty/not an object, unknown field | `400` | |
| Caller not the assigned coordinator | `403` | |
| Event not found | `404` | |
| Event not `Confirmed`, or no high-impact field changes | `409` | `RECHECK_NOT_NEEDED`, with `currentStatus` |
| Latest round not `Safety Approved` (data drift) | `409` | `NO_APPROVED_SAFETY_CHECK` |
| Concurrent re-check won the race | `409` | `ROUND_NOT_APPROVED` (from Record) |
| Event Service refused step 7 (validation `400`, `STALE_SAFETY_CHECK`, …) | its status, after `restore` | passed through |
| Downstream timeout / error | `504` / `502` (after `restore` if step 6 ran) | |

No readiness re-check of bookings/equipment here: round N+1 is reviewed by the Safety Officer as it stands, and if the change makes a booking unsuitable the officer requests changes (151) and SCRUM-164 takes over.

### Frontend (`frontend/event-management-ui/`)

1. `src/features/event/eventDetails.ts` (new): `HIGH_IMPACT_FIELDS`, `FIELD_LABELS` (mirror Event Service), `updateEventDetails(eventId, coordinatorId, changes)` → `PATCH {VITE_EVENT_SERVICE_URL}/events/<id>/details`; returns `{event}` or throws a typed `SafetyRecheckRequired {highImpactFields, labels, message}` on that `409`.
2. `src/features/safety/safetyCheck.ts`: `recheckSafety({eventId, coordinatorId, changes})` → `POST /safety-checks/recheck`; `SafetyCheckRecord` gains `withdrawnAt`, `withdrawnBy`, `withdrawalReason`; status union gains `'Approval Withdrawn'`.
3. `src/features/event/EventEditDialog.tsx` (new): reuses `EventRequestForm`'s field components and validation messages, prefilled from the event; fields grouped "Safety-relevant details" (high) and "Other details" (low), with a one-line note on `Confirmed` events: "Changing safety-relevant details withdraws the safety approval." Sends only fields the user changed.
   - On `SafetyRecheckRequired`: a confirm step, **"Withdraw safety approval?"** "You changed Date/time and Expected attendance. This event will go back to Pending Safety Check and can't proceed to preparation until a Safety Officer approves it again. New attendee registrations close until then." Buttons **Save and withdraw approval** / **Go back**. Confirm → `recheckSafety`.
   - Success: low-impact → "Event details saved."; re-check → "Saved. Safety approval withdrawn because Date/time and Expected attendance changed. The event is back to Pending Safety Check." (AC1 "told why").
   - On `EVENT_UNDER_SAFETY_REVIEW` show the message inline. Any other error shows its `message`.
4. `src/pages/EventDetailPage.tsx`: **Edit details** button for the assigned coordinator on any `EDITABLE_STATUSES` event; hidden for `Rejected` / `Cancelled` and for other roles. After save, refresh the event. In Action history, render `changedFields` (as labels) under an entry's `details`; a withdrawal entry gets a "Safety approval withdrawn" tag (AC3, event side).
5. `src/features/event/submission.ts`: `EventAction` gains optional `changedFields?: string[]`, `highImpactFields?: string[]`, `withdrawnSafetyCheckId?: string`.
6. `eventStatus.ts`: no change.

If SCRUM-20 lands its own edit pop-up first (Q1), wire steps 3 to 5 into that component instead of creating a second one.

## Tests

Every test name or docstring cites the AC (e.g. "SCRUM-153 AC1: …"). Unit tests are hermetic (pytest-socket); mock `psycopg2.connect` and `httpx` as the existing safety tests do. File names are story-based.

### Event Service: new `tests/unit/test_event_details_recheck.py`

| Test | AC |
| --- | --- |
| `Confirmed`, change each high-impact field alone (parametrised over all six) without token/`safetyRecheck` → `409 SAFETY_RECHECK_REQUIRED` naming that field; only the `SELECT` ran | AC1 (gate) |
| `Confirmed`, valid token + matching `withdrawnSafetyCheckId` → `200`; one `UPDATE` sets the columns **and** `status = 'Pending Safety Check'`; history entry has `details` naming the labels, `changedFields`, `highImpactFields`, `withdrawnSafetyCheckId`, `safetyCheckId`, `coordinatorId`, `recordedAt` | AC1 |
| Start and end both changed → "Date/time" appears once in `details` | AC1 |
| `Confirmed`, each low-impact field (parametrised, incl. `description` and `purpose` inside the JSON) → `200`, status still `Confirmed`, no safety fields in the entry | AC2 |
| Mixed low + high on `Confirmed` without token → `409`, **nothing** saved (not even the low-impact part) | AC1 / AC2 |
| Same value resent (`"120"` vs `120`, `" Hall A "` vs `"Hall A"`, same date in another ISO spelling) → `200`, no status change, no history entry | AC2 |
| `decision`, `decisionHistory`, `actionDetails` and earlier `actionHistory` survive every edit | regression |
| Wrong `withdrawnSafetyCheckId` → `409 STALE_SAFETY_CHECK` | race |
| After a re-check, `update_event_safety_status(... "Confirmed", safety_check_id=<round N+1>)` succeeds (the approve path finds the new round) | AC1 → 150 |
| `PATCH /safety-status` `Confirmed → Pending Safety Check` → `409 INVALID_SAFETY_TRANSITION`, nothing written | gate |
| `Pending Safety Check` + high-impact → `409 EVENT_UNDER_SAFETY_REVIEW`; + low-impact → `200` | Q3 (decided) |
| `Approved`, `Under Review`, `Safety Changes Requested` + high-impact → `200`, status unchanged (no approval to withdraw) | AC1 scope |
| `Rejected` / `Cancelled` → `409 EVENT_NOT_EDITABLE` | |
| Not assigned → `403` before any status logic; not found → `404`; bad body / unknown field / empty `changes` / invalid merged values (end before start, attendance 0) → `400` | |
| Token configured but missing/wrong on a `safetyRecheck` call → `409 SAFETY_RECHECK_REQUIRED` | gate |

Update `test_safety_gate.py` / `test_safety_submit_status.py` parametrisations that assert `Confirmed` has no outgoing safety move: it now has one, reachable only through `/details`. Keep `test_only_pending_safety_check_leads_into_confirmed` green.

### Safety Check Record Service: new `tests/unit/test_safety_withdrawal.py`

| Test | AC |
| --- | --- |
| Withdraw latest `Safety Approved` round → `201`; one `UPDATE` (status, `withdrawn_*`; decision fields untouched) and one `INSERT` of round N+1 `Pending` with notes copied, same connection | AC1, AC3 |
| Withdraw a `Pending` / `Changes Requested` / `Safety Rejected` / already `Approval Withdrawn` round → `409 ROUND_NOT_APPROVED`, no `INSERT` | race |
| Withdraw a round that isn't the latest → `409 NOT_LATEST_ROUND` | |
| Blank / 2001-char reason, bad UUID → `400`, no SQL; missing round → `404` | |
| `GET /safety-check-records?eventId=` returns the withdrawn round with `withdrawnAt/By/Reason` and the new `Pending` round, newest first | AC3 |
| `restore` deletes N+1 and resets N; refuses when N+1 was decided; idempotent on a second call | compensation |
| `decide` on an `Approval Withdrawn` round → `409 SAFETY_CHECK_ALREADY_DECIDED` | AC3 |

### Safety Check Service: new `tests/unit/test_safety_recheck.py`

| Test | AC |
| --- | --- |
| Happy path: event read as coordinator, rounds listed, withdraw called with the label reason, `/details` called with `changes`, `safetyRecheck` and the token; `200` body shape | AC1, AC3 |
| Event not `Confirmed` (parametrised) or only low-impact changes → `409 RECHECK_NOT_NEEDED`, no writes | AC2 |
| Not assigned → `403`; not found → `404`; bad body → `400`; all with no writes | |
| Latest round not `Safety Approved` → `409 NO_APPROVED_SAFETY_CHECK`; withdraw `409` passed through, no event call | race |
| Event write fails (`400`, `409 STALE_SAFETY_CHECK`, `502`, timeout) → `restore` called with both ids, original status returned | compensation |
| `restore` also fails → ERROR log with both ids, original failure returned | compensation |
| Never calls Venue Availability, Equipment Request or User Service | scope |
| `test_clients.py`: the three new clients, token header sent, error mapping | |

Safety Check Service and Safety Check Record Service sit at `fail_under = 100`; keep them there. Raise Event Service's floor if this lifts it.

### Frontend

- Vitest `eventDetails.test.ts`: URL, body, `SafetyRecheckRequired` thrown on that `409` code only.
- Vitest `EventEditDialog.test.tsx`: sends only changed fields; low-impact save shows "Event details saved."; on `SafetyRecheckRequired` shows the confirm step listing the labels, **Go back** sends nothing more, **Save and withdraw approval** calls `recheckSafety` with the same `changes` and shows the "because … changed" message (AC1); `EVENT_UNDER_SAFETY_REVIEW` message shown.
- Vitest `EventDetailPage.test.tsx`: Edit button only for the assigned coordinator and not on `Rejected`/`Cancelled`; withdrawal entry renders the tag and changed fields (AC3).
- Playwright `e2e/safety-recheck.spec.ts` (mock every call via `mock()` in `e2e/fixtures.ts`): coordinator opens a `Confirmed` event, renames it (stays `Confirmed`, AC2), then changes expected attendance, confirms, and the badge shows `Pending Safety Check` with the reason (AC1) and the history line (AC3). The existing `safety-*` specs must pass unchanged.

### Manual check (for the Jira attachment)

With `npm run dev` from the repo root: take a `Confirmed` test event (submit and approve one via SCRUM-149/150 if none). As its coordinator, change the name: still `Confirmed`. Change expected attendance and confirm: `Pending Safety Check`, reason shown, Action history line present. In Supabase, `SafetyCheck` shows round N `Approval Withdrawn` (with `withdrawn_*`) and round N+1 `Pending`. As Nurul Huda (Safety Officer), approve round N+1: back to `Confirmed`. Then `curl -X PATCH localhost:5003/events/<id>/details` with a high-impact change and no token (with the token configured) returns `409 SAFETY_RECHECK_REQUIRED`. Restore any data you changed.

## Task breakdown

| # | Task | Service | Depends on | Est. (h) |
| --- | --- | --- | --- | --- |
| 0 | Branch (Step 0) | Git | | 0.1 |
| 1 | Migration; `APPROVAL_WITHDRAWN`; `withdraw` / `restore` endpoints; serialize new columns; tests at 100%; README | Safety Check Record (atomic) | 0 | 2 |
| 2 | Field classification; `PATCH /events/<id>/details` and `update_event_details` with the gate, history entries, metadata preserved; `/safety-status` refuses the re-check-only move; tests; README | Event (atomic) | 0 | 3 |
| 3 | `POST /safety-checks/recheck`, three clients, compensation, tests at 100%, README | Safety Check (composite) | 1, 2 | 2 |
| 4 | `eventDetails.ts`, `EventEditDialog`, confirm step, `EventDetailPage` button + history rendering, types | UI | API contracts above | 2.5 |
| 5 | Vitest + Playwright | UI | 4 | 1.5 |
| 6 | Docs: `INDEX.md` Event/Safety Check/Safety Check Record rows; `docs/db-structure.md` `SafetyCheck` withdrawal columns and status; C3 Safety Check line "…submit, review, decide, resubmit, **and re-open after a high-impact change**"; `c4.png` `SafetyCheck` table (ask Claire, SCRUM-169 owner, or note it in the PR) | Repo | 3 | 0.5 |
| 7 | `npm run test:backend`, PR, CI green, manual evidence, Jira | All | 1 to 6 | 1 |

About 12.5 hours. Backend tasks 1 and 2 can run in parallel; 4 and 5 can start once the contracts above are accepted.

## Not in this story

- **Contradiction checks against existing bookings/equipment** on a high-impact edit (SCRUM-20 AC2 to AC4). When SCRUM-20 builds them, they run *before* this story's gate; this story neither blocks nor depends on them.
- **Notifying Safety Officers** that a re-check round is waiting: SCRUM-168 AC1 ("submitted or resubmitted"). Publish after step 7; a failure must not undo the re-check.
- **A safety-history panel** listing every round: SCRUM-163 AC4. This story stores the history (record + event entry) and shows the event-side line.
- **Withdrawing approval when a venue booking or equipment request changes** on a `Confirmed` event (SCRUM-157 edits, equipment edits). Q3.
- **Attendee impact.** Existing registrations stay; new registrations close while the event is `Pending Safety Check` because both the catalogue and Attendee Registration Service require `Confirmed`. No code change; noted in the confirm text.
- **Event Workflow Service.** Not built and not resolved here (Q2).

## Decisions and defaults

From earlier threads and Jira:
- (11 Oct, Clarice) Round statuses use the Jira wording; `Approved` is only an event status.
- (13 Oct, Clarice) `/safety-status` is locked to Safety Check Service with the internal token (opt-in).
- (14 Oct, Clarice) SCRUM-164 owns re-review of flagged arrangements and the `Safety Changes Requested → Pending Safety Check` move.

Defaults built into this plan:
- Only `Confirmed` events have an approval to withdraw. Edits on `Approved`, `Under Review` and `Safety Changes Requested` save normally.
- "Changed" is decided on normalised values, so resaving unchanged values never withdraws.
- A withdrawal is stored as `Approval Withdrawn` on the approved round plus three nullable columns (one small migration), and a new `Pending` round N+1 carries the earlier notes forward. The original decision fields are kept, so the history shows who approved, when, and why it was withdrawn (AC3).
- The coordinator confirms before an approval is withdrawn; the API itself also requires the safety workflow (the gate), so skipping the UI can't bypass it.
- No readiness re-check of bookings/equipment on a re-check; the Safety Officer reviews round N+1 as it stands.

## Decisions from Clarice (16 Oct)

All three answered "go with all recommended options":

1. **Edit endpoint (Q1): (A).** SCRUM-153 adds the minimal `PATCH /events/<id>/details` in Event Service with the field classification and the gate. SCRUM-20 (Justin) later adds its contradiction checks in front of it and reuses the UI. Tell Justin in the PR description, since his stale branch defines a different route (`/update`) for the same thing.
2. **Where the re-check lives (Q2): (A).** Safety Check Service (composite). The Event Workflow Service question in AGENTS.md stays open; this plan doesn't touch it.
3. **Scope (Q3): (A).** Only the five event fields in AC1 withdraw approval, and only on `Confirmed` events. High-impact edits are blocked while an event is `Pending Safety Check` (`409 EVENT_UNDER_SAFETY_REVIEW`). Venue booking and equipment request changes on a `Confirmed` event stay out of scope.
