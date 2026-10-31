# Microservices Catalog

What each service on the `is212 archi diagrams` Miro board does. Based on
the board state as of the latest edits (5 composite-flow frames + 1 Master
SOA Overview frame). See `microservices-diagram-notes.md` for the visual
style conventions and the numbered call sequences. This is a design reference
with planned flows, not an exhaustive implementation inventory; use
[INDEX.md](../INDEX.md) and service READMEs for current implemented scope.

## UI

**Event Management System (UI)** — the React SPA. Calls straight into
whichever composite (or atomic, for simple reads) owns the capability it
needs. No API gateway in front of it.

## Composite services

Composites hold no data of their own — they orchestrate atomics and
the Message Broker to carry out one business process, and are the only
services allowed to call other services.

### Event Workflow Service — internally labelled "Change/Cancel Service"

Covers event lifecycle events that aren't simple CRUD on Event Service:
re-validating existing venue/equipment commitments when an organiser
requests a change, and cascading a cancellation. Calls Event Service, Venue
Availability, Equipment Request, Equipment and the Message
Broker (async notify).

**Open question flagged on the board (not yet resolved):** whether this
composite is needed at all, since an Event Coordinator editing an event
would already go through Venue Booking Service / Equipment Reservation
Service's own edit paths — see the sticky note on that frame. Treat this
composite's scope as provisional until that's settled.

### Coordinator Assignment Service

Assigns or reassigns the Event Coordinator on an event: looks up eligible
coordinators (User Service), updates the event record (Event Service), and notifies the
assigned coordinator asynchronously (Message Broker).

### Venue Booking Service

Processes venue booking requests end-to-end: checks each request's suitability
(especially venue capacity vs. that booking's required capacity), then persists
the booking request and checks for double-booking via Venue Availability
Service (which owns both the records and the conflict check — see the
Atomic services table below; this merges what used to be two separate
services, Booking Conflict and Venue Availabilities), and — only on the
venue staff approval/rejection sub-flow — records the decision reason on the
booking and notifies asynchronously.

### Equipment Reservation Service

Processes equipment requests end-to-end. Two sub-flows in one frame:
- **Request submission** (ends at step 7): checks assignment, event state and physical availability (event window
  from Event Service and physical status from Equipment Service) and
  records the request as `Pending`; submission does not reserve stock.
- **Approval/rejection** (continues from step 8): Technical Support Staff's
  composite supplies catalogue stock, event/overlap context and the exact
  Pending request IDs. Equipment Request Service re-reads its current requests
  after one shared transaction-level PostgreSQL advisory lock (READ COMMITTED),
  checks own/overlapping Approved quantities plus grouped candidates, and saves
  only those IDs and their decision outbox records atomically. Rejection needs
  no stock check. Notifications are asynchronous. Built so far:
  read-time availability and transactional approval enforcement (see
  [Equipment Reservation README](../services/equipment-reservation-service/README.md)).
  This transaction protects owner allocation reads and approval writes; it does
  not prove external input provenance or coordinate catalogue/event mutations.

### Attendee Registration Service

Registers/withdraws an attendee for an event: validates the event is
confirmed and open for registration (Event Service), creates or removes the
registration record (Registration Service), and notifies asynchronously.

Registration rows store only the attendee's ID, so this composite also adds
the attendee's name, email and organisation from User Service when listing
registrations: `GET /registrations?attendeeId=` (the attendee's own) and
`GET /events/<eventId>/registrations` (the coordinator's list for one event).

## Atomic services

Atomics never call each other or any other service — only a composite
reaches into an atomic. Each owns exactly one entity/concern and its own
data store (Postgres unless noted).

| Service | Owns |
|---|---|
| **User** | User accounts, roles, authentication |
| **Event** | The Event entity: details, status, change-request records |
| **Venue** | Venue catalogue — capacity, facilities, accessibility, layouts. Also runs the suitability-check computation (given an event's requirements as input) |
| **Venue Availability** | Venue booking records (id, eventId, venueId, status pending/approved/rejected, proposed date/time, decision reason), timed venue holds with expiry, **and** the overlap/conflict-detection algorithm together — merged design; there is no separate Booking Conflict service or table |
| **Equipment** | Equipment catalogue only — types, quantities owned, location, operational status. Does **not** hold reservation data. Exposes `GET /equipment[?status=]` and `POST /equipment` (Technical Support only); the UI calls it directly |
| **Equipment Request** | The equipment request records (`public."EquipmentRequest"`) and each request's status (Pending → Approved/Rejected). Final approval stock enforcement under one shared transaction-level advisory lock, using catalogue/event inputs supplied by Equipment Reservation; no external HTTP or other service's database access. Decisions and notification outbox records commit together |
| **Registration** | Attendee registration records |
| **Notification** | Notification records; consumes off the Message Broker and calls the Email/SMS Wrapper to deliver |

> **Current implementation note:** Event Service owns append-only
> `clarificationHistory` metadata. Its dedicated endpoints change only the
> Event-owned status/metadata and preserve the original request fields.

## Infrastructure

- **Message Broker (RabbitMQ)** — the only asynchronous path in the system.
  Every composite publishes a notification event here instead of calling
  Notification Service directly; Notification Service consumes off the
  queue. Everything else is synchronous REST/JSON.
