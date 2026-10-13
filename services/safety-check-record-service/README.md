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

Body: `{status, decidedBy, remarks?}`. `status` must be one of
`DECISION_STATUSES` — only `Safety Approved` until SCRUM-151 adds
`Changes Requested` and `Safety Rejected`. `remarks` is optional text, up to
2000 characters; blank is stored as `NULL`.

The round is selected `FOR UPDATE` first, so this is also the race guard for
SCRUM-150 AC3: if two Safety Officers decide the same round at once, only one
`UPDATE` can see it still `Pending`.

- `200` with the decided record (`decidedBy`, `decidedAt = now()`, `remarks`).
- `404` when the round doesn't exist.
- `409 {"code": "SAFETY_CHECK_ALREADY_DECIDED", "safetyCheck": {...}}` when the
  round is no longer `Pending` — the race's loser, or a stale retry.
- `409 {"code": "NOT_LATEST_ROUND"}` when a later round exists for the event.
- `400` for a bad UUID, an unlisted `status`, or remarks that aren't text or
  are over 2000 characters.
- `503` when `DATABASE_URL` is unset or the database is unreachable.

### `POST /safety-check-records/<id>/reopen` is for compensation only

Body: `{decidedAt}`, the value `PATCH .../decision` returned. Safety Check
Service calls this when it decided a round and then could not move the event
(for example, the event's status changed underneath it). `decidedAt` must
match the round's current `decidedAt` exactly, so this can only undo the
decision the same request just made — never an older, unrelated decision.
`409` if the round isn't decided or `decidedAt` doesn't match; `404` if
missing.

### `DELETE /safety-check-records/<id>` is for compensation only

There is no distributed transaction across services. Safety Check Service
creates the round first and then moves the event to `Pending Safety Check`; if
that second step fails, it deletes the round it just created so the event isn't
left with an open round it doesn't know about. That is the only caller.

It refuses anything else: a round that has been decided returns `409`, and a
missing one `404`. Nothing here is a user-facing "withdraw my safety check" —
withdrawal, if it is ever wanted, is a new story.

## Record JSON

```json
{
  "id": "<uuid>", "eventId": "<uuid>", "roundNumber": 1,
  "submittedBy": "<uuid>", "submittedAt": "2026-10-11T07:30:00+00:00",
  "equipmentPlacementNotes": "Speakers either side of the stage.",
  "crowdMovementNotes": "Entry through Door A.",
  "status": "Pending", "decidedBy": null, "decidedAt": null, "remarks": null
}
```

`status` is one of `Pending`, `Safety Approved`, `Changes Requested`,
`Safety Rejected` (`RECORD_STATUSES` in [`app/models.py`](app/models.py)).
SCRUM-149 writes only `Pending`; SCRUM-150 and SCRUM-151 write the rest.
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
(SCRUM-169). This service applies no migrations of its own. It writes no
`SafetyCheckFlag` rows either — those are SCRUM-151's.
