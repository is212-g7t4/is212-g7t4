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

The Event Coordinator manager (role `Event Coordinator`, `manager_id` is
`null`) can bypass the `coordinator_id` filter/ownership check on the read
endpoints (`/events`, `/events/submitted`, `/events/<id>`) by passing
`isManager=true` — this lets them see every event, not just ones assigned to
them. Approve/reject are **not** bypassed — the manager must be the assigned
coordinator to approve or reject, same as anyone else.

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

The lifecycle constants (`ALL_STATUSES`, `PRE_SAFETY_STATUSES`,
`SAFETY_STATUSES`, `PREPARATION_STATUS`, `ALLOWED_TRANSITIONS`,
`SAFETY_BLOCK_MESSAGES`) live at module level in `app/models.py` for the
sibling safety stories to reuse. The frontend mirrors them in
`src/features/event/eventStatus.ts` purely to offer the right options and
explain the next step up front — the backend remains the authority.

