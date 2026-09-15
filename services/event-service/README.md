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

## Event Coordinator approval

The prototype role selector does not provide a signed-in user's UUID. Configure an
existing coordinator in `frontend/event-management-ui/.env`:

```dotenv
VITE_CURRENT_COORDINATOR_ID=<existing Event Coordinator user_id>
VITE_CURRENT_COORDINATOR_NAME=<coordinator display name>
```

The queue shows **Approve Request** only when an event's `coordinator_id` matches
that UUID. The backend repeats the assignment check while locking the event row and
only approves requests whose current status is `Submitted`.

