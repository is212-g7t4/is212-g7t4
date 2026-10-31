# Equipment Request Service (atomic)

Owns the equipment request records in `public."EquipmentRequest"` and records
the Technical Support decision on them (SCRUM-33). Being an atomic it calls no
other service, so it returns raw IDs (`eventId`, `equipmentId`).

It does **not** decide whether stock is available: that needs event dates,
equipment stock and other events' reservations, so it lives in
[Equipment Reservation Service](../equipment-reservation-service/README.md),
which calls this service.

## Run

```
cp .env services/equipment-request-service/.env   # from the repo root
cd services/equipment-request-service
uv sync
uv run --env-file .env flask --app app run --port 5011
```

Or `docker compose up --build equipment-request-service` (port 5011).

## Endpoints

Every endpoint needs a Supabase access token (`Authorization: Bearer
<token>`, SCRUM-8); the caller's id and role come from the token. `401`
without a valid token.

- `GET /equipment-requests[?status=Pending|Approved|Rejected][&eventId=<uuid>][&eventIds=<uuid>,<uuid>...]`
  — Technical Support, Event Coordinator or Event Coordinator Lead. `eventIds` takes up to 500 IDs.
  Each item:
  `{id, eventId, equipmentId, quantityRequested, technicalRequirements, status, reviewedBy, rejectionReason}`.
- `GET /equipment-requests/<id>` — same roles; `404` if unknown.
- `PATCH /equipment-requests/<id>` — Technical Support only. Body
  `{"status": "Approved" | "Rejected"}`; records the caller as `reviewedBy`.
  `409` if the request is no longer Pending, `404` if unknown, `400` for a bad
  id/status.
- `PATCH /events/<event_id>/equipment-requests` — Technical Support only. Body
  `{"status": "Approved" | "Rejected"}`; updates every Pending request for
  that event and returns them in `{"requests": [...]}`. `409` if the event has
  requests but none are Pending, `404` if the event has no requests.
  Both decision endpoints require `rejectionReason` when status is `Rejected`
  (1-500 characters after trimming). The reason is saved to `rejection_reason`
  and returned on reads; bulk rejection applies it to every Pending line.
  Approval and safety reset clear any previous rejection reason.
- `POST /events/<event_id>/equipment-requests` — Event Coordinator or Event Coordinator Lead (the Lead, for events
  assigned to them, as for venue requests). Body
  `{"items": [{"equipmentId", "quantityRequested", "technicalRequirements"?}]}`
  (1–50 items, quantity a whole number ≥ 1, each equipment once). Saves every
  line as Pending in one transaction and returns `201 {"requests": [...]}`;
  `404` (nothing saved) if the event or an equipment item does not exist.
  Assignment, event status and equipment availability are checked by
  Equipment Reservation Service, which is the caller the UI uses.

Because the status lives in this table, a coordinator reading
`GET /equipment-requests?eventId=` sees a decision as soon as it is saved.

### Safety re-review

`POST /events/<event_id>/equipment-requests/safety-reset` accepts
`{"requestIds": ["<uuid>"]}` (1-500 distinct IDs). It requires an
`X-Internal-Token` matching `INTERNAL_SERVICE_TOKEN`, shared with
Safety Check Service, **and** the `Safety Officer` role (SCRUM-10): Safety Check
Service forwards the signed-in Safety Officer's token, and any other role gets
`403 {"message": "Your role cannot change this information."}`. This is not a
browser or staff decision endpoint.
All IDs must belong to the event; otherwise nothing is updated. In one
transaction, the selected requests become `Pending` and `reviewed_by` is
cleared. Requests outside the selection are unchanged. Repeating the same
reset before staff review has the same result.


### SCRUM-48 transactional notification ownership

Create and individual/bulk review also take a `notificationContext` built by
Equipment Reservation Service. Create needs the `Event Coordinator` or
`Event Coordinator Lead` role and review needs `Technical Support`, both checked on the
forwarded user's token. These routes do **not** check an internal token (only the outbox
routes and `safety-reset` do), and the context is validated for shape only, so this
service does not itself prove the context came from Equipment Reservation Service; see
the known gaps in
[docs/scrum-10-role-based-modification-control.md](../../docs/scrum-10-role-based-modification-control.md).
The atomic never fetches Event/User/Equipment data or calls RabbitMQ. Browser callers
should use the composite. Context includes event identity/name, equipment names,
and submission recipient IDs or the decision-time coordinator ID. The owner
uses its **returned changed rows** to build IDs/quantities and freezes one
full-list submission envelope per TSS or one decision envelope per changed row.
No reason is copied into a decision envelope. Pending/unchanged rows emit none.

The envelopes and business changes commit together in the owner's new
`EquipmentNotificationOutbox`. Internal token-authenticated HTTP endpoints:
`POST /internal/notification-outbox/claim` and
`POST /internal/notification-outbox/<id>/published|retry` (leaseToken required).
The separate Equipment Reservation dispatcher publishes existing frozen content;
it cannot change recipient/message during retry. Safety reset has no new trigger.

For a new deployment where it is absent, the team must review/apply only
`database/supabase/migrations/20261028000000_equipment_notification_outbox.sql`
to this service's owning database. It creates the RLS-enabled outbox and pending
index, no history backfill. Use a privileged service DB connection; no client RLS
policy is granted. Do not rerun the migration on an existing deployment without
checking its history/schema and obtaining team approval. This cleanup did not
inspect or change shared schema/runtime state.
See the [composite README](../equipment-reservation-service/README.md) for deployment
order and [owner-only tests](tests/README.md) for opt-in disposable PostgreSQL commands.
