# Event request submission

## 1. Start the service

From the repository root, copy the existing database configuration:

```powershell
Copy-Item .env services/event-service/.env
```

Then run:

```powershell
cd services/event-service
uv sync
uv run --env-file .env flask --app app run --port 5003
```

Alternatively, after creating services/event-service/.env, run
`docker compose up --build event-service` from the repository root.
The database password stays on the server. If the configured hostname is unavailable,
use the working connection string from your Supabase Connect panel in the service .env.

## 2. Start the frontend

In a second terminal, from the repository root:

```powershell
npm run dev:frontend
```

Open http://localhost:5174. The frontend calls http://localhost:5003 by default.
For a different API address, set VITE_EVENT_SERVICE_URL in the frontend .env.
If Vite uses a different port, set FRONTEND_ORIGIN in the service .env to that origin.

## Event Coordinator approval and rejection

The frontend's Topbar user picker (backed by `user-service`) supplies the
signed-in user's real UUID as `coordinatorId` on every request — there's no
mock role selector anymore. `VITE_CURRENT_COORDINATOR_ID`/`_NAME` in
`frontend/event-management-ui/.env` are only a fallback used briefly while
the real user list is still loading.

The queue shows decision actions only when an event's `coordinator_id` matches
the caller's id. Rejection requires a non-empty reason. The backend repeats the assignment
check while locking the event row and only approves or rejects requests whose current
status is `Submitted`.

`coordinatorId` is required on the coordinator read endpoints (`/events`,
`/events/submitted`, `/events/<id>`). Passing `viewerRole` widens them from
"assigned to me" to every event: `Event Coordinator Lead` on all three, and
`Venue Staff`/`Technical Support` on `/events` and `/events/<id>` only. Any
other `viewerRole` gets `403`. Approve and reject are **not** widened: the Lead
must be the assigned coordinator to approve or reject, the same as anyone else.

The role is whatever the caller sends, the same as `coordinatorId`. Atomics
can't call User Service to check it, so this stays trust-based until services
verify the Supabase JWT (see AGENTS.md). The retired `isManager=true` flag is
ignored.

`GET /events/unassigned` returns `Submitted` events with no `coordinator_id`,
oldest submission first. It backs the Lead's unassigned queue, which
`coordinator-assignment-service` serves at `GET /queue` after checking that the
caller is the Lead. The frontend never calls this endpoint directly.

`GET /events/active` returns every event that isn't `Confirmed`, `Rejected` or
`Cancelled`, assigned or not, ordered by start date. It backs the Lead's
coordinator workload view, which `coordinator-assignment-service` serves at
`GET /workload` after checking that the caller is the Lead. The frontend never
calls this endpoint directly.

Decisions are returned in `decision` and retained in `decisionHistory`. Each decision
records its status, coordinator ID, UTC timestamp, and rejection reason when present.

## Event progress and the safety gate

`PATCH /events/<id>/progress` is the only endpoint that moves an event through
its lifecycle. Since SCRUM-152 it refuses to move an event into `Confirmed`
until the event has passed its Operational Safety Check.

```
Submitted → Under Review → Approved ──(SCRUM-149)──► Pending Safety Check
                         ↘ Rejected                    │
                                    (SCRUM-150) ◄──────┼──────► (SCRUM-151)
                                         │             │            │
                                     Confirmed     Safety Changes  Cancelled
                                   (in preparation)  Requested
```

**`Confirmed` *is* the preparation stage.** It means the event passed its
Operational Safety Check and may proceed, so there is no separate
"In Preparation" status. **Only the safety workflow sets it** — a coordinator
can no longer confirm an event by hand, so the old `Approved → Confirmed` move
is gone. The safety statuses (`Pending Safety Check`, `Confirmed`,
`Safety Changes Requested`, `Cancelled`) are written by the safety-check
endpoints SCRUM-149/150/151 add, not here.

What this endpoint accepts, by the event's current status:

| Current status | Allowed `status` |
| --- | --- |
| Submitted | Submitted, Under Review |
| Under Review | Under Review, Approved, Rejected |
| Approved | Approved |
| Rejected | Rejected |
| Pending Safety Check | Pending Safety Check |
| Confirmed | Confirmed |
| Safety Changes Requested | Safety Changes Requested |
| Cancelled | Cancelled |

Every status lists itself and nothing else past approval: a "self" transition is
a save that keeps the status and updates the action details, and that keeps
working at every stage. Only the pre-safety transitions (SCRUM-19) actually move
an event, which is what keeps AC2 true.

SCRUM-152 AC1's guarantee that `Confirmed` can't be reached "through ... the
API" covers `PATCH /events/<id>/safety-status` too, not just `/progress`:
that endpoint accepts a direct call only from Safety Check Service, proven by
`X-Internal-Service-Token`. That lock is opt-in — set `INTERNAL_SERVICE_TOKEN`
here and on Safety Check Service to turn it on. Leaving it unset logs a
startup warning and leaves the endpoint unlocked, as it was before SCRUM-150.

Under Compose, this service reads the root `.env` and then
`services/event-service/.env`, so one value in the root `.env` configures the
whole stack while a per-service token still overrides it. The token is
deliberately not passed through Compose's `environment:`, which would
override the per-service file with an empty value whenever the root `.env`
had none — silently unlocking an installation that was previously locked.

The gate runs inside the row lock (`SELECT ... FOR UPDATE`) and after the
assigned-coordinator check, so a caller who isn't the assigned coordinator
still gets `403` and learns nothing about the event's stage. A blocked move
returns `409` with a reason the UI shows as-is:

```json
{
  "code": "SAFETY_APPROVAL_REQUIRED",
  "message": "Submit this event for safety check for it to progress to Confirmed.",
  "currentStatus": "Approved",
  "requiredStatus": "Confirmed"
}
```

The `message` is tailored to the current status — submit it for safety check
(`Approved`), waiting for the Safety Officer (`Pending Safety Check`), changes
to make and resubmit (`Safety Changes Requested`), cancelled, rejected, or not
yet approved. Any other disallowed transition still returns the generic
`409 This status change is not allowed for the event's current stage.` with no
`code`, and an unknown status returns `400`.

### `PATCH /events/<id>/safety-status` — for Safety Check Service only

The one way into a safety status. `PATCH /progress` above still cannot reach
any of them, so the two tables of allowed moves never overlap:
`ALLOWED_TRANSITIONS` is the coordinator's, `SAFETY_TRANSITIONS` is the
workflow's. SCRUM-149 adds `Approved → Pending Safety Check`; SCRUM-150 adds
`Pending Safety Check → Confirmed`.

**Optionally locked to Safety Check Service (SCRUM-150, moved forward from
SCRUM-152 v2's B1).** This story opens the first legitimate route into
`Confirmed`, so a direct API call could in principle confirm an event and
skip the Safety Officer. Setting `INTERNAL_SERVICE_TOKEN` closes that: every
request must then carry the shared secret:

```
X-Internal-Service-Token: <INTERNAL_SERVICE_TOKEN>
```

checked with `hmac.compare_digest` before the body is even parsed: missing or
wrong → `403 {"code": "INTERNAL_ONLY"}`. The header is deliberately **not** in
the CORS allow-headers list, so a browser cannot send it — only a
server-to-server caller can.

**The lock is opt-in.** If `INTERNAL_SERVICE_TOKEN` is unset on this service
(the default for local/dev setups that don't configure it), the check is
skipped entirely and the endpoint behaves exactly as it did before SCRUM-150
— no `503`, no header required. To turn the lock on, set
`INTERNAL_SERVICE_TOKEN` to the same value here and in
[`safety-check-service`](../safety-check-service/), which sends the header
(or an empty one, if it also has nothing configured) on every call to this
endpoint, submit and approve alike.

```json
PATCH /events/<id>/safety-status
{
  "status": "Pending Safety Check",
  "coordinatorId": "<uuid>",
  "safetyCheckId": "<uuid>",
  "roundNumber": 1
}
```

```json
PATCH /events/<id>/safety-status
{
  "status": "Confirmed",
  "decidedBy": "<uuid>",
  "safetyCheckId": "<uuid>",
  "roundNumber": 1,
  "remarks": "Looks safe."
}
```

Called by the composite, which has already checked the caller's role
(coordinator for submit, Safety Officer for approve, via User Service) and
the event's arrangements — neither is repeated here. What *is* checked,
inside `SELECT ... FOR UPDATE` because the composite's earlier read can be
stale:

- **Submit** (`status: "Pending Safety Check"`): the caller is the event's
  assigned coordinator, else `403` (SCRUM-149 AC5); the event isn't already
  `Pending Safety Check`, else `409 {"code": "SAFETY_CHECK_ALREADY_PENDING"}`
  (AC4).
- **Approve** (`status: "Confirmed"`): no coordinator check — the Safety
  Officer deciding is not the coordinator. Instead, the round being approved
  must be the one the event actually has open: the latest `actionHistory`
  entry with `status == "Pending Safety Check"` must carry the same
  `safetyCheckId` as this request, else
  `409 {"code": "STALE_SAFETY_CHECK"}` (SCRUM-150 AC3). This is what stops a
  stale or made-up round from confirming the event, with no call to another
  service.
- Either way, `status` must be reachable from the current one per
  `SAFETY_TRANSITIONS`, else
  `409 {"code": "INVALID_SAFETY_TRANSITION", "currentStatus": "<status>"}`.

On success it returns `200` with the event and appends to `actionHistory`.
Submit:

```json
{
  "status": "Pending Safety Check",
  "details": "Submitted for Operational Safety Check (round 1).",
  "coordinatorId": "<uuid>", "safetyCheckId": "<uuid>",
  "recordedAt": "2026-10-11T07:30:00+00:00"
}
```

Approve:

```json
{
  "status": "Confirmed",
  "details": "Operational Safety Check approved (round 1).",
  "decidedBy": "<uuid>", "safetyCheckId": "<uuid>",
  "remarks": "Looks safe.",
  "recordedAt": "2026-11-02T03:00:00+00:00"
}
```

That is the event-side record of AC1/AC2's "in the event's history" — what
the event detail page reads to show the submission and the decision.
`SafetyCheck.submitted_at`/`decided_at` in `safety-check-record-service` stay
the authoritative times. The coordinator's `decision`/`decisionHistory` are
untouched throughout: a safety decision is its own thing, kept on the
`SafetyCheck` round.

Like every endpoint today there is no JWT, so this one trusts `coordinatorId`
and `decidedBy`. The internal token plus the assignment/round checks mean a
direct browser call still can't submit someone else's event or invent a
decision (AC5, AC3), but it could skip the arrangements check or role lookup
if it somehow had the token — the same trust level as the rest of the system
until auth lands.

The lifecycle constants (`ALL_STATUSES`, `PRE_SAFETY_STATUSES`,
`SAFETY_STATUSES`, `PREPARATION_STATUS`, `ALLOWED_TRANSITIONS`,
`SAFETY_TRANSITIONS`, `SAFETY_BLOCK_MESSAGES`) live at module level in
`app/models.py` for the sibling safety stories to reuse. The frontend mirrors them in
`src/features/event/eventStatus.ts` purely to offer the right options and
explain the next step up front — the backend remains the authority.

