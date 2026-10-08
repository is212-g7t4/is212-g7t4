# Microservices Catalog

What each service on the `is212 archi diagrams` Miro board does. Based on
the board state as of the latest edits (5 composite-flow frames + 1 Master
SOA Overview frame). See `microservices-diagram-notes.md` for the visual
style conventions and the numbered call sequences.

## UI

**Event Management System (UI)** — the React SPA. Calls straight into
whichever composite (or atomic, for simple reads) owns the capability it
needs. No API gateway in front of it.

## Composite services

Composites hold no data of their own — they orchestrate atomics, Forum, and
the Message Broker to carry out one business process, and are the only
services allowed to call other services.

### Event Workflow Service — internally labelled "Change/Cancel Service"

Covers event lifecycle events that aren't simple CRUD on Event Service:
re-validating existing venue/equipment commitments when an organiser
requests a change, and cascading a cancellation. Calls Event Service, Venue
Availabilities, Equipment Availabilities, Forum Service, and the Message
Broker (async notify).

**Open question flagged on the board (not yet resolved):** whether this
composite is needed at all, since an Event Coordinator editing an event
would already go through Venue Booking Service / Equipment Reservation
Service's own edit paths — see the sticky note on that frame. Treat this
composite's scope as provisional until that's settled.

### Coordinator Assignment Service

Assigns or reassigns the Event Coordinator on an event: looks up eligible
coordinators (User Service), updates the event record (Event Service), logs
the assignment/reassignment reason (Forum Service), and notifies the
assigned coordinator asynchronously (Message Broker).

**Open question flagged on the board:** whether Forum Service is actually
needed here (sticky note: "not sure if forum is needed here") — most
assignments won't have a reason worth logging, only reassignments might.

### Venue Booking Service

Processes venue booking requests end-to-end: checks suitability (capacity/
facilities vs. the event's requirements) via Venue Service, then persists
the booking request and checks for double-booking via Venue Availability
Service (which owns both the records and the conflict check — see the
Atomic services table below; this merges what used to be two separate
services, Booking Conflict and Venue Availabilities), and — only on the
venue staff approval/rejection sub-flow — logs the decision reason to Forum
Service and notifies asynchronously.

### Equipment Reservation Service

Processes equipment requests end-to-end. Two sub-flows in one frame:
- **Request submission** (ends at step 7): checks availability (event window
  from Event Service, stock from Equipment Service, quantities already held
  by other non-rejected events from Equipment Request Service) and
  records the request as `pending_review`.
- **Approval/rejection** (continues from step 8): Technical Support Staff's
  decision is validated against the same availability check (Approve is
  blocked while any line is insufficient) and recorded in Equipment Request
  Service, logs to Forum Service, and notifies asynchronously. Built so far:
  the availability check and the review validation (see
  `services/equipment-reservation-service/README.md`).

### Attendee Registration Service

Registers/withdraws an attendee for an event: validates the event is
confirmed and open for registration (Event Service), creates or removes the
registration record (Registration Service), and notifies asynchronously. No
Forum Service call — registration doesn't have an approval/rejection
reason the way venue and equipment requests do.

## Atomic services

Atomics never call each other or any other service — only a composite
reaches into an atomic. Each owns exactly one entity/concern and its own
data store (Postgres unless noted).

| Service | Owns |
|---|---|
| **User** | User accounts, roles, authentication |
| **Event** | The Event entity: details, status, change-request records |
| **Venue** | Venue catalogue — capacity, facilities, accessibility, layouts. Also runs the suitability-check computation (given an event's requirements as input) |
| **Venue Availability** | Venue booking records (id, eventId, venueId, status pending/approved/rejected, proposed date/time, decision reason) **and** the overlap/conflict-detection algorithm together — merged design; there is no separate Booking Conflict service or table |
| **Equipment** | Equipment catalogue only — types, quantities owned, location, operational status. Does **not** hold reservation data. Exposes `GET /equipment[?status=]` and `POST /equipment` (Technical Support only); the UI calls it directly |
| **Equipment Request** | The equipment request records (`public."EquipmentRequest"`) and each request's status (Pending → Approved/Rejected). No availability logic — that is computed on demand by the Equipment Reservation composite |
| **Registration** | Attendee registration records |
| **Notification** | Notification records; consumes off the Message Broker and calls the Email/SMS Wrapper to deliver |
| **Forum / Communication** | **NoSQL (MongoDB).** All communication tied to a request — clarification requests, approval/rejection reasons, comments — keyed by entityType + entityId |

## Infrastructure

- **Message Broker (RabbitMQ)** — the only asynchronous path in the system.
  Every composite publishes a notification event here instead of calling
  Notification Service directly; Notification Service consumes off the
  queue. Everything else is synchronous REST/JSON.
