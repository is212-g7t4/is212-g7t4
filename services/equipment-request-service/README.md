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

Identity is the DEV `X-Dev-User-Id` / `X-Dev-Role` headers (same as Equipment
Service) until Supabase JWT verification lands.

- `GET /equipment-requests[?status=Pending|Approved|Rejected][&eventId=<uuid>][&eventIds=<uuid>,<uuid>...]`
  — Technical Support or Event Coordinator. `eventIds` takes up to 500 IDs.
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
- `POST /events/<event_id>/equipment-requests` — Event Coordinator only. Body
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
`X-Internal-Service-Token` matching `INTERNAL_SERVICE_TOKEN`, shared with
Safety Check Service. This is not a browser or staff decision endpoint.
All IDs must belong to the event; otherwise nothing is updated. In one
transaction, the selected requests become `Pending` and `reviewed_by` is
cleared. Requests outside the selection are unchanged. Repeating the same
reset before staff review has the same result.
