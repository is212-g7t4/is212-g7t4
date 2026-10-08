# Attendee Registration Service

Composite service for registering an attendee for a confirmed event. It checks
Event Service for the event status and start time, then asks Registration
Service to atomically enforce duplicate-email and capacity rules and create the
registration.

## Endpoint

- `POST /registrations` with `eventId`, `attendeeId`, `fullName`, `email`, and
  optional `organization`.
- `GET /registrations?attendeeId=<uuid>` returns that attendee's registration
  records combined with their confirmed event details.

No database is owned by this composite and no database schema changes are
required.
