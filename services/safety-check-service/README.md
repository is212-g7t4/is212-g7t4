# safety-check-service

Composite service (port **5012**) that coordinates the Operational Safety
Check workflow (change #6). SCRUM-149 builds the first step, **submit**;
SCRUM-150 the second, **approve**; SCRUM-151 the other two, **request
changes** and **reject**; SCRUM-153 adds **re-check**, which withdraws an
approval after a high-impact change. SCRUM-163 (review) and SCRUM-164
(resubmit) extend it further, and SCRUM-28 Part B adds the venue-change
withdrawal Venue Booking Service calls.

Submitting and approving each need facts from more than one atomic and write
to two, which is exactly what a composite is for (AGENTS.md;
`c4_diagram/export/c4.png`). The records live in
[`safety-check-record-service`](../safety-check-record-service/) and the
event's status in [`event-service`](../event-service/) — neither knows about
the other.

| Calls | For |
|---|---|
| Event Service (5003) | the event and its coordinator; the lifecycle move; the edit write on a re-check |
| Venue Availability Service (5008) | every venue booking for the event |
| Equipment Request Service (5011) | every equipment request for the event |
| Safety Check Record Service (5013) | creating, deciding, listing, withdrawing and rolling back a round |
| User Service (5001) | the caller's role (SCRUM-150: is this a Safety Officer?) |
| Venue Service (5006) | venue names for the Safety Officer's queue (SCRUM-162) |
| Equipment Service (5002) | equipment catalogue details for the Safety Officer's review (SCRUM-163) |

## `GET /safety-checks/<eventId>/review?safetyOfficerId=<uuid>`

The Safety Officer's read-only review page uses this composite read to gather
the event, venue bookings and venue catalogue details, equipment requests and
catalogue names, the open round's placement/crowd notes, and every earlier
safety round. The route verifies the caller's role and that the event is
`Pending Safety Check`; downstream read failures fail closed. The response
groups per-booking capacity comparisons under `venues`, requested inventory
under `equipment`, and earlier decisions under `history`. Each venue entry's
`emergencyAccess` and `restrictions` come from Venue Service's
`emergencyAccessDetails` and `knownRestrictions` (SCRUM-167, recorded by Venue
Staff); they are null when nothing is recorded, so the UI displays
**Not provided**.

No notification in this story: Notification Service and RabbitMQ aren't built,
and the "decision" notification is SCRUM-168.

## `GET /safety-checks/feedback`

Query: `eventId=<uuid>&coordinatorId=<uuid>`. Checks assignment through Event
Service before reading any safety records. Returns `{ "safetyChecks": [...] }`
with complete review rounds, including decision, reason (`remarks`), affected
areas and requested changes (`flags`), newest first. An event with no rounds
returns an empty list. This endpoint is read-only and does not reset any
arrangements. Invalid identifiers return 400, inaccessible events 403/404,
and downstream failures 502/504.

The assigned coordinator's event details page displays this feedback while the
event is `Safety Changes Requested`, with earlier rounds available separately.
Arrangement revision and resubmission are separate increments of the story.

## Safety Resubmission

`GET /safety-checks/resubmit/readiness?eventId=<uuid>&coordinatorId=<uuid>`
returns `{ready, eventStatus, outstanding}` for the assigned coordinator.
`ready` requires `Safety Changes Requested`, at least one active approved
venue booking, and no outstanding venue or equipment arrangements. Pending
and rejected equipment block; rejected venue history is ignored when an
approved replacement exists. Loading failures leave the button disabled.

`POST /safety-checks/resubmit` accepts the same body as initial submission,
but requires `Safety Changes Requested` and rechecks venue and equipment readiness
before creating the next round. It moves the event to `Pending Safety Check`,
preserves earlier rounds, and deletes the new undecided round if the event
update fails. Duplicate submissions retain the existing open-round guard.
The feedback section's **Resubmit Safety Check** button carries forward the
previous review's planning notes and reloads the event after success.

Initial submission and resubmission use the same full arrangement rules.
Coordinator venue edits refresh readiness and disable resubmission until
Venue Staff has reviewed the edited arrangement.
Save progress remains a separate notes/progress action, not resubmission.

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

`reason` is required text, up to 2000 characters (AC1). Area-wide `flags`
use distinct areas (`"venue arrangement"`, `"technical arrangement"`,
`"event details"`), each with non-blank `changeRequired`. Targeted technical
flags may also include `equipmentRequestId`; see the scope rules below.
Shares the decision steps with approve and reject — see `_decide` in
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

Technical flags may include an `equipmentRequestId`. Distinct requests can
have separate technical flags (up to 500 flags); an area-wide flag cannot
be mixed with individual flags for the same area. Request IDs are checked
against this event before deciding the round. After the decision is saved,
flagged equipment is reset to `Pending` through Equipment Request Service's
internal `safety-reset` endpoint, before moving the event. A technical flag
without an ID resets the whole event's equipment arrangement. Unflagged
requests remain approved. Both services must share `INTERNAL_SERVICE_TOKEN`.
If reset fails, the safety decision is reopened and no success is reported.
If the event update fails after reset, requests stay Pending (fail closed)
while the safety decision is reopened; retrying the decision can complete it.

Venue flags may include `bookingId`; without one, the venue area covers all
active event bookings. Flagged active bookings return to `Pending Review`
through Venue Availability Service's internal safety-reset endpoint.
Terminal bookings are preserved, and unaffected bookings remain approved.
Venue Availability must share `INTERNAL_SERVICE_TOKEN` with this composite.
Arrangement reset failures reopen the decision and do not report success.
Responses follow the same shape as
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

## `POST /safety-checks/recheck`

```json
{
  "eventId": "<uuid>",
  "coordinatorId": "<uuid>",
  "changes": {"expectedAttendance": "400", "eventName": "Community Workshop"}
}
```

SCRUM-153: a **high-impact** change to a `Confirmed` event withdraws its
safety approval, so the event is never prepared on the basis of an outdated
safety review. The five details in AC1 are high-impact — date/time, expected
attendance, venue requirements, equipment requirements, accessibility needs;
the rest (name, description, purpose, registration needs) are low-impact and
never come here.

The UI calls **Event Service first**, with the same `changes`. A low-impact
edit saves there and the event stays `Confirmed` (AC2). A high-impact one gets
`409 SAFETY_RECHECK_REQUIRED`, the coordinator confirms, and the UI calls this
route — the `changes` unchanged.

The order of writes:

1. validate the body: UUIDs, `changes` a non-empty object of editable fields,
   every value text — `400`, nothing written;
2. `GET` the event as the coordinator — `403` for a stranger, `404` if missing;
3. the event must be `Confirmed` — else
   `409 {"code": "RECHECK_NOT_NEEDED", "currentStatus"}`;
4. at least one high-impact field must really change, compared on **normalised**
   values exactly as Event Service compares them (strings stripped, attendance
   as an int, dates as naive Singapore-local date-times) — else the same `409`.
   This is an early, friendly check only: Event Service's gate decides for
   real. Catching it here keeps a no-op edit from withdrawing an approval that
   then has to be compensated back;
5. the event's latest round must be `Safety Approved` — else
   `409 {"code": "NO_APPROVED_SAFETY_CHECK"}` (data drift);
6. `POST .../safety-check-records/<round N>/withdraw`, which in one
   transaction marks round N `Approval Withdrawn` (keeping its decision, AC3)
   and opens round N+1 as `Pending`;
7. `PATCH /events/<id>/details` with `changes`, the `safetyRecheck` block
   naming both rounds, and the internal token. Event Service saves the fields
   **and** moves the event to `Pending Safety Check` in one transaction, and
   writes the "approval withdrawn because …" history line (AC1's "told why").
   **Any failure here restores the withdrawal** (step 8);
8. `200 {event, safetyCheck, withdrawnSafetyCheck, changedFields, reason}`.

**Record first, then event**, as submit and approve do: the record service's
row lock on the event's latest round is the race guard, so two concurrent
re-checks can't both open round N+1 — the second gets
`409 ROUND_NOT_APPROVED`, passed through, with the event untouched.

**Event Service re-checks everything under its own lock**: the status is still
`Confirmed`, the withdrawn round really is the approval the event holds (else
`409 STALE_SAFETY_CHECK`), and a high-impact field still changes. So an edit
landing between steps 2 and 7 can't leave a mismatched state, and a made-up
round id can't move the event. Its refusals — a validation `400`,
`STALE_SAFETY_CHECK`, `EVENT_UNDER_SAFETY_REVIEW` — are passed back verbatim
with their own status: it is the authority on the fields, the gate and the
status, and its body already says what the coordinator has to fix.

**No readiness re-check of bookings or equipment.** Round N+1 is reviewed by
the Safety Officer as it stands; if the change makes a booking unsuitable the
officer requests changes (SCRUM-151) and SCRUM-164 takes over. This route
never calls Venue Availability, Equipment Request or User Service.

### The compensation edge case, re-check's version

If step 7 fails and the restoring `POST .../restore` **also** fails, both ids
go to the log at `ERROR` and the caller gets the original error. The event
then reads `Confirmed` with its approval withdrawn and round N+1 waiting —
the worst of both. To clear it, find the ids in the log:

```
curl -X POST localhost:5013/safety-check-records/<round N id>/restore \
  -H "Content-Type: application/json" -d '{"openedSafetyCheckId": "<round N+1 id>"}'
```

`restore` is idempotent, so this is safe to repeat.

## `POST /safety-checks/withdraw-for-venue-change` (SCRUM-28 Part B)

Called by **Venue Booking Service** (5007), before it edits or cancels a
venue booking of a `Confirmed` event. Decided 25 Oct: the approval was given
for the old arrangement, so it is withdrawn and the event goes back to
**`Approved`**. Unlike a re-check, **no round is opened**: Venue Staff re-review
the changed booking, then the coordinator resubmits with `POST
/safety-checks`, which opens round N+1.

Body `{eventId, coordinatorId, bookingId, reason}`. Steps: load the event as
the coordinator (`403` for anyone else) → it must be `Confirmed` (`409
EVENT_NOT_CONFIRMED`) → its latest round must be `Safety Approved` (`409
NO_APPROVED_SAFETY_CHECK`) → withdraw that round with `openNextRound: false`
(the record service's lock is the race guard; a lost race is `409
ROUND_NOT_APPROVED`) → move the event `Confirmed → Approved` with
`withdrawnSafetyCheckId`. If the event move fails, the round is restored
(`nextRoundOpened: false`) and Event Service's error is returned. `200
{event, withdrawnSafetyCheck, bookingId}`.

## `POST /safety-checks/restore-after-venue-change` (SCRUM-28 Part B)

Compensation only: Venue Booking Service calls this when the booking change
it withdrew the approval for then failed. Body `{eventId, coordinatorId,
withdrawnSafetyCheckId}`. The event must be `Approved` (`409
EVENT_NOT_WITHDRAWN`). **Record first, then event**: the round is restored,
then the event moves `Approved → Confirmed` with `restoredSafetyCheckId`. If
that event move fails, the event stays `Approved` with its round approved
again — safe, because nothing reads as confirmed without an approval — and it
is logged at `ERROR`; the coordinator resubmits. `200 {event, safetyCheck}`.

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

## `GET /safety-checks/queue?safetyOfficerId=<uuid>`

SCRUM-162: the Safety Officer's queue of events awaiting an Operational
Safety Check. Read-only.

```
UI ──GET /safety-checks/queue──► Safety Check Service (composite, 5012)
 1. validate safetyOfficerId                                                400
 2. GET  User Service   /users/<safetyOfficerId>                            403 NOT_SAFETY_OFFICER
 3. in parallel: GET Event Service /events?status=Pending Safety Check
                     &viewerRole=Safety Officer&coordinatorId=<officer>     (AC1)
                 GET Venue Service /venues                       (names only)
 4. per event, in parallel:
       GET Record Service     /safety-check-records?eventId=<id>&status=Pending
       GET Venue Availability /events/<id>/venue-bookings
 5. 200 {events: [...]}, nearest event date first                           (AC2)
```

```json
{
  "events": [
    {
      "eventId": "<uuid>", "eventName": "Community Workshop",
      "preferredStartDate": "2026-11-12T09:00:00+08:00",
      "preferredEndDate": "2026-11-12T17:00:00+08:00",
      "expectedAttendance": "120",
      "venues": [{"id": "<uuid>", "name": "Main Hall"}],
      "safetyCheckId": "<uuid>",
      "submittedAt": "2026-11-01T02:30:00+00:00",
      "roundNumber": 2,
      "resubmission": true
    }
  ]
}
```

- **Submission date** is the open round's `submittedAt`, so a resubmission
  shows when it was resubmitted, not when it was first submitted.
- **Resubmission** (AC3) is `roundNumber > 1`: every round after the first
  follows an earlier decision. Nothing creates a round 2 until resubmit
  (SCRUM-164) is built.
- **Venues** are the event's bookings that still hold a venue (not
  `Cancelled`, `Expired` or `Rejected`), one entry per venue. A venue missing
  from the catalogue is shown as `"Unknown venue"`.
- **Order** (AC2): `preferredStartDate` ascending, ties by `eventId`, undated
  events last.
- **Decided events drop out** (AC4) with no extra rule: every decision moves
  the event out of `Pending Safety Check`, and step 3 lists only that status.
- **An event with no open round** (data out of step) is left out and logged
  at `WARNING`, rather than shown with no submission date.
- **Fails closed:** if any read fails, the whole queue is `502`/`504`. A
  partial list could silently hide an event the officer has to review.

The per-event reads are two calls per queued event. That is fine at this
queue's size. If it ever isn't, the fix is batch reads (`eventIds=`) on the
record and booking services.

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
