# Attendee registrations

Owns records in `"Registration"`. Read lookups are called directly by the frontend for
a "simple read" (per `AGENTS.md`: the UI may call an owning atomic directly
without a composite in between), the same way it already calls
`event-service` and `user-service`.

The internal write endpoints are called by Attendee Registration Service after business validation. 
Registration Service serializes writes per event, enforces
attendee uniqueness and capacity, and owns the status and audit timestamp.

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
- `GET /registrations?attendeeId=<uuid>` — every registration belonging to
  one attendee, newest first.
- `POST /registrations` — internal atomic write used by Attendee Registration
  Service. Requires event and attendee IDs plus event capacity.
- `PATCH /registrations/<registrationId>/withdraw` — internal atomic write;
  verifies the attendee owns the row, changes `Confirmed` to `Withdrawn`, and
  records `withdrawn_at` in the same transaction.
