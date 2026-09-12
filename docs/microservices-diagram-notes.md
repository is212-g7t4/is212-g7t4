# Microservices Diagram — Style Reference & Spec

Notes from scanning the reference Miro board ("Microservice Overview",
`https://miro.com/app/board/uXjVG3A1SwU=/` — a TravelLust trip-planning
example, not part of this project) to match its visual conventions for our
own ConnectSphere architecture diagram, plus the resulting spec for our system.

All of this is built on the Miro board `is212 archi diagrams`
(`https://miro.com/app/board/uXjVHqeuVHs=/`), in six frames: five
composite-service flow diagrams and one "Master SOA Overview" tying
everything together. The teammate's ER diagram and the earlier C4 diagrams
on that board are separate and untouched by this spec.

## Reference board conventions

**Color coding (fill / stroke):**

| Fill hex | Stroke hex | Meaning |
|---|---|---|
| `#fff6b6` (light/pale yellow) | `#1a1a1a` (black) | Composite / process service (orchestrates a business capability) |
| `#ffdc4a` (deeper gold yellow) | `#1a1a1a` | Atomic service — one entity, simple CRUD (or a self-contained algorithm) |
| `#c6dcff` (light blue) | `#1a1a1a` | Wrapper service exposing an external system (our one wrapper: Email/SMS delivery) |
| `#305bab` (deep blue) | `#1a1a1a`, white text | UI (React SPA) |
| `#dedaff` (light purple), dashed connectors | `#6631d7` | Message Broker (RabbitMQ) and the async connectors into/out of it |
| `#adf0c7` (light green) | `#087429` | The one NoSQL data store (Forum Service's MongoDB), to visually flag it as different tech from everything else's Postgres |

No API gateway — the UI calls straight into whichever composite (or atomic,
for simple reads) owns that capability.

**Layout pattern:** one Miro frame per composite service. Inside each frame:
UI box at top, the composite directly below it, the atomic services (and
Forum, and the broker, and the wrapper) it calls laid out below/around it.
Solid connectors = synchronous HTTP request/response (arrow `both` for
request+response pairs, `end` for one-way). Dashed purple connectors =
asynchronous messaging through the broker.

**Call annotation style:** numbered `N. HTTP <Verb> <path> {payload}` text
labels placed near each connector, in call order, request and response legs
numbered separately.

## Design decisions from this revision

- **Notifications are asynchronous.** Every composite publishes to a
  **Message Broker (RabbitMQ)** instead of calling Notification Service
  directly over HTTP; Notification Service consumes off the queue and then
  synchronously calls the Email/SMS Wrapper to actually deliver. This is the
  one deliberately async path in the system — everything else stays
  synchronous REST/JSON. Rationale: notification delivery is not on the
  critical path of any user-facing request (the booking/request/registration
  should succeed or fail independently of whether the email actually sends),
  so decoupling it avoids the composite waiting on a slow/unreliable third
  party.
- **Draft Event Requests stay synchronous.** Saving a draft is a single-entity
  write straight to Event Service with no cross-service side effects and no
  external call — the user expects an immediate "saved" confirmation, so
  sync request/response is the right fit. No diagram shows this as a
  composite flow; it's plain atomic CRUD on Event Service.
- **New atomic: Forum / Communication Service**, backed by **MongoDB (NoSQL)**
  instead of Postgres. It stores all communication tied to a request —
  clarification requests, approval/rejection reasons, general comments —
  keyed by `entityType` + `entityId` (e.g. `EVENT`, `BOOKING`,
  `EQUIPMENT_REQUEST`). Rationale for NoSQL: these entries are variable-shape,
  append-only, and never need relational joins, so a document store fits
  better than forcing them into a fixed schema — a legitimate "polyglot
  persistence" choice worth calling out explicitly in the diagram (every
  other service keeps its own Postgres schema).
- **New composite: Coordinator Assignment Service**, split out from Event
  Workflow Service. Assigning/reassigning the Event Coordinator on an event
  is its own business process (look up eligible coordinators, update the
  event, log the reason for reassignment, notify) and doesn't need to live
  inside the broader change/cancellation-impact workflow.
- **Venue Booking Service** now explicitly checks **suitability** (via Venue
  Service) *before* checking for booking **conflicts** (via Booking Conflict
  Service). Like Equipment Reservation Service, it's two sub-flows in one
  frame: request submission (persists the booking as `pending_review` in
  **Venue Availabilities Service**) and a separate venue-staff
  approval/rejection sub-flow (updates the Venue Availabilities record, logs
  the decision reason to Forum Service, and notifies asynchronously).
- **Booking Conflict Service owns the conflict-detection algorithm only** —
  given a venue + time window, it checks for overlaps. It does **not** hold
  the booking records themselves; those live in the separate **Venue
  Availabilities Service** (id, eventId, venueId, status, proposed date/time,
  decision reason). These are two different atomics, not one.
- **Equipment Reservation Service** calls **Equipment Availability Service**
  only — not Equipment Service. Equipment Availability Service owns both the
  availability-checking algorithm *and* the actual reservation records
  (checked/held at submission, committed or released on approval/rejection).
  Equipment Service is a separate atomic that owns the equipment catalogue
  only (types, quantities owned, technical specs) and holds no reservation
  data — this composite's flow never needs to call it. This mirrors the
  Venue Booking Service / Booking Conflict Service + Venue Availabilities
  split. It also now logs to Forum Service, but only on the approval/
  rejection sub-flow.

## Full service catalog

**Composites (5):** Event Workflow Service, Coordinator Assignment Service,
Venue Booking Service, Equipment Reservation Service, Attendee Registration
Service.

**Atomics (10, each own Postgres schema except Forum):** User, Event, Venue,
Booking Conflict (the conflict-detection algorithm only), Venue Availabilities
(the actual venue booking records: id, eventId, venueId, status, proposed
date/time, decision reason), Equipment, Equipment Availability (equipment
reservation records + availability-checking algorithm), Registration,
Notification, Forum / Communication (MongoDB).

**Infra:** Message Broker (RabbitMQ, async notifications only), Email/SMS
Wrapper (called only by Notification Service).

## Diagram 1 — Venue Booking Service (composite, two sub-flows)

**Sub-flow A — booking request submission:**

1. `HTTP POST /booking-requests {eventId, venueId, proposedDate, startTime, endTime, expectedAttendance}` — UI → Venue Booking Service
2. `HTTP GET /events/{eventId}` — Venue Booking Service → Event Service
3. `HTTP 200 Resp {expectedAttendance, date, startTime, endTime}` — Event Service → Venue Booking Service
4. `HTTP GET /venues/{venueId}` — Venue Booking Service → Venue Service
5. `HTTP 200 Resp {capacity, facilities, accessibility, layouts}` — Venue Service → Venue Booking Service
6. `HTTP POST /venues/{venueId}/suitability-check {expectedAttendance, requiredFacilities}` — Venue Booking Service → Venue Service
7. `HTTP 200 Resp {suitable, reasons}` — Venue Service → Venue Booking Service
8. `HTTP POST /conflicts/check {venueId, date, startTime, endTime}` — Venue Booking Service → Booking Conflict Service
9. `HTTP 200 Resp {hasConflict, conflictingBookingIds}` — Booking Conflict Service → Venue Booking Service
10. `HTTP POST /venue-availabilities {eventId, venueId, proposedDate, startTime, endTime, status: pending_review}` — Venue Booking Service → Venue Availabilities Service
11. `HTTP 201 Resp {bookingId, status: pending_review}` — Venue Availabilities Service → Venue Booking Service
12. `HTTP 201 Resp {bookingId, status: pending_review}` — Venue Booking Service → UI

**Sub-flow B — venue staff approval/rejection** (continues once Venue Staff act on the pending request):

13. `HTTP PATCH /booking-requests/{bookingId}/decision {decision, reason}` — UI → Venue Booking Service
14. `HTTP PATCH /venue-availabilities/{bookingId} {status: approved|rejected}` — Venue Booking Service → Venue Availabilities Service
15. `HTTP 200 Resp {bookingId, status}` — Venue Availabilities Service → Venue Booking Service
16. `HTTP POST /forum/entries {entityType: BOOKING, entityId, type, message: reason}` — Venue Booking Service → Forum Service
17. `HTTP 201 Resp {entryId}` — Forum Service → Venue Booking Service
18. `PUBLISH notifications.queue {userId, type: BOOKING_DECISION, eventId, venueId, decision}` — Venue Booking Service → Message Broker (async)
19. `HTTP POST /send {channel, to, template, data}` — Notification Service → Email/SMS Wrapper
20. `HTTP 200 Resp {bookingId, status}` — Venue Booking Service → UI

## Diagram 2 — Event Workflow Service (composite)

1. `HTTP POST /events/{eventId}/change-requests {changedFields, reason}` — UI → Event Service
2. `HTTP 201 Resp {changeRequestId, status}` — Event Service → UI
3. `HTTP POST /workflows/event-change {eventId, changeRequestId, changedFields}` — Event Service → Event Workflow Service
4. `HTTP POST /conflicts/check {venueId, newDate, newStartTime, newEndTime}` — Event Workflow Service → Booking Conflict Service
5. `HTTP 200 Resp {hasConflict}` — Booking Conflict Service → Event Workflow Service
6. `HTTP GET /equipment-availability/reservations?eventId={eventId}` — Event Workflow Service → Equipment Availability Service
7. `HTTP 200 Resp {reservationId, equipmentId, quantity}` — Equipment Availability Service → Event Workflow Service
8. `HTTP POST /forum/entries {entityType: EVENT, entityId, type, message}` — Event Workflow Service → Forum Service
9. `HTTP 201 Resp {entryId}` — Forum Service → Event Workflow Service
10. `PUBLISH notifications.queue {userIds, type: EVENT_CHANGED, eventId, impact}` — Event Workflow Service → Message Broker (async)
11. `HTTP POST /send {channel, to, template, data}` — Notification Service → Email/SMS Wrapper

## Diagram 3 — Coordinator Assignment Service (composite)

1. `HTTP POST /events/{eventId}/assign-coordinator {coordinatorId}` — UI → Coordinator Assignment Service
2. `HTTP GET /users?role=EventCoordinator&available=true` — Coordinator Assignment Service → User Service
3. `HTTP 200 Resp {coordinators}` — User Service → Coordinator Assignment Service
4. `HTTP PATCH /events/{eventId} {assignedCoordinatorId}` — Coordinator Assignment Service → Event Service
5. `HTTP 200 Resp {eventId, assignedCoordinatorId}` — Event Service → Coordinator Assignment Service
6. `HTTP POST /forum/entries {entityType: EVENT, entityId, type: ASSIGNMENT_NOTE, message}` — Coordinator Assignment Service → Forum Service
7. `HTTP 201 Resp {entryId}` — Forum Service → Coordinator Assignment Service
8. `PUBLISH notifications.queue {userId: coordinatorId, type: COORDINATOR_ASSIGNED, eventId}` — Coordinator Assignment Service → Message Broker (async)
9. `HTTP POST /send {channel, to, template, data}` — Notification Service → Email/SMS Wrapper
10. `HTTP 200 Resp {eventId, assignedCoordinatorId}` — Coordinator Assignment Service → UI

## Diagram 4 — Equipment Reservation Service (composite, two sub-flows)

**Sub-flow A — request submission** (ends at step 7):

1. `HTTP POST /equipment-requests {eventId, equipmentType, quantity, technicalRequirements}` — UI → Equipment Reservation Service
2. `HTTP GET /events/{eventId}` — Equipment Reservation Service → Event Service
3. `HTTP 200 Resp {date, startTime, endTime}` — Event Service → Equipment Reservation Service
4. `HTTP POST /equipment-availability/check {equipmentType, quantity, date, startTime, endTime}` — Equipment Reservation Service → Equipment Availability Service
5. `HTTP 200 Resp {available, availableQuantity}` — Equipment Availability Service → Equipment Reservation Service
6. `HTTP POST /equipment-availability/hold {equipmentType, eventId, quantity, startTime, endTime, status: pending_review}` — Equipment Reservation Service → Equipment Availability Service
7. `HTTP 201 Resp {requestId, status: pending_review}` — Equipment Reservation Service → UI

**Sub-flow B — approval/rejection** (continues from step 8): Technical Support Staff's decision updates Equipment Availability directly — no call to Equipment Service, which holds the catalogue only and no reservation data.

8. `HTTP PATCH /equipment-requests/{requestId}/decision {decision, reason}` — UI → Equipment Reservation Service
9. `HTTP PATCH /equipment-availability/{requestId} {status: approved|rejected}` — Equipment Reservation Service → Equipment Availability Service (commits the quantity on approval, releases the hold on rejection)
10. `HTTP 200 Resp {requestId, status}` — Equipment Availability Service → Equipment Reservation Service
11. `HTTP POST /forum/entries {entityType: EQUIPMENT_REQUEST, entityId, type, message: reason}` — Equipment Reservation Service → Forum Service
12. `HTTP 201 Resp {entryId}` — Forum Service → Equipment Reservation Service
13. `PUBLISH notifications.queue {userId, type: EQUIPMENT_DECISION, eventId, equipmentId}` — Equipment Reservation Service → Message Broker (async)
14. `HTTP POST /send {channel, to, template, data}` — Notification Service → Email/SMS Wrapper
15. `HTTP 200 Resp {requestId, status}` — Equipment Reservation Service → UI

## Diagram 5 — Attendee Registration Service (composite)

1. `HTTP POST /registrations {eventId, attendeeId}` — UI → Attendee Registration Service
2. `HTTP GET /events/{eventId}` — Attendee Registration Service → Event Service
3. `HTTP 200 Resp {status, date, venue, registrationEnabled}` — Event Service → Attendee Registration Service
4. `HTTP POST /registrations {eventId, attendeeId}` — Attendee Registration Service → Registration Service
5. `HTTP 201 Resp {registrationId, status}` — Registration Service → Attendee Registration Service
6. `PUBLISH notifications.queue {userId, type: REGISTRATION_CONFIRMED, eventId}` — Attendee Registration Service → Message Broker (async)
7. `HTTP POST /send {channel, to, template, data}` — Notification Service → Email/SMS Wrapper
8. `HTTP 201 Resp {registrationId, status: confirmed}` — Attendee Registration Service → UI
9. `HTTP DELETE /registrations/{registrationId} → 200 Resp {status: withdrawn}` — UI ↔ Attendee Registration Service ↔ Registration Service

No Forum Service call here — registration doesn't have an approval/rejection
reason or clarification workflow the way event review, venue booking, and
equipment requests do.

## Master SOA Overview

One frame tying all five composites to all ten atomics, the broker, and the
wrapper, in the same UI-bar / composite-row / atomic-row / DB-cylinder-row
layout as the reference jpg. Atomic services never call each other or another
service directly (matches the SOA module's "atomic implies independent of
other services" principle) — only composites reach into atomics, into Forum,
and into the broker.