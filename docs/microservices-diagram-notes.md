# Microservices Diagram — Style Reference & Spec

Notes from scanning the reference Miro board ("Microservice Overview",
`https://miro.com/app/board/uXjVG3A1SwU=/` — a TravelLust trip-planning
example, not part of this project) to match its visual conventions for our
own ConnectSphere architecture diagram, plus the resulting spec for our system.

All of this is built on the Miro board `is212 archi diagrams`
(`https://miro.com/app/board/uXjVHqeuVHs=/`), in six frames: five
composite-service flow diagrams and one "Master SOA Overview" tying
everything together. The teammate's ER diagram and the earlier C4 diagrams
on that board are separate and untouched by this spec. The numbered flows mix
implemented and planned work; see [INDEX.md](../INDEX.md) and service READMEs
for current implemented scope. This textual spec omits the cancelled communication
store; older board/C4 artwork is historical and has not been regenerated.

## Reference board conventions

**Color coding (fill / stroke):**

| Fill hex | Stroke hex | Meaning |
|---|---|---|
| `#fff6b6` (light/pale yellow) | `#1a1a1a` (black) | Composite / process service (orchestrates a business capability) |
| `#ffdc4a` (deeper gold yellow) | `#1a1a1a` | Atomic service — one entity, simple CRUD (or a self-contained algorithm) |
| `#c6dcff` (light blue) | `#1a1a1a` | Wrapper service exposing an external system (our one wrapper: Email/SMS delivery) |
| `#305bab` (deep blue) | `#1a1a1a`, white text | UI (React SPA) |
| `#dedaff` (light purple), dashed connectors | `#6631d7` | Message Broker (RabbitMQ) and the async connectors into/out of it |

No API gateway — the UI calls straight into whichever composite (or atomic,
for simple reads) owns that capability.

**Layout pattern:** one Miro frame per composite service. Inside each frame:
UI box at top, the composite directly below it, the atomic services (and
the broker and the wrapper) it calls laid out below/around it.
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
- **New composite: Coordinator Assignment Service**, split out from Event
  Workflow Service. Assigning/reassigning the Event Coordinator on an event
  is its own business process (look up eligible coordinators, update the
  event, log the reason for reassignment, notify) and doesn't need to live
  inside the broader change/cancellation-impact workflow.
- **Venue Booking Service** now explicitly checks **suitability** (via Venue
  Service) *before* persisting the booking and checking for **conflicts**
  (via Venue Availability Service). Like Equipment Reservation Service, it's
  two sub-flows in one frame: request submission (persists the booking as
  `Pending Review` in **Venue Availability Service**, which conflict-checks
  it there) and a separate venue-staff approval/rejection sub-flow (updates
  the Venue Availability record and its decision reason,
  and notifies asynchronously).
- **Venue Availability Service owns both the booking records and the
  conflict-detection algorithm**, in one atomic (`public."VenueBooking"`:
  id, eventId, venueId, status, proposed date/time, decision reason). This
  merges what was originally drafted as two atomics — a stateless "Booking
  Conflict Service" plus a separate "Venue Availabilities Service" — because
  a stateless conflict-checker would have needed to read bookings owned by
  the other service, which atomics can't do (see AGENTS.md). There is no
  separate Booking Conflict service or table.
- **Equipment Reservation Service** calls **Event Service** (event window),
  **Equipment Service** (catalogue, total stock, physical status) and
  **Equipment Request Service** (request records, decisions). It owns the
  read-time availability calculation and supplies catalogue/event inputs for
  approvals. Equipment Request Service owns final enforcement: after one shared
  transaction-level PostgreSQL advisory lock, it re-reads current requests at
  READ COMMITTED and checks stock before committing the exact checked IDs and
  decision outbox records together. Neither atomic calls another service or
  another service's database; `Equipment.operational_status` is never changed
  by a booking. Equipment Service is a separate atomic that owns the
  equipment catalogue only (types, quantities owned, technical specs). The UI
  calls it directly for catalogue reads/writes (`GET /equipment[?status=]`,
  `POST /equipment`).

## Full service catalog

**Composites (5):** Event Workflow Service, Coordinator Assignment Service,
Venue Booking Service, Equipment Reservation Service, Attendee Registration
Service.

**Atomics in these five design frames (8, Postgres-backed):** User, Event, Venue,
Venue Availability (venue booking records — id, eventId, venueId, status,
proposed date/time, decision reason — **and** the conflict-detection
algorithm together, one atomic), Equipment, Equipment Request (equipment
request records, status and final transactional stock enforcement;
catalogue/event inputs and read-time availability come from Equipment Reservation), Registration,
Notification.

**Infra:** Message Broker (RabbitMQ, async notifications only), Email/SMS
Wrapper (called only by Notification Service).

## Diagram 1 — Venue Booking Service (composite, three sub-flows)

**Sub-flow A — booking request submission:**

1. `HTTP POST /booking-requests {eventId, venueId, requestedStartTime, requestedEndTime, requiredCapacity, venueRequirements}` — UI → Venue Booking Service. Each request is independent; several may share one event.
2. `HTTP GET /events/{eventId}` — Venue Booking Service → Event Service
3. `HTTP 200 Resp {expectedAttendance, date, startTime, endTime}` — Event Service → Venue Booking Service
4. `HTTP GET /venues/{venueId}` — Venue Booking Service → Venue Service
5. `HTTP 200 Resp {capacity, facilities, accessibility, layouts}` — Venue Service → Venue Booking Service
6. Venue Booking Service evaluates the selected catalogue venue against this booking's `requiredCapacity` and operational status. It does not use the event's total attendance for venue capacity.
7. `HTTP 200 Resp {suitable, reasons}` — Venue Service → Venue Booking Service
8. `HTTP POST /venue-bookings {eventId, venueId, requestedStartTime, requestedEndTime, requiredCapacity, venueRequirements, requestedBy}` — Venue Booking Service → Venue Availability Service (persists the booking and checks that venue's conflicts against existing Approved bookings there)
9. `HTTP 201 Resp {bookingId, status: Pending Review}` or `HTTP 409 Resp {message}` on conflict — Venue Availability Service → Venue Booking Service
10. `HTTP 201 Resp {bookingId, status: Pending Review}` — Venue Booking Service → UI

**Sub-flow B — venue staff approval/rejection** (continues once Venue Staff act on the pending request):

11. `HTTP PATCH /booking-requests/{bookingId}/approve|reject {reviewedBy, reason}` — UI → Venue Booking Service
12. `HTTP PATCH /venue-bookings/{bookingId}/approve|reject {reviewedBy}` — Venue Booking Service → Venue Availability Service (re-checks for conflicts on approve)
13. `HTTP 200 Resp {bookingId, status}` or `HTTP 409 Resp {message}` on conflict — Venue Availability Service → Venue Booking Service
14. `PUBLISH notifications.queue {userId, type: BOOKING_DECISION, eventId, venueId, decision}` — Venue Booking Service → Message Broker (async)
15. `HTTP POST /send {channel, to, template, data}` — Notification Service → Email/SMS Wrapper
16. `HTTP 200 Resp {bookingId, status}` — Venue Booking Service → UI

**Sub-flow C — venue search** (SCRUM-26; read-only, so no
broker message). Steps 18 and 20 are independent and run at the same time, so
the search costs the slower call rather than their sum:

17. `HTTP GET /venue-search?start=&end=&expectedAttendance=&minCapacity=&location=&layout=&facility=&accessibility=` — UI → Venue Booking Service
18. `HTTP GET /venues?minCapacity=&location=&layout=&facility=&accessibility=` — Venue Booking Service → Venue Service (the suitability check over the catalogue)
19. `HTTP 200 Resp {venues: [...]}` — Venue Service → Venue Booking Service
20. `HTTP GET /venue-bookings/window?dateFrom={start}&dateTo={end}` — Venue Booking Service → Venue Availability Service (every venue's non-rejected bookings overlapping the window, in one call; `GET /venue-bookings` is SCRUM-25's single-venue calendar read)
21. `HTTP 200 Resp {bookings: [...]}` — Venue Availability Service → Venue Booking Service
22. `HTTP 200 Resp {venues: [{...venue, availability}], count}`, or `HTTP 400 Resp {message, missing}` for an incomplete search — Venue Booking Service → UI

## Diagram 2 — Event Workflow Service (composite)

1. `HTTP POST /events/{eventId}/change-requests {changedFields, reason}` — UI → Event Service
2. `HTTP 201 Resp {changeRequestId, status}` — Event Service → UI
3. `HTTP POST /workflows/event-change {eventId, changeRequestId, changedFields}` — Event Service → Event Workflow Service
4. `HTTP POST /venue-bookings/{bookingId}/conflicts-check {newDate, newStartTime, newEndTime}` — Event Workflow Service → Venue Availability Service
5. `HTTP 200 Resp {hasConflict}` — Venue Availability Service → Event Workflow Service
6. Event Workflow Service reads equipment requests from Equipment Request Service and catalogue stock from Equipment Service for edit validation; no separate Equipment Availability service exists.
7. Equipment Request supplies request status/quantity; Equipment supplies catalogue quantity/physical status. These reads are outside the final equipment approval transaction.
8. `PUBLISH notifications.queue {userIds, type: EVENT_CHANGED, eventId, impact}` — Event Workflow Service → Message Broker (async)
9. `HTTP POST /send {channel, to, template, data}` — Notification Service → Email/SMS Wrapper

## Diagram 3 — Coordinator Assignment Service (composite)

1. `HTTP POST /events/{eventId}/assign-coordinator {coordinatorId}` — UI → Coordinator Assignment Service
2. `HTTP GET /users?role=EventCoordinator&available=true` — Coordinator Assignment Service → User Service
3. `HTTP 200 Resp {coordinators}` — User Service → Coordinator Assignment Service
4. `HTTP PATCH /events/{eventId} {assignedCoordinatorId}` — Coordinator Assignment Service → Event Service
5. `HTTP 200 Resp {eventId, assignedCoordinatorId}` — Event Service → Coordinator Assignment Service
6. `PUBLISH notifications.queue {userId: coordinatorId, type: COORDINATOR_ASSIGNED, eventId}` — Coordinator Assignment Service → Message Broker (async)
7. `HTTP POST /send {channel, to, template, data}` — Notification Service → Email/SMS Wrapper
8. `HTTP 200 Resp {eventId, assignedCoordinatorId}` — Coordinator Assignment Service → UI

## Diagram 4 — Equipment Reservation Service (composite, two sub-flows)

> **Approved owner-transaction design:** this supersedes the earlier separate
> Equipment Availability atomic and “no availability logic” descriptions. No new
> service, table or column is introduced. Concurrent catalogue quantity or event
> schedule changes remain outside this transaction guarantee. External input
> provenance is not established by the owner allocation transaction.

**Sub-flow A — request submission:**

1. UI → Equipment Reservation: `POST /equipment-reservations/events/{eventId}/requests`.
2. The composite reads assignment/window from Event and physical stock from Equipment.
3. Equipment Reservation → Equipment Request: `POST /events/{eventId}/equipment-requests`; saves Pending records (no stock hold).

**Sub-flow B — approval/rejection:**

4. UI → Equipment Reservation: `PATCH /equipment-reservations/requests/{requestId}` or `PATCH /equipment-reservations/events/{eventId}`.
5. On approval, the composite gathers catalogue stock, request-holder event summaries and **all** eligible overlapping events, not just events already holding Approved equipment, and fixes the exact checked Pending request IDs.
6. Equipment Reservation → Equipment Request: `PATCH /equipment-requests/{requestId}` or `PATCH /events/{eventId}/equipment-requests`, supplying catalogue/event inputs and the exact checked request IDs. The owner transaction protects its allocation reads and approval writes; this does not establish authentication of the external inputs.
7. Equipment Request acquires the shared transaction-level advisory lock before row locks, then reads its current rows at READ COMMITTED. Own Approved + other overlapping eligible Approved + grouped candidates must fit stock. Unknown/missing context or stale membership/state fails closed. Only checked IDs are approved; decisions and existing per-row outbox records commit or roll back together.
8. Rejection retains its existing Pending-only decision and outbox transaction without a stock check. The composite's dispatcher publishes notifications asynchronously; Email/SMS remains planned.

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

## Master SOA Overview

One frame tying the five composite design frames to their eight atomics, the broker, and the
wrapper, in the same UI-bar / composite-row / atomic-row / DB-cylinder-row
layout as the reference jpg. Atomic services never call each other or another
service directly (matches the SOA module's "atomic implies independent of
other services" principle) — only composites reach into atomics
and into the broker.
