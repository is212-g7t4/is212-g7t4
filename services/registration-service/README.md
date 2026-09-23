# Attendee registrations

Read-only lookups against `"Registration"` — no registration,
withdrawal, or capacity-checking logic. Called directly by the frontend for
a "simple read" (per `AGENTS.md`: the UI may call an owning atomic directly
without a composite in between), the same way it already calls
`event-service` and `user-service`.

This is a deliberately minimal slice of the eventually-planned Registration
Service — just enough to show registration counts and attendee lists on the
event detail page.

## 1. Start the service

From the repository root, copy the existing database configuration:

```
cp .env services/registration-service/.env
```

Then run:

```
cd services/registration-service
uv sync
uv run --env-file .env flask --app app run --port 5005
```

Alternatively, after creating `services/registration-service/.env`, run
`docker compose up --build registration-service` from the repository root.

## Endpoints

- `GET /registrations?eventId=<uuid>` — every registration row for that
  event, oldest first. No filtering by status — the caller (frontend)
  derives counts (e.g. "Confirmed" vs "Withdrawn") from the returned list.
