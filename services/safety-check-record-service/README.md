# safety-check-record-service

Atomic service (port **5013**) owning `public."SafetyCheck"` — the Operational
Safety Check records for the safety-check workflow (change #6). One row per
**review round**, so earlier decisions stay visible as history rather than
being overwritten (see [`docs/db-structure.md`](../../docs/db-structure.md)).

It owns the records only. The workflow around them — who may submit, whether
the event's venue bookings and equipment requests are approved, and moving the
event's status — lives in
[`safety-check-service`](../safety-check-service/), the composite. As an atomic
this service calls no other service (AGENTS.md).

## Endpoints

| Method | Path | What it does |
|---|---|---|
| `GET` | `/health` | `{"status": "ok"}` |
| `POST` | `/safety-check-records` | Opens the next round for an event (SCRUM-149) |
| `GET` | `/safety-check-records?eventId=<uuid>[&status=<status>]` | An event's rounds, newest first |
| `DELETE` | `/safety-check-records/<id>` | Removes an undecided round — compensation only, see below |
| `PATCH` | `/safety-check-records/<id>/decision` | Decides the open round (SCRUM-150) |
| `POST` | `/safety-check-records/<id>/reopen` | Undoes a decision — compensation only, see below |
| `POST` | `/safety-check-records/<id>/withdraw` | Withdraws an approval and opens the next round (SCRUM-153) |
| `POST` | `/safety-check-records/<id>/restore` | Undoes a withdrawal — compensation only, see below |

### `POST /safety-check-records`

Body: `{eventId, submittedBy, equipmentPlacementNotes, crowdMovementNotes}`.
Both note fields are optional, up to 2000 characters each; blank or
whitespace-only notes are stored as `NULL`.

**The round rule.** The new round's number is one past the event's latest
round, and a new round is refused while the latest one is still `Pending`:

- `201` with the record (`status` `Pending`, `submittedAt` set by the database).
- `409 {"code": "SAFETY_CHECK_ALREADY_PENDING", "safetyCheck": {...}}` when a
  round is already open — SCRUM-149 AC4's "no duplicate safety check". The open
  round comes back in the body so the caller can say when it was submitted.
- `400` for a non-UUID id, non-text notes or notes over 2000 characters.
- `503` when `DATABASE_URL` is unset or the database is unreachable.

Both the round number and the open-round check are decided in **one
transaction**, under `FOR UPDATE` on the event's latest round. For a first
submission there is no row to lock, so `UNIQUE (event_id, round_number)`
(`safety_check_event_round_key`) is the backstop: the losing insert's
`UniqueViolation` is caught and answered with the same `409`.

### `PATCH /safety-check-records/<id>/decision`

Body: `{status, decidedBy, remarks?, flags?}`. `status` is one of
`DECISION_STATUSES`: `Safety Approved`, `Changes Requested`, `Safety Rejected`.
Per-status rules, checked before the database is touched:

| `status` | `remarks` | `flags` |
| --- | --- | --- |
| `Safety Approved` | optional | absent or `[]` |
| `Changes Requested` | required, non-blank | `{area, changeRequired, equipmentRequestId?}` items; scope rules below |
| `Safety Rejected` | required, non-blank | absent or `[]` |

`remarks` is text up to 2000 characters. Each flag's `area` is one of
`FLAG_AREAS` (`"venue arrangement"`, `"technical arrangement"`,
`"event details"`) and `changeRequired` is non-blank text up to 2000
characters. Area-wide flags have null `bookingId` / `equipmentRequestId`.
Technical flags may identify an individual equipment request instead.
Venue flags may identify a specific `bookingId`, stored in `booking_id`;
distinct targeted venue flags follow the same duplicate and scope rules.

Technical flags can also carry `equipmentRequestId`, stored in
`equip_request_id`. Multiple flags for distinct equipment requests in the
same technical area are supported (up to 500 flags). Duplicate targets and
mixing an area-wide flag with individual flags for that area are rejected.
Event ownership is checked by Safety Check Service before this write.

The round is selected `FOR UPDATE` first, so this is also the race guard for
SCRUM-150 AC3 / SCRUM-151 AC7: if two Safety Officers decide the same round at
once, only one `UPDATE` can see it still `Pending`. The decision and its flags
are written in one transaction.

- `200` with the decided record (`decidedBy`, `decidedAt = now()`, `remarks`,
  `flags`).
- `404` when the round doesn't exist.
- `409 {"code": "SAFETY_CHECK_ALREADY_DECIDED", "safetyCheck": {...}}` when the
  round is no longer `Pending` — the race's loser, or a stale retry.
- `409 {"code": "NOT_LATEST_ROUND"}` when a later round exists for the event.
- `400` for a bad UUID, an unlisted `status`, remarks that aren't text, are
  over 2000 characters or are missing for a change/reject decision, or flags
  that break any rule above.
- `503` when `DATABASE_URL` is unset or the database is unreachable.

### `POST /safety-check-records/<id>/reopen` is for compensation only

Body: `{decidedAt}`, the value `PATCH .../decision` returned. Safety Check
Service calls this when it decided a round and then could not move the event
(for example, the event's status changed underneath it). `decidedAt` must
match the round's current `decidedAt` exactly, so this can only undo the
decision the same request just made — never an older, unrelated decision.
Reopening also deletes the round's `SafetyCheckFlag` rows, since they belong
to the decision being undone.
`409` if the round isn't decided or `decidedAt` doesn't match; `404` if
missing.

### `POST /safety-check-records/<id>/withdraw`

Body: `{withdrawnBy, reason}`. `reason` is required, non-blank text up to 2000
characters — it is what SCRUM-153 AC1's "the coordinator is told why" quotes.

A high-impact change to a `Confirmed` event invalidates its safety approval
(SCRUM-153). In **one transaction** this:

1. turns round N from `Safety Approved` into `Approval Withdrawn`, setting
   `withdrawn_at = now()`, `withdrawn_by` and `withdrawal_reason`, and
   **keeping** `decided_by`, `decided_at` and `remarks` — AC3's "the approval
   stays visible in the event's safety history" means the Safety Officer's
   original decision is still readable, with the withdrawal recorded next to it;
2. inserts round N+1 as `Pending`, carrying round N's
   `equipment_placement_notes` / `crowd_movement_notes` forward and recording
   the withdrawing coordinator as its `submitted_by`.

The round is selected `FOR UPDATE`, and the latest-round check runs under the
same lock, so two simultaneous re-checks can't both open round N+1 — the second
finds round N no longer `Safety Approved`.

- `201 {"withdrawn": {...}, "opened": {...}}`.
- `404` when the round doesn't exist.
- `409 {"code": "ROUND_NOT_APPROVED", "currentStatus", "safetyCheck"}` when the
  round isn't `Safety Approved` — including when it is already
  `Approval Withdrawn`, which is the race's loser.
- `409 {"code": "NOT_LATEST_ROUND"}` when a later round exists: an older
  round's approval is history, not the one in force.
- `400` for a bad UUID, a missing/blank `reason` or one over 2000 characters,
  or a non-boolean `openNextRound`.
- `503` when `DATABASE_URL` is unset or the database is unreachable.

**`openNextRound: false`** (SCRUM-28 Part B) does step 1 only and returns
`{"withdrawn": {...}, "opened": null}`. It is used when a venue booking of a
`Confirmed` event changes: the event goes back to `Approved` rather than
straight to a new round, because Venue Staff must re-review the booking
first; the coordinator's later SCRUM-149 submit opens round N+1. Omitted, it
defaults to `true`, which is SCRUM-153's behaviour above.

Safety Check Service is the only caller — it is the service that checks the
caller is the assigned coordinator, that the event is `Confirmed`, and that a
high-impact field really changed.

### `POST /safety-check-records/<id>/restore` is for compensation only

Body: `{openedSafetyCheckId}`, the round N+1 `withdraw` returned. Safety Check
Service calls this when it withdrew an approval and then could not save the
edit and move the event — otherwise the event would read `Confirmed` with its
approval withdrawn.

It deletes round N+1 only while that round is still `Pending` and really is
round N+1 of the same event, then sets round N back to `Safety Approved` with
the three withdrawal columns cleared. Idempotent: a second call, where round N
is already approved and N+1 is gone, returns round N unchanged.

**`{"nextRoundOpened": false}`** (SCRUM-28 Part B) undoes an
`openNextRound: false` withdrawal: there is no round to delete, so
`openedSafetyCheckId` must be omitted, and round N must still be the event's
latest round — so this can never un-withdraw an approval whose round N+1
exists.

`409 {"code": "NOT_RESTORABLE"}` if round N isn't withdrawn, or the round named
has since been decided or isn't the one this withdrawal opened; `404` if round N
is missing. It is not a general "un-withdraw" endpoint.

### `DELETE /safety-check-records/<id>` is for compensation only

There is no distributed transaction across services. Safety Check Service
creates the round first and then moves the event to `Pending Safety Check`; if
that second step fails, it deletes the round it just created so the event isn't
left with an open round it doesn't know about. That is the only caller.

It refuses anything else: a round that has been decided returns `409`, and a
missing one `404`. Nothing here is a user-facing "withdraw my safety check" —
that is `withdraw` above, which keeps the round rather than deleting it.

## Record JSON

```json
{
  "id": "<uuid>", "eventId": "<uuid>", "roundNumber": 1,
  "submittedBy": "<uuid>", "submittedAt": "2026-10-11T07:30:00+00:00",
  "equipmentPlacementNotes": "Speakers either side of the stage.",
  "crowdMovementNotes": "Entry through Door A.",
  "status": "Pending", "decidedBy": null, "decidedAt": null, "remarks": null,
  "withdrawnAt": null, "withdrawnBy": null, "withdrawalReason": null,
  "flags": []
}
```

The three `withdrawn*` fields are on **every** round (null unless that round's
approval was withdrawn), which is what SCRUM-163 AC4 reads. A withdrawn round
keeps its decision fields alongside them:

```json
{"roundNumber": 2, "status": "Approval Withdrawn",
 "decidedBy": "<uuid>", "decidedAt": "2026-10-14T02:00:00+00:00",
 "remarks": "Looks safe.",
 "withdrawnAt": "2026-10-16T06:00:00+00:00", "withdrawnBy": "<uuid>",
 "withdrawalReason": "Date/time and Expected attendance changed after safety approval."}
```

A decided `Changes Requested` round carries one flag per selected area:

```json
{"id": "<uuid>", "area": "venue arrangement", "bookingId": null,
 "equipmentRequestId": null, "changeRequired": "Move the stage left of centre."}
```

`status` is one of `Pending`, `Safety Approved`, `Changes Requested`,
`Safety Rejected`, `Approval Withdrawn` (`RECORD_STATUSES` in
[`app/models.py`](app/models.py)). SCRUM-149 writes only `Pending`; SCRUM-150
and SCRUM-151 write the three decisions; SCRUM-153 writes `Approval Withdrawn`.
`Approval Withdrawn` is not a decision — it is an approval that a later
high-impact change invalidated, so it is absent from `DECISION_STATUSES` and
`PATCH .../decision` refuses it.
`Approved` is deliberately **not** one of them — that is only ever an *event*
status, the one an event holds before its safety check.

No DEV identity headers: this is a service-to-service API, like
`venue-availability-service`'s reads.

## Commands

```
uv sync
uv run flask --app app run --debug
uv run pytest
```

`uv run pytest` takes no flags: every pytest and coverage setting is in
`pyproject.toml`.

## Schema

Created by `database/supabase/migrations/20261011140000_baseline_schema.sql`
(SCRUM-169), plus
`database/supabase/migrations/20261016142813_safety_check_withdrawal.sql`
(SCRUM-153), which adds the three nullable `withdrawn_at` / `withdrawn_by` /
`withdrawal_reason` columns — no backfill, so existing rows are untouched.
This service applies no migrations of its own. It writes
`SafetyCheckFlag` rows for a `Changes Requested` decision (SCRUM-151),
area-level only: `bookingId` and `equipmentRequestId` stay `NULL`.
