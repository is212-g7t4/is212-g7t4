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
facilities vs. the event's requirements) via Venue Service, checks for
double-booking via Booking Conflict Service, persists the booking request
itself in Venue Availabilities, and — only on the venue staff
approval/rejection sub-flow — logs the decision reason to Forum Service and
notifies asynchronously.

### Equipment Reservation Service

Processes equipment requests end-to-end. Two sub-flows in one frame:
- **Request submission** (ends at step 7): checks availability and records
  the request against Equipment Availability as `pending_review`.
- **Approval/rejection** (continues from step 8): Technical Support Staff's
  decision updates Equipment Availability (commits the quantity on
  approval, releases the hold on rejection), logs to Forum Service, and
  notifies asynchronously.

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
| **Booking Conflict** | The conflict-detection algorithm only — given a venue + time window, checks for overlaps against existing bookings |
| **Venue Availabilities** | The actual venue booking records: id, eventId, venueId, status (pending/approved/rejected), proposed date/time, decision reason |
| **Equipment** | Equipment catalogue only — types, quantities owned, technical specs. Does **not** hold reservation data |
| **Equipment Availability** | The real reservation records and the availability-checking algorithm together: committed quantities per event/time window, and each request's status (pending_review → approved/rejected) |
| **Registration** | Attendee registration records |
| **Notification** | Notification records; consumes off the Message Broker and calls the Email/SMS Wrapper to deliver |
| **Forum / Communication** | **NoSQL (MongoDB).** All communication tied to a request — clarification requests, approval/rejection reasons, comments — keyed by entityType + entityId |

## Infrastructure

- **Message Broker (RabbitMQ)** — the only asynchronous path in the system.
  Every composite publishes a notification event here instead of calling
  Notification Service directly; Notification Service consumes off the
  queue. Everything else is synchronous REST/JSON.
