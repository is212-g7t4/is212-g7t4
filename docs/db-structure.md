# ConnectSphere C4 database structure

Revised after the Week 7 customer changes (as of 9 Oct 2026).

**Conventions**

- One Supabase (Postgres) project; each service owns its own tables, so foreign keys across services are real FKs.
- The Forum service uses MongoDB and is planned (bonus feature), so its references to SQL rows are logical only.
- Every time column is `TIMESTAMPTZ` (timezone-aware).
- Existing column names are kept; only new columns follow the `xxxAt` / `xxxBy` pattern.
- `status` columns stay `VARCHAR(50)`; the allowed values are still to be defined by the team.
- Single-row validation rules are enforced in the service code, not as database `CHECK` constraints: a booking or closure must end after it starts, and `quantityReserved` must be between 0 and `quantityRequested`.
- `UNIQUE` rules stay in the database, because only the database can block two simultaneous inserts.
- **Change** column: `new` = added, `changed` = type or constraint changed, blank = as before.

---

## Event service

### Event

| Column | Type / constraint | Change | What it is for and how it is used |
|---|---|---|---|
| eventId | UUID (PK) | | Unique ID of the event, used by every other table to point at it. |
| eventName | VARCHAR(255) | | The event's title, shown in queues, lists and notifications. |
| purpose | TEXT | new | Why the event is being held, captured on the request form and editable as a low-impact field. |
| description | TEXT | | Longer free-text details of the event, shown on the event page. |
| expectedAttendance | INTEGER | | Expected headcount, compared against venue capacity and used as the registration cap. |
| preferredStartDate | TIMESTAMPTZ | changed | When the organiser wants the event to start, used for venue search and equipment availability. |
| preferredEndDate | TIMESTAMPTZ | changed | When the organiser wants the event to end, used together with the start date. |
| status | VARCHAR(50) | | The event's current stage, which controls what actions each role can take. |
| organiserId | UUID (FK User) | | The Event Organiser who owns the request, used to scope what they can see and edit. |
| coordinatorId | UUID (FK User), nullable | | The currently assigned coordinator; empty means the event sits in the Lead's unassigned queue. |
| submissionDate | TIMESTAMPTZ, nullable | changed | When the request was submitted (empty while a draft), shown in the unassigned queue. |
| venueRequirements | TEXT | | What the organiser needs from a venue, read by the coordinator when searching. |
| accessibilityNeeds | TEXT | | Accessibility requirements, read by the coordinator and the Safety Officer. |
| equipmentRequirements | TEXT | | Equipment the organiser asks for, used by the coordinator to raise equipment requests. |
| registrationNeeds | TEXT | | Free-text notes on how attendee registration should work. |
| registrationEnabled | BOOLEAN NOT NULL DEFAULT FALSE | new | Switch that tells the system whether attendees may register for this event. |
| rejectionReason | TEXT | new | The coordinator's reason when the request is rejected, shown to the organiser. |
| assignedBy | UUID (FK User) | | The Lead who made the latest assignment, shown on the event detail page. |
| assignedAt | TIMESTAMPTZ | changed | When the latest assignment was made, shown on the event detail page. |
| previousCoordinatorID | UUID (FK User) | | The coordinator replaced in the latest reassignment, used to notify them and remove their access. |

### EventChangeReq

| Column | Type / constraint | Change | What it is for and how it is used |
|---|---|---|---|
| changeId | UUID (PK) | | Unique ID of one change request. |
| eventId | UUID (FK Event) | | The event the organiser wants changed. |
| requestedChanges | JSONB | | The fields and new values requested, applied to the event if approved. |
| status | VARCHAR(50) | | Whether the request is pending, approved or rejected. |
| requestDate | TIMESTAMPTZ | changed | When the organiser submitted the change request, used to order the coordinator's queue. |
| rejectionReason | TEXT | | The coordinator's reason for refusing the change, shown to the organiser. |
| reviewDate | TIMESTAMPTZ | changed | When the coordinator decided on the request. |
| reviewedBy | UUID (FK User) | | The coordinator who decided, kept for accountability. |

---

## User service

### User

| Column | Type / constraint | Change | What it is for and how it is used |
|---|---|---|---|
| userId | UUID (PK) | | Unique ID of a person, referenced wherever a table records who did something. |
| username | VARCHAR(255) | | Display name shown across the app, including attendee lists. |
| email | VARCHAR(255) UNIQUE | changed | Login and contact email; unique so two accounts cannot share one address. |
| role | VARCHAR(50) | | The user's single role (for example Event Coordinator Lead or Safety Officer), which decides their permissions. |
| organization | VARCHAR(255) | | The organisation the user belongs to, shown on registration lists. |
| contactDetails | TEXT | | Extra contact information such as a phone number. |

---

## Equipment service

### Equipment (unchanged)

| Column | Type / constraint | Change | What it is for and how it is used |
|---|---|---|---|
| equipmentId | UUID (PK) | | Unique ID of a catalogue item, referenced by equipment requests. |
| equipmentType | VARCHAR(100) | | The kind of equipment (for example projector), used when listing and requesting. |
| description | TEXT | | Details of the item to help Technical Support and coordinators choose. |
| totalQuantity | INTEGER | | How many units exist in total, the ceiling for the availability calculation. |
| location | VARCHAR(255) | | Where the equipment is stored. |
| operationalStatus | VARCHAR(50) | | Whether the item is usable, so unavailable equipment is not offered. |

---

## Venue service

### Venue

| Column | Type / constraint | Change | What it is for and how it is used |
|---|---|---|---|
| venueId | UUID (PK) | | Unique ID of a venue, referenced by bookings and closures. |
| venueName | VARCHAR(255) | | The venue's name, shown in search results and the calendar. |
| location | VARCHAR(255) | | Where the venue is, used as a search filter. |
| maxCapacity | INTEGER | | Maximum people allowed, compared with expected attendance for suitability and safety. |
| facilities | JSONB | | List of facilities the venue has, used for search filtering and suitability checks. |
| accessibility | TEXT | | Accessibility features of the venue, read by coordinators and the Safety Officer. |
| supportedLayouts | JSONB | | Room layouts the venue supports, used as a search filter. |
| operatingInfo | TEXT | new, optional | Opening hours and access rules, shown on the venue page (from the Release 1 catalogue spec). |
| operationalStatus | VARCHAR(50) | meaning narrowed | Whether the venue is in use at all (Active or Inactive); retired venues are hidden from search. |
| setupTimeMinutes | INTEGER NOT NULL DEFAULT 0 | changed | Preparation time before each event, subtracted from the start time when checking availability. |
| turnaroundTimeMinutes | INTEGER NOT NULL DEFAULT 0 | changed | Reset time after each event, added to the end time when checking availability. |
| emergencyAccessDetails | TEXT | | Exits, assembly points and emergency vehicle access, shown on the Safety Officer's review page. |
| knownRestrictions | TEXT | | Restrictions such as noise curfews or load limits, shown on the Safety Officer's review page. |
| safetyInfoUpdatedBy | UUID (FK User) | | The Venue Staff member who last edited the safety information. |
| safetyInfoUpdatedAt | TIMESTAMPTZ | changed | When the safety information was last edited. |

---

## Venue Availability service

### VenueBooking

One row is one venue arrangement for one event. It starts either as a hold (placed by Venue Staff) or as a booking request (placed by the coordinator), and an event can have several rows.

| Column | Type / constraint | Change | What it is for and how it is used |
|---|---|---|---|
| bookingId | UUID (PK) | | Unique ID of one venue arrangement. |
| eventId | UUID (FK Event) | | The event this arrangement belongs to; several bookings can share one event. |
| venueId | UUID (FK Venue) | | The venue being held or booked. |
| requestedStartTime | TIMESTAMPTZ NOT NULL | | Advertised start of the booking, padded with setup time when checking for conflicts. |
| requestedEndTime | TIMESTAMPTZ NOT NULL | | Advertised end of the booking, padded with turnaround time when checking for conflicts. |
| venueRequirements | TEXT | | What this specific booking needs from the venue, read by Venue Staff when deciding. |
| status | VARCHAR(50) | | The arrangement's current state (for example On Hold, Pending, Approved, Rejected, Expired). |
| requestedBy | UUID (FK User), nullable | changed | The coordinator who submitted the request; empty while the row is only a hold. |
| requestedAt | TIMESTAMPTZ | new | When the coordinator submitted the request, used to order Venue Staff's queue. |
| reviewedBy | UUID (FK User) | | The Venue Staff member who approved or rejected the request. |
| reviewedAt | TIMESTAMPTZ | new | When the request was approved or rejected. |
| rejectionReason | TEXT | | Venue Staff's reason for rejecting, shown to the coordinator so they can plan an alternative. |
| heldBy | UUID (FK User) | | The Venue Staff member who placed the hold. |
| heldAt | TIMESTAMPTZ | new | When the hold was placed, shown on the hold details page. |
| holdExpiresAt | TIMESTAMPTZ | changed | Deadline of the hold; the Hold Checker expires the hold once this time passes. |
| reminderSentAt | TIMESTAMPTZ | new, optional | When the 3-day reminder was sent, so the Hold Checker does not publish it again every minute. |
| conflictReason | VARCHAR(50), nullable | replaces conflictFlag | Why the booking is flagged (buffer overlap or venue closure); empty means no problem. |
| closureId | UUID (FK VenueClosure), nullable | new | The closure that affected this booking, used to show the closure period and reason to the coordinator. |

### VenueClosure

| Column | Type / constraint | Change | What it is for and how it is used |
|---|---|---|---|
| closureId | UUID (PK) | | Unique ID of one period of temporary unavailability. |
| venueId | UUID (FK Venue) | | The venue being closed. |
| startDateTime | TIMESTAMPTZ NOT NULL | changed | When the closure begins, used by the availability check and the calendar. |
| endDateTime | TIMESTAMPTZ NOT NULL | changed | When the closure ends, after which the venue is bookable again. |
| reason | TEXT NOT NULL | changed | The operational reason (maintenance, renovation and so on), shown on the calendar and in notifications. |
| createdBy | UUID (FK User) | | The Venue Staff member who recorded the closure. |
| createdAt | TIMESTAMPTZ | changed | When the closure was recorded. |

---

## Equipment Availability service

### EquipmentRequest

The time window for availability comes from the event's `preferredStartDate` and `preferredEndDate`.

| Column | Type / constraint | Change | What it is for and how it is used |
|---|---|---|---|
| equipRequestId | UUID (PK) | | Unique ID of one equipment request line. |
| eventId | UUID (FK Event) | | The event the equipment is for. |
| equipmentId | UUID (FK Equipment) | | The catalogue item being requested. |
| quantityRequested | INTEGER | | How many units the coordinator asked for. |
| quantityReserved | INTEGER NOT NULL DEFAULT 0 | new | How many units are actually reserved (can be partial), deducted from availability for overlapping events. |
| technicalRequirements | TEXT | | Technical notes for Technical Support Staff, such as setup needs. |
| status | VARCHAR(50) | | The request's current state (for example Pending, Reserved, Rejected). |
| requestedBy | UUID (FK User) | new | The coordinator who raised the request. |
| requestedAt | TIMESTAMPTZ | new | When the request was raised, used to order Technical Support's queue. |
| reviewedBy | UUID (FK User) | | The Technical Support Staff member who handled the request. |
| reviewedAt | TIMESTAMPTZ | new | When the request was handled. |
| rejectionReason | TEXT | new | Why the request was refused, shown to the coordinator. |

---

## Registration service

### Registration

| Column | Type / constraint | Change | What it is for and how it is used |
|---|---|---|---|
| registrationId | UUID (PK) | | Unique ID of one attendee's registration for one event. |
| eventId | UUID (FK Event) | | The event being registered for. |
| attendeeId | UUID (FK User) | | The attendee's account, used to look up their name, email and organisation. |
| registrationDate | TIMESTAMPTZ | changed | When the attendee registered, shown on the coordinator's registration list. |
| status | VARCHAR(50) | | Confirmed or Withdrawn; confirmed rows are counted against expected attendance. |
| UNIQUE (eventId, attendeeId) | table rule | new | Stops the same attendee registering twice; re-registering after withdrawal reuses the row. |

Removed: `attendeeName`, `attendeeEmail`, `attendeeOrganization` (these come from `User`).

---

## Notification service

### Notification

| Column | Type / constraint | Change | What it is for and how it is used |
|---|---|---|---|
| notificationId | UUID (PK) | | Unique ID of one in-app notification. |
| recipientId | UUID (FK User) | | The one user who should see it; the polling endpoint filters on this. |
| type | VARCHAR(50) | | The kind of notification (for example coordinator assigned), used to choose the wording and icon. |
| eventId | UUID (FK Event) | | The event it is about, used for the link back to the event page. |
| payload | JSONB | | Extra details to display, such as venue name, closure period or decision reason. |
| dedupeKey | VARCHAR(255) | | A fixed key per real-world occurrence, so a retried message does not create a second notification. |
| createdAt | TIMESTAMPTZ | changed | When it was created, used to sort newest first and as the polling cursor. |
| readAt | TIMESTAMPTZ | changed | When the user opened it; empty means unread and counts toward the badge. |
| UNIQUE (recipientId, dedupeKey) | table rule | | Enforces the no-duplicates rule for each recipient. |
| INDEX (recipientId, createdAt) | index | new | Speeds up the front-end's poll for one user's notifications, newest first. |

---

## Safety Check service

### SafetyCheck

One row per review round, so earlier decisions stay visible as history.

| Column | Type / constraint | Change | What it is for and how it is used |
|---|---|---|---|
| safetyCheckId | UUID (PK) | | Unique ID of one safety review round. |
| eventId | UUID (FK Event) | | The event being reviewed. |
| roundNumber | INTEGER NOT NULL | new | 1 for the first submission and higher for resubmissions, used to label and order rounds. |
| submittedBy | UUID (FK User) | | The coordinator who submitted the event for review. |
| submittedAt | TIMESTAMPTZ | changed | When it was submitted, shown in the Safety Officer's queue. |
| equipmentPlacementNotes | TEXT | | The coordinator's notes on where equipment will go, read by the Safety Officer. |
| crowdMovementNotes | TEXT | | The coordinator's notes on expected crowd flow, read by the Safety Officer. |
| status | VARCHAR(50) | | The round's outcome (for example Pending, Approved, Changes Requested, Rejected). |
| decidedBy | UUID (FK User) | | The Safety Officer who decided, taken from the verified login. |
| decidedAt | TIMESTAMPTZ | changed | When the decision was made. |
| remarks | TEXT | | The Safety Officer's overall reason or comments, shown to the coordinator. |
| UNIQUE (eventId, roundNumber) | table rule | new | Stops duplicate safety checks for the same round, such as from a double submit. |

Removed: `flaggedAreas` (replaced by `SafetyCheckFlag`).

### SafetyCheckFlag (new table)

One row per item the Safety Officer flags when requesting changes.

| Column | Type / constraint | Change | What it is for and how it is used |
|---|---|---|---|
| flagId | UUID (PK) | new | Unique ID of one flagged item. |
| safetyCheckId | UUID (FK SafetyCheck) | new | The review round the flag belongs to. |
| area | VARCHAR(50) | new | Which planning area is affected (venue arrangement, technical arrangement or event details). |
| bookingId | UUID (FK VenueBooking), nullable | new | The specific venue booking Venue Staff must re-review; empty for other areas. |
| equipRequestId | UUID (FK EquipmentRequest), nullable | new | The specific equipment request Technical Support must re-review; empty for other areas. |
| changeRequired | TEXT | new | What the Safety Officer wants changed for this item, shown to the coordinator. |

---

## Forum service (MongoDB, planned)

Will hold comments, decision reasons and the event-specific history log.

### Thread

| Field | Type | Change | What it is for and how it is used |
|---|---|---|---|
| _id | ObjectId (PK) | | Unique ID of a conversation thread. |
| entityId | UUID (indexed) | | The SQL record the thread is about, such as an event or booking, used to load its thread. |
| entityType | String | | The kind of record `entityId` points at, so the ID is looked up in the right table. |
| status | String | | Whether the thread is open or closed. |
| participants | Array | | User IDs allowed to read and post in the thread. |

### Message

| Field | Type | Change | What it is for and how it is used |
|---|---|---|---|
| _id | ObjectId (PK) | was messageId UUID | Unique ID of one message, in MongoDB's standard key field. |
| threadId | ObjectId (logical FK Thread) | | The thread the message belongs to. |
| senderId | UUID | | The user who posted it (or the system for log entries). |
| type | String | new | Whether it is a comment, a decision reason or a change-log entry, used to filter the history view. |
| content | String | changed | The message text. |
| timestamp | Date | changed | When it was posted, used to order the thread. |
| attachments | Array | changed | Any files attached to the message. |

---

## Still open

- **Status values:** the allowed values for every `status` column are still to be listed by the team. `On Hold` should require `holdExpiresAt`, and bookings and equipment requests need a status for "sent back for safety re-review".
- **Suitability checking:** `Venue.accessibility` and the event's requirement fields are free text, so the system cannot compare them automatically.
- **Assignment history:** only the latest assignment is stored on `Event`; full reassignment history waits for the Forum service.
- **Optional columns:** `Venue.operatingInfo` and `VenueBooking.reminderSentAt` can be dropped without breaking a Week 7 requirement.
- **Story pool:** the "Reject Affected Bookings" story still says auto-reject and needs rewording to match flagging.