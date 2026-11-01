# Equipment Reservation Service (composite)

Checks whether the equipment an event asked for is actually available, and
validates Technical Support's decision against that check. It owns no data: it
orchestrates atomic APIs and never reads their databases. Equipment Request owns
the final allocation transaction; this composite supplies catalogue/event inputs
and exact checked IDs, not a commit-time reservation of its own.

| Calls | For |
|---|---|
| Event Service | the event's `startTime`/`endTime`, and other events overlapping that window |
| Equipment Service | the catalogue: `totalQuantity` and physical `status` |
| Equipment Request Service | requests, final stock enforcement and recording approve/reject |
| User Service | eligible submission-notification recipients |
| Safety Check Record Service | latest-round feedback for equipment in safety revision |

## Availability rules

Availability is computed on demand for each Pending request; nothing is
polled or stored, and `Equipment.operational_status` is never changed.

1. **Physical check** — equipment that is not `Available` has effective stock `0`.
2. **Temporal check** — stock is a shared pool. `reserved` is the sum of
   `quantityRequested` over **Approved** requests belonging to the same event
   and other overlapping events whose status is `Approved`, `Confirmed`,
   `Under Review`, `Clarification Requested`, `Amendment Requested`,
   `Pending Safety Check` or `Safety Changes Requested`
  (Submitted events do not reserve stock) and whose window overlaps:
   `other.start < target.end AND other.end > target.start`.
   `availableStock = max(0, totalQuantity - reserved)`.
3. `isInsufficient = quantityRequested > availableStock`.

Read-time results are snapshots, not stock holds. Bulk approval groups the selected
quantities per equipment item. Equipment Request re-reads owner allocations after
its shared transaction lock and makes the final stock check before saving the exact
checked selection and its outbox records. That transaction does not prove external
input provenance or coordinate concurrent catalogue/event mutations.

## Endpoints

The caller's `Authorization: Bearer <token>` (SCRUM-8) is forwarded to the
atomics, which decide access from it.

- `GET /equipment-reservations[?status=Pending|Approved|Rejected]` — Technical
  Support, Event Coordinator or Event Coordinator Lead (coordinators and the Lead
  see only their assigned events). Returns `{events: [{eventId, eventName,
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
  or Event Coordinator Lead only; body `{"items": [{"equipmentId", "quantityRequested",
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
`SAFETY_CHECK_RECORD_SERVICE_URL`, `USER_SERVICE_URL`, `INTERNAL_SERVICE_TOKEN`,
`FRONTEND_ORIGIN` — see `.env.example`.
Port 5010 under docker compose.

## Commands

Optional host execution, from the repository root, after configuring this
service's `.env` and its downstream URLs (keep existing settings):

```bash
cd services/equipment-reservation-service
uv sync --locked --python 3.12
uv run --env-file .env flask --app app run --port 5010
```

Alternatively use Docker Compose from the root; do not bind port 5010 twice.
Prepared databases/accounts and running downstream services are prerequisites.
For isolated tests, from this service directory:

```bash
PYTHON_DOTENV_DISABLED=1 uv run --no-env-file --locked --python 3.12 pytest
```


## SCRUM-48 — equipment notifications

Exactly three acceptance criteria: submission alerts each eligible Technical Support
user once with the full submitted list; approval alerts the event's current
coordinator once per changed request row; rejection does the same without including
its workflow reason in message or details. AC2 covers Approved/Rejected decisions;
AC3's rejection message states that the Equipment Request was rejected, not
that the event was rejected and not the private reason why. The existing decision API still requires
and stores the rejection reason. Bulk decisions emit per changed row, not per unit.
No edit, withdrawal, reassignment or reminder notification triggers are added.

Before the write, this composite resolves event name, equipment names and either
TSS recipients (both `Technical Support` and `Technical Support Staff`) or the
current coordinator. The Event Service read (`/internal/events/<id>/notification-context`)
needs `X-Internal-Token` matching `INTERNAL_SERVICE_TOKEN`; if that token is not
configured here the action is refused with `503` before anything is saved. The create and
review calls supply notification context; approvals also supply catalogue/event
inputs and exact checked request IDs. The owner transaction protects its allocation
reads and approval writes, not external input provenance.
Existing browser callers continue using this composite, without sending internal tokens.
Configure the same token in Event, Equipment Request (its outbox routes) and Equipment
Reservation services. Cross-service reads remain outside the atomic. An unavailable context service refuses the action before saving;
broker/consumer outages do **not** affect successful writes.

The owner builds and freezes complete envelopes in `EquipmentNotificationOutbox`
in the **same transaction** as the submitted rows/decision. This is a separate
owner table, not the Venue service's table. It adapts SCRUM-47's lease-fenced HTTP
outbox, bounded dispatcher subprocess, confirmed persistent RabbitMQ publication
and Notification's existing `source_id` inbox deduplication. Retries retain saved
IDs, recipient and content; the worker never re-reads event assignment. An event
with no assigned coordinator has no eligible decision recipient. Submission with
no TSS has no eligible recipient. A later assignment does not create an alert.

Run `uv run python -m app.dispatcher` in a separate process, or deploy the Compose
`equipment-notification-dispatcher`. It needs only `EQUIPMENT_REQUEST_SERVICE_URL`,
`INTERNAL_SERVICE_TOKEN`, `RABBITMQ_URL` (no database access). Start the existing
Notification consumer too. Never run multiple uncoordinated deployments against
another team's shared state.

### Migration / rollout (deployment-specific; do not automatically rerun)

For a **new deployment where it is absent**, apply only
`database/supabase/migrations/20261028000000_equipment_notification_outbox.sql`
to the owning database after team approval and checking history/schema. Do not
rerun it on an existing deployment without those checks. This cleanup did not
inspect shared schema/runtime state. It creates the outbox and pending index, enables RLS with
no client policies, and requires the service's privileged DB connection. It does
not modify/backfill historical equipment requests. The existing Notification inbox
migration and consumer remain prerequisites; there is no additional inbox migration.
Deploy the consumer/frontend contract, then owner migration+service and composite,
then worker. Preserve/drain pending jobs before rollback; do not drop pending work.
No migration or test in this task writes shared Supabase.

### Verification: separate single-service boundaries

From this service directory, run the normal strict whole-service gate:

```sh
PYTHON_DOTENV_DISABLED=1 uv run --no-env-file --locked --python 3.12 pytest
```

Exactly three AC contract scenarios execute only Reservation's routes/adapters,
with external HTTP doubles: submission forwards full items/names/TSS context;
approval selects the latest pre-write coordinator snapshot; rejection keeps its
workflow reason outside notification context. Request separately tests frozen
full-list/per-record reason-free envelopes; Notification separately tests its
consumer contract. No production package from another owner is imported here.
Supporting bulk, security, stock-refusal and dispatcher cases are documented in
[tests/README.md](tests/README.md). No newly introduced SCRUM48 cross-service/E2E
harness remains on branch;
original sources/evidence were verified and handed off externally, not relabelled.
The driver/dotenv development dependencies used only by that harness were removed;
pika remains a real production dispatcher dependency.

Only Equipment Request owns the optional real PostgreSQL tests (no broker or
other service). See its [test guide](../equipment-request-service/README.md).
Do not run broad integration discovery or start shared workers to test this change.
The [test guide](tests/README.md) describes these separate test boundaries and
the known recipient snapshot timing limitation. Local regressions do not verify
remote CI or runtime deployment. This composite's snapshot is
**not assignment-at-commit proof**.
