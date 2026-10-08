# Attendee registrations

Owns records in `"Registration"`. Read lookups are called directly by the frontend for
a "simple read" (per `AGENTS.md`: the UI may call an owning atomic directly
without a composite in between), the same way it already calls
`event-service` and `user-service`.

The internal `POST /registrations` endpoint is called by Attendee Registration
Service after event validation. It serializes registrations per event and
enforces duplicate-email and capacity rules before inserting a confirmed row.

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
- `POST /registrations` — internal atomic write used by Attendee Registration
  Service. Requires event and attendee IDs, capacity, full name and email.
