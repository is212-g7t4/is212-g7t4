# Equipment Reservation Service (composite)

Checks whether the equipment an event asked for is actually available, and
validates Technical Support's decision against that check. It owns no data: it
orchestrates three atomics and never reads their databases.

| Calls | For |
|---|---|
| Event Service | the event's `startTime`/`endTime`, and other events overlapping that window |
| Equipment Service | the catalogue: `totalQuantity` and physical `status` |
| Equipment Request Service | the requests, and recording approve/reject |

## Availability rules

Availability is computed on demand for each Pending request; nothing is
polled or stored, and `Equipment.operational_status` is never changed.

1. **Physical check** — equipment that is not `Available` has effective stock `0`.
2. **Temporal check** — stock is a shared pool. `reserved` is the sum of
   `quantityRequested` over **Approved** requests belonging to *other* events
   whose status is `Approved`, `Confirmed`, `Submitted` or `Under Review`
   (i.e. not `Rejected`, so an Approved line on a still-pending event already
   holds stock) and whose window overlaps:
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
  `409`; Rejecting is always allowed.
- `GET /health`

## Configuration

`EQUIPMENT_REQUEST_SERVICE_URL`, `EVENT_SERVICE_URL`, `EQUIPMENT_SERVICE_URL`,
`FRONTEND_ORIGIN` — see `.env.example`. Port 5010 under docker compose.

## Commands

```
uv sync
uv run flask --app app run --debug
uv run pytest --cov=app --cov-report=term-missing
```
