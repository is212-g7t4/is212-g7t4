# User accounts

Read-only lookups against `"User"` — no login, passwords, or JWTs.
Callers (currently the frontend and coordinator-assignment-service) assert a
user's identity by id rather than authenticating; this mirrors how
`coordinatorId` is already trusted elsewhere in the system.

## 1. Start the service

From the repository root, copy the existing database configuration:

```
cp .env services/user-service/.env
```

Then run:

```
cd services/user-service
uv sync
uv run --env-file .env flask --app app run --port 5001
```

Alternatively, after creating `services/user-service/.env`, run
`docker compose up --build user-service` from the repository root.

## Endpoints

- `GET /users` — all users, or `GET /users?role=Event+Coordinator` to filter.
- `GET /users/<uuid:user_id>` — a single user, 404 if not found.

Each user includes `manager_id`: `null` for an Event Coordinator manager
(e.g. Alice Tan), or another user's id for a coordinator reporting to them.
