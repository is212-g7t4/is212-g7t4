# safety-check-service

Composite service (port **5012**) that coordinates the Operational Safety
Check workflow (change #6). SCRUM-149 builds the first step, **submit**;
SCRUM-150 the second, **approve**; SCRUM-151 the other two, **request
changes** and **reject**. SCRUM-163 (review) and SCRUM-164 (resubmit) extend
it further.

Submitting and approving each need facts from more than one atomic and write
to two, which is exactly what a composite is for (AGENTS.md;
`c4_diagram/export/c4.png`). The records live in
[`safety-check-record-service`](../safety-check-record-service/) and the
event's status in [`event-service`](../event-service/) — neither knows about
the other.

| Calls | For |
|---|---|
| Event Service (5003) | the event and its coordinator; the lifecycle move |
| Venue Availability Service (5008) | every venue booking for the event |
| Equipment Request Service (5011) | every equipment request for the event |
| Safety Check Record Service (5013) | creating, deciding, listing and rolling back a round |
| User Service (5001) | the caller's role (SCRUM-150: is this a Safety Officer?) |

No notification in this story: Notification Service and RabbitMQ aren't built,
and the "decision" notification is SCRUM-168.

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

## `POST /safety-checks/approve`

```json
{
  "eventId": "<uuid>",
  "safetyOfficerId": "<uuid>",
  "remarks": "Looks safe."
}
```

`remarks` is optional, up to 2000 characters (AC2).

```
UI ──POST /safety-checks/approve──► Safety Check Service (composite, 5012)
 1. validate body (UUIDs, remarks ≤ 2000 chars)                             400
 2. GET  User Service   /users/<safetyOfficerId>                            403 NOT_SAFETY_OFFICER
    role must be 'Safety Officer'
 3. GET  Event Service  /events/<id>?coordinatorId=<officer>&viewerRole=Safety Officer
    event must be 'Pending Safety Check'                 409 EVENT_NOT_PENDING_SAFETY_CHECK (AC3)
 4. GET  Record Service /safety-check-records?eventId=<id>&status=Pending   409 NO_OPEN_SAFETY_CHECK
 5. PATCH Record Service /safety-check-records/<roundId>/decision
          {status: "Safety Approved", decidedBy, remarks}     409 SAFETY_CHECK_ALREADY_DECIDED
 6. PATCH Event Service /events/<id>/safety-status   (X-Internal-Service-Token)
          {status: "Confirmed", decidedBy, safetyCheckId, roundNumber, remarks}
        on any failure → POST Record Service /safety-check-records/<roundId>/reopen {decidedAt}
 7. 200 {safetyCheck, event}
```

| Case | Response |
|---|---|
| Bad body, bad UUIDs, non-text remarks, remarks over 2000 characters | `400 {"message": ...}` |
| Caller unknown or not a Safety Officer | `403 {"code": "NOT_SAFETY_OFFICER"}` |
| Event not found | `404` |
| Event not `Pending Safety Check` (AC3) | `409 {"code": "EVENT_NOT_PENDING_SAFETY_CHECK", "currentStatus": "..."}` |
| No open round (data out of step) | `409 {"code": "NO_OPEN_SAFETY_CHECK"}` |
| Round already decided — two officers at once (AC3/race) | `409 {"code": "SAFETY_CHECK_ALREADY_DECIDED", "safetyCheck": {...}}`, event untouched |
| Event Service refused step 6 (stale status or round), after reopening | `409 {"code": "EVENT_NOT_PENDING_SAFETY_CHECK"}` |
| Event Service refused this service's own token, after reopening | `502` |
| A downstream service failed / timed out | `502` / `504` |
| Success (AC1, AC2) | `200 {"safetyCheck": {...}, "event": {...}}` |

**Decide first, event second — same shape as submit.** The record service is
the race guard (AC3): if two Safety Officers click at once, only one `PATCH
.../decision` can see the round still `Pending`; the loser gets `409` before
the event is touched. If step 6 then fails, step 5's decision is undone via
`POST .../reopen`, which only works if `decidedAt` matches exactly — so this
can only undo the decision this request just made.

**The role is looked up, not trusted.** `safetyOfficerId` travels to User
Service, which answers with the caller's current role. A non-Safety-Officer
(or an unknown id) never gets past step 2, regardless of what the request
claims.

**Event Service's own round check is the second line of defence (AC3).**
Step 6 sends `safetyCheckId`; Event Service's `/safety-status` route checks
that round is the one the event actually has open before writing `Confirmed`
— see [`event-service`](../event-service/README.md). That means a stale read
in step 3 still can't confirm the wrong round, even without a second call
here.

### The compensation edge case, approve's version

If step 6 fails and the reopening `POST .../reopen` **also** fails, the round
id goes to the log at `ERROR` and the caller gets the original error. The
event then stays `Pending Safety Check` while the round reads `Safety
Approved` — the next approve attempt gets `NO_OPEN_SAFETY_CHECK`. To clear it,
find the id in the log and reopen the round by hand with the `decidedAt` it
was given:

```
curl -X POST localhost:5013/safety-check-records/<id>/reopen \
  -H "Content-Type: application/json" -d '{"decidedAt": "<the timestamp from the log/DB>"}'
```

## `POST /safety-checks/request-changes`

```json
{
  "eventId": "<uuid>",
  "safetyOfficerId": "<uuid>",
  "reason": "Needs another look.",
  "flags": [
    {"area": "venue arrangement", "changeRequired": "Move the stage left of centre."},
    {"area": "event details", "changeRequired": "Fix the clashing start time."}
  ]
}
```

`reason` is required text, up to 2000 characters (AC1). `flags` is 1 to 3
entries, each a distinct `area` (`"venue arrangement"`, `"technical
arrangement"`, `"event details"`) with its own non-blank `changeRequired`
(AC1). Shares every step with approve and reject — see `_decide` in
`app/routes.py`:

```
UI ──POST /safety-checks/request-changes──► Safety Check Service (composite, 5012)
 1. validate body (UUIDs, reason, flags)                                   400
 2. GET  User Service   /users/<safetyOfficerId>                           403 NOT_SAFETY_OFFICER
 3. GET  Event Service  /events/<id>?...&viewerRole=Safety Officer
    event must be 'Pending Safety Check'                409 EVENT_NOT_PENDING_SAFETY_CHECK (AC7)
 4. GET  Record Service /safety-check-records?eventId=<id>&status=Pending  409 NO_OPEN_SAFETY_CHECK
 5. PATCH Record Service /safety-check-records/<roundId>/decision
          {status: "Changes Requested", decidedBy, remarks, flags}  409 SAFETY_CHECK_ALREADY_DECIDED
 6. PATCH Event Service /events/<id>/safety-status   (X-Internal-Service-Token)
          {status: "Safety Changes Requested", decidedBy, safetyCheckId, roundNumber, remarks, areas}
        on any failure → POST Record Service /safety-check-records/<roundId>/reopen {decidedAt}
 7. 200 {safetyCheck, event}
```

Bookings and equipment requests are never read or written here (AC2's
"existing arrangements are preserved") — Venue Availability and Equipment
Request Service aren't called at all. Responses follow the same shape as
approve (`403 NOT_SAFETY_OFFICER`, `404`, `409
EVENT_NOT_PENDING_SAFETY_CHECK` / `NO_OPEN_SAFETY_CHECK` / `SAFETY_CHECK_ALREADY_DECIDED`,
`502`/`504`), plus `400` when `reason` or `flags` break any rule above.

## `POST /safety-checks/reject`

```json
{
  "eventId": "<uuid>",
  "safetyOfficerId": "<uuid>",
  "reason": "Unsafe egress plan.",
  "confirmed": true
}
```

`reason` is required text, up to 2000 characters (AC3). `confirmed` must be
`true` — the API enforces the UI's confirm step itself, so a client that
skips it gets `400 {"code": "REJECTION_NOT_CONFIRMED"}` and nothing is saved.

```
UI ──POST /safety-checks/reject──► Safety Check Service (composite, 5012)
 1. validate body (UUIDs, reason, confirmed === true)                      400
 2–6. same steps as approve/request-changes, deciding "Safety Rejected"
      and moving the event to "Cancelled"       409 EVENT_NOT_PENDING_SAFETY_CHECK (AC7)
 7. release (AC5): GET Venue Availability /events/<id>/venue-bookings
    for each booking not already Cancelled/Expired/Rejected:
         PATCH Venue Availability /venue-bookings/<bookingId>/cancel {eventId}
 8. 200 {safetyCheck, event, release}
```

`release` in the response:

```json
{
  "venueBookingsReleased": ["<bookingId>", "..."],
  "venueBookingsNotReleased": [],
  "equipment": "Released: equipment held by a Cancelled event no longer counts against availability."
}
```

**Release last, and only once the event is definitely `Cancelled`.**
Cancelling a booking can't be undone the way the decision can — the slot may
be taken a second later — so it only happens after step 6 succeeds. A
booking already `Cancelled`, `Expired` or `Rejected` is left alone: it
already blocks nothing, and its status stays accurate history. Equipment
needs no write: `equipment-reservation-service` already excludes a
`Cancelled` event's requests from held stock.

**A release failure doesn't undo the rejection.** If listing the bookings or
cancelling one fails, the event really is cancelled, so the response is
still `200` — the ids that couldn't be released land in
`venueBookingsNotReleased` and are logged at `ERROR`. To clear one by hand
(cancel is idempotent, so this is safe to repeat):

```
curl -X PATCH localhost:5008/venue-bookings/<id>/cancel \
  -H "Content-Type: application/json" -d '{"eventId": "<eventId>"}'
```

**AC4: `Cancelled` is terminal.** Event Service's `SAFETY_TRANSITIONS` has no
entry for `Cancelled`, so nothing — not a resubmit, not another decision —
can move the event again.

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
`coordinatorId` on submit. Approve is the first place a role is actually
checked server-side: `safetyOfficerId` is looked up in User Service rather
than trusted from the request (SCRUM-150). Event Service's own assignment and
round checks mean a direct browser call still can't submit someone else's
event (AC5) or confirm the wrong round (AC3), but either call could skip this
service's own arrangements/role checks if it somehow had
`INTERNAL_SERVICE_TOKEN` — the same trust level as the rest of the system
until auth lands. Set `INTERNAL_SERVICE_TOKEN` (shared with
[`event-service`](../event-service/)) in this service's environment; without
it, every call to `/safety-status` is refused.
