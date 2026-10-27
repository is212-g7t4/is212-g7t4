# ConnectSphere

Shared language for event requests and organiser/coordinator notifications.

## Language

**Submitting Event Organiser**:
The Event Organiser who submitted an event request and receives updates about its decision and coordinator assignment.
_Avoid_: Lead Coordinator when referring to the notification recipient

**Event Request Decision**:
An approval or rejection of an event request. A rejection includes a rejection reason.

**Decision Notification**:
An in-app update to the submitting Event Organiser confirming approval or rejection, identifying the event, and linking to the request's decision details.

**Coordinator Assignment**:
The designation of the coordinator responsible for an event; the initial assignment establishes that responsibility, and reassignment transfers it to another coordinator.

**Coordinator Assignment Notification**:
An in-app update to the submitting Event Organiser identifying the event and newly assigned coordinator, with a link to event details. It is distinct from a decision notification, even when approval and assignment happen together.

**Coordinator Assignment Received Notification**:
An in-app update to the newly assigned Event Coordinator identifying the event, Event Organiser and proposed schedule, with a link to event details.
_Avoid_: Coordinator Assignment Notification, which refers to the organiser-facing update

**Coordinator Removal Notification**:
An in-app update to the previous Event Coordinator stating that they are no longer assigned following reassignment, identifying the event, Event Organiser and proposed schedule without an event link.
