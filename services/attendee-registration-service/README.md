# Attendee Registration Service

Composite service for registering or withdrawing an attendee for a confirmed
event. Registration checks status, start time and capacity. Withdrawal uses the
organiser's optional deadline, or the event start when none was set, before
asking Registration Service to timestamp the status change atomically.

## Endpoint

The attendee is the signed-in caller: every endpoint needs
`Authorization: Bearer <token>` (SCRUM-8), which is forwarded downstream.

- `POST /registrations` with `eventId`.
- `GET /registrations` returns the caller's registration records combined
  with their confirmed event details.
- `PATCH /registrations/<registrationId>/withdraw` withdraws the caller's own
  registration before the applicable deadline.

No database is owned by this composite and no database schema changes are
required.
