# safety-check-service

Composite service (port **5012**) that coordinates the Operational Safety
Check workflow (change #6). SCRUM-149 builds the first half, **submit**;
SCRUM-163 (review), SCRUM-150 (approve), SCRUM-151 (reject / request changes)
and SCRUM-164 (resubmit) extend it.

Submitting needs facts from three atomics and writes to two, which is exactly
what a composite is for (AGENTS.md; `c4_diagram/export/c4.png`). The records
live in [`safety-check-record-service`](../safety-check-record-service/) and
the event's status in [`event-service`](../event-service/) — neither knows
about the other.

| Calls | For |
|---|---|
| Event Service (5003) | the event and its coordinator; the lifecycle move |
| Venue Availability Service (5008) | every venue booking for the event |
| Equipment Request Service (5011) | every equipment request for the event |
| Safety Check Record Service (5013) | creating, listing and rolling back a round |

No notification in this story: Notification Service and RabbitMQ aren't built,
and the "submitted" notification is change-6 story 6.9.

## `POST /safety-checks`

```json
{
  "eventId": "<uuid>",
  "coordinatorId": "<uuid>",
  "equipmentPlacementNotes": "Speakers either side of the stage.",
  "crowdMovementNotes": "Entry through Door A, exit through Doors B and C."
}
```

Both note fields are optional, up to 2000 characters each (SCRUM-149 AC3).

```
UI ──POST /safety-checks──► Safety Check Service (composite, 5012)
 1. validate body (UUIDs, notes ≤ 2000 chars)                               400
 2. GET  Event Service /events/<id>?coordinatorId=<caller>                  404 / 403 (AC5)
 3. event is 'Pending Safety Check'
       → GET records ?status=Pending, 409 SAFETY_CHECK_ALREADY_PENDING      (AC4)
    event isn't 'Approved' → 409 EVENT_NOT_READY_FOR_SAFETY_CHECK
 4. in parallel: GET Venue Availability /events/<id>/venue-bookings
                 GET Equipment Request  /equipment-requests?eventId=<id>
    outstanding → 422 ARRANGEMENTS_OUTSTANDING, nothing written             (AC2)
 5. POST Safety Check Record /safety-check-records       409 → ALREADY_PENDING (AC4)
 6. PATCH Event Service /events/<id>/safety-status
    any failure → DELETE the round just created (compensate), map the error
 7. 201 {safetyCheck, event}
```

| Case | Response |
|---|---|
| Bad body, bad UUIDs, non-text notes, a note over 2000 characters | `400 {"message": ...}` |
| Event not found | `404` |
| Caller isn't the assigned coordinator (AC5) | `403 {"code": "NOT_ASSIGNED_COORDINATOR"}` |
| Event already `Pending Safety Check` (AC4) | `409 {"code": "SAFETY_CHECK_ALREADY_PENDING", "safetyCheck": {...}}`, nothing created |
| Any other status but `Approved` | `409 {"code": "EVENT_NOT_READY_FOR_SAFETY_CHECK", "currentStatus": "..."}` |
| Outstanding arrangements (AC2) | `422 {"code": "ARRANGEMENTS_OUTSTANDING", "outstanding": [...]}`, nothing created |
| A downstream service failed / timed out | `502` / `504` |
| Success (AC1, AC3) | `201 {"safetyCheck": {...}, "event": {...}}` |

### Three rules worth knowing

**Record first, event second.** The record service is the duplicate guard
(AC4) — it refuses a new round while one is `Pending` and has
`UNIQUE (event_id, round_number)` behind that. Creating the record first means
two near-simultaneous submits cannot both reach step 6.

**Event Service re-checks under a row lock.** Step 2's read can be stale: the
event may be reassigned, or another submission may land, before step 6. So
`PATCH /events/<id>/safety-status` repeats the coordinator and status checks
inside `SELECT ... FOR UPDATE`.

**Fail closed.** If the bookings or the equipment requests can't be read, the
submission is blocked (`502`/`504`) — "couldn't check" is never treated as
"nothing outstanding". Downstream URLs and error text stay inside
`app/clients.py` and never reach the browser.

### The compensation edge case

There is no distributed transaction. If step 6 fails, step 5's round is
deleted. If **that delete also fails**, there is nothing left to try: the
record id goes to the log at `ERROR` and the caller gets the original error.
The event then reads `Approved` while the next submit gets
`SAFETY_CHECK_ALREADY_PENDING`. To clear it, find the id in the log and remove
the round by hand:

```
curl -X DELETE localhost:5013/safety-check-records/<id>   # 204; it is still Pending
```

## `GET /safety-checks/readiness?eventId=<uuid>&coordinatorId=<uuid>`

Steps 2–4 only, no writes — what the submit panel calls on mount so a
coordinator sees what's outstanding before clicking rather than after.

```json
{
  "ready": false,
  "eventStatus": "Approved",
  "outstanding": [
    {"type": "venue", "id": "<bookingId>", "status": "Pending Review",
     "label": "Booking 12 Nov 2026 09:00–17:00 (120 people)",
     "reason": "Waiting for Venue Staff approval."}
  ],
  "openSafetyCheck": null
}
```

`openSafetyCheck` is filled only when the event is `Pending Safety Check`.
Same `400`/`403`/`404`/`502`/`504` as above.

## The readiness rule — `app/readiness.py`

One pure function, shared by both endpoints so the list and the submit check
can't disagree, and unit-tested without HTTP.

| Arrangement | Ready | Outstanding | Ignored |
|---|---|---|---|
| Venue booking | `Approved` | `Pending Review`, `Pending`, `Rejected`, missing/unknown status | `Cancelled`, `Expired` — withdrawn or lapsed, the same set Venue Availability treats as inactive |
| Equipment request | `Approved`, `Reserved` | `Pending`, `Rejected`, missing/unknown status | `Cancelled` (no endpoint sets it today) |

Plus two rules AC1 implies but doesn't spell out:

- **No equipment requested is ready** — AC1 says so outright.
- **No live venue booking is outstanding**, with the item
  `"No venue booking has been made for this event."` An event with nowhere to
  happen isn't ready for a safety check. Only cancelled or expired bookings
  counts as the same thing.

Labels use only what the two responses carry (times, `requiredCapacity`,
`quantityRequested`). The composite deliberately does **not** call Venue or
Equipment Service for names here; the UI already has venue names from
`VenueBookingsPanel` and can enrich a label client-side by `id`.

## Commands

```
uv sync
uv run flask --app app run --debug
uv run pytest
```

`uv run pytest` takes no flags: every pytest and coverage setting is in
`pyproject.toml`.

## Trust

Like every endpoint today there is no JWT, so this service trusts
`coordinatorId` and Event Service trusts the one it is handed. Event Service's
own assignment check means a direct browser call still can't submit someone
else's event (AC5), but it could skip the arrangements check — the same trust
level as the rest of the system until auth lands.
