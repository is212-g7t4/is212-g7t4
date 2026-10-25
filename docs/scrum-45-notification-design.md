# SCRUM-45 — Event Organiser Status and Update Notifications

Status (October 21, 2026): agreed design implemented across tickets 01–04; see [verification summary](scrum-45-verification-summary.md) for combined verification. Independent review and ticket closure remain pending.

Historical note: this document began as an interview with implementation not yet authorised. The confirmation and verification sections below preserve that original design-stage chronology, not the current delivery status.

## Confirmed scope

- Notify only the Event Organiser who submitted the request, not the Lead Coordinator, assigned coordinator, or other organisers.
- Reuse the existing persistent in-app notification bell, inbox, read/unread behaviour and delivery logic. Email and push are out of scope.
- A successfully recorded approval generates a decision notification with event name, approval decision, and a link to decision details.
- A successfully recorded rejection generates a decision notification with event name, rejection decision, rejection reason, and a link to decision details.
- Each successfully recorded initial assignment or reassignment generates a separate notification with event name, the newly assigned coordinator's name, and an event-details link.
- Approval and assignment recorded together generate two separate notifications.
- Cover every supported successful approval/rejection mutation path. Changing approval permissions is outside this story.

## Confirmed delivery and history behaviour

- A temporary notification-delivery failure does not undo a successful decision or assignment. Delivery retries automatically without duplicate inbox entries.
- Failed actions and unchanged coordinator assignments generate no notifications.
- Notifications describe the recorded change: successive Alice and Bob assignments retain their respective coordinator names. The linked page shows current event details.
- Legacy requests without a submitting organiser remain actionable, but no organiser notification is sent. Record a diagnostic rather than guessing a recipient or broadcasting. Such records cannot satisfy notification delivery until ownership is repaired.

## Confirmed linked-page change

Reuse the organiser event-details page for both notification types. Add the recorded decision and rejection reason to this page rather than introducing a separate screen.

## Confirmed delivery architecture

- Event Service saves notification work in the same transaction as each supported decision or assignment mutation. A rollback must not leave notification work behind.
- A separately run worker hosted by Event Workflow Service retrieves pending work through Event Service's internal HTTP API and publishes through the existing RabbitMQ notification pipeline. Event Service does not call other services or RabbitMQ.
- This explicitly extends Event Workflow's remit. See `adr/0001-event-notification-delivery-ownership.md` for alternatives and rationale.
- Retain the recipient, event name, decision/rejection reason, and assignment coordinator ID belonging to each recorded change rather than rebuilding these from current event state.
- Resolve coordinator names by the saved coordinator ID, then freeze the prepared notification content before publishing. Names reflect the first successful preparation, not necessarily the spelling at assignment time.
- Retry transient user-lookup failures. Missing coordinator records or unusable names hold that notification as a diagnosed failure until repaired and retried; do not substitute a different coordinator or an ID-only label. Other notifications continue delivering.
- Existing architecture diagrams suggesting Event Service calls Event Workflow outward conflict with `AGENTS.md`; this design follows the latter's service-boundary rule.

## Confirmed rollout and authentication boundaries

- Retain existing asynchronous delivery and inbox refresh behaviour; instant live updates are not required.
- Generate notifications only for decisions and assignments recorded after feature enablement. No historical backfill.
- Reuse the current development-only notification identity mechanism for the project demo. Test recipient isolation under that mechanism; do not claim production-authenticated security. Production authentication remains a separate requirement.

## Original interview-stage remaining approval (historical)
- Confirm shared understanding before implementation; select the implementation branch/base separately.

## Original verification requirements (now mapped in final verification)

Tests must trace to the supplied ACs and cover both decision mutation paths, initial assignment, reassignment, separate approval/assignment notifications, correct recipient isolation, rejection reason and destination rendering, retries/deduplication, failed and unchanged actions, successive assignments, and missing legacy recipients. No implementation tests have been run during this interview.
