# User accounts

Lookups against `"User"`, plus sign-in through Supabase Auth (SCRUM-8).
Passwords are never stored or checked here: `POST /auth/login` passes them to
Supabase and returns its access token. Every other endpoint needs that token
(`Authorization: Bearer <token>`) or, for background workers, the
`X-Internal-Token`.

Environment: `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`,
`INTERNAL_SERVICE_TOKEN`.

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

- `POST /auth/login` — body `{ "email", "password" }`. `200 { accessToken,
  expiresAt, user }` (`expiresAt` in epoch seconds); `400` if either field is
  missing; `401 "Incorrect email or password."`; `403` if the account has no
  `"User"` profile; `503` if Supabase is unreachable or not configured.
- `GET /users` — all users, or `GET /users?role=Event+Coordinator` to filter.
- `GET /users/<uuid:user_id>` — a single user, 404 if not found.

The Event Coordinator Lead is identified by role: `Event Coordinator Lead`
(e.g. Alice Tan). Users carry no link to a Lead.
