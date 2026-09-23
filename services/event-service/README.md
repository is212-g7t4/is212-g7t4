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

Open http://localhost:5173. The frontend calls http://localhost:5003 by default.
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

