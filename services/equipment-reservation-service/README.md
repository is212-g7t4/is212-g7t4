# Equipment Reservation Service (composite)

Checks whether the equipment an event asked for is actually available, and
validates Technical Support's decision against that check. It owns no data: it
orchestrates three atomics and never reads their databases.

| Calls | For |
|---|---|
| Event Service | the event's `startTime`/`endTime`, and other events overlapping that window |
| Equipment Service | the catalogue: `totalQuantity` and physical `status` |
| Equipment Request Service | the requests, and recording approve/reject |
| Safety Check Record Service | latest-round feedback for equipment in safety revision |

## Availability rules

Availability is computed on demand for each Pending request; nothing is
polled or stored, and `Equipment.operational_status` is never changed.

1. **Physical check** — equipment that is not `Available` has effective stock `0`.
2. **Temporal check** — stock is a shared pool. `reserved` is the sum of
   `quantityRequested` over **Approved** requests belonging to *other* events
  whose status is `Approved`, `Confirmed`, `Under Review`, `Clarification Requested`,
  `Pending Safety Check` or `Safety Changes Requested`
  (Submitted events do not reserve stock) and whose window overlaps:
   `other.start < target.end AND other.end > target.start`.
   `availableStock = max(0, totalQuantity - reserved)`.
3. `isInsufficient = quantityRequested > availableStock`.

Each line is compared to the pool on its own.

## Endpoints

DEV `X-Dev-User-Id` / `X-Dev-Role` headers are forwarded to the atomics.

- `GET /equipment-reservations[?status=Pending|Approved|Rejected]` — Technical
  Support or Event Coordinator. Returns `{events: [{eventId, eventName,
  eventStatus, startTime, endTime, requests: [...]}]}`. Each
  request has the Equipment Request Service fields plus `equipment`
  (`description, type, totalQuantity, status`) and, for Pending lines only,
  `availability` (`reservedQuantity, availableStock, isInsufficient`).
- `PATCH /equipment-reservations/requests/<id>` — Technical Support only; body
  `{"status": "Approved" | "Rejected"}`. Approving an insufficient line is `409`.
- `PATCH /equipment-reservations/events/<event_id>` — Technical Support only;
  the batch decision. Approving while any Pending line is insufficient is
  `409`; rejection does not require sufficient stock.
  Both decision endpoints require `rejectionReason` for `Rejected` decisions
  (1-500 characters after trimming), forwarded to Equipment Request Service.
  Bulk rejection uses the same reason for every Pending line; request reads
  include the saved `rejectionReason` for staff and assigned coordinators.
- `POST /equipment-reservations/events/<event_id>/requests` — Event Coordinator
  only; body `{"items": [{"equipmentId", "quantityRequested",
  "technicalRequirements"?}]}`. `403` unless the event is assigned to the
  caller, `409` unless it is Under Review or Safety Changes Requested, `409` if any item's
  physical status is Unavailable, `404` if an item is not in the catalogue.
  Stock over the event's window is not checked here — that happens at review.
  Forwards to Equipment Request Service and returns `201 {"requests": [...]}`.
- `GET /health`

## Configuration

For events at `Safety Changes Requested`, each request includes
`safetyFeedback: {reason, requestedChanges}` when it matches a technical flag
in the latest Changes Requested round, or `null` when unflagged. Individual
flags match `equipmentRequestId`; area-wide technical flags apply to every
equipment request for that event. Earlier-round feedback is not reused.
Technical Support sees this in the final Safety change reason column of the
horizontally scrollable equipment-review table.

`EQUIPMENT_REQUEST_SERVICE_URL`, `EVENT_SERVICE_URL`, `EQUIPMENT_SERVICE_URL`,
`SAFETY_CHECK_RECORD_SERVICE_URL`, `FRONTEND_ORIGIN` — see `.env.example`.
Port 5010 under docker compose.

## Commands

```
uv sync
uv run flask --app app run --debug
uv run pytest --cov=app --cov-report=term-missing
```
