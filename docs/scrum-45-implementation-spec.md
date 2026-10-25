# SCRUM-45 — Event Organiser Status and Update Notifications

Status (October 21, 2026): implemented across tickets 01–04; combined ticket 05 verification is recorded in [verification summary](scrum-45-verification-summary.md). Independent standards/specification review and ticket closure remain parent-owned and pending. Tracker publication is not asserted here.

Historical baseline: this specification was originally written during design/first-RED preparation, before production implementation. The original plan below remains a requirements/chronology record, not a current claim that implementation is absent.

## Problem Statement

Submitting Event Organisers need to know whether their event request was approved or rejected, why it was rejected, and who is responsible for coordinating the event. Existing venue notifications do not deliver these updates, and the organiser details screen does not display the rejection reason.

## Solution

Deliver persistent decision and coordinator-assignment notifications to the submitting organiser through the existing bell and inbox. Link to the existing organiser event-details page, extended to display the decision and rejection reason. Record notification work reliably with each successful change and deliver asynchronously without duplicate inbox entries.

## User Stories

The canonical ticket story is: As an Event Organiser, I want to receive an in-app notification when the Lead Coordinator approves or rejects my event request, so that I know the outcome and who is responsible for coordinating my event.

The following are decompositions of SCRUM-45 and its agreed rules, not additional backlog tickets:

1. As a submitting Event Organiser, I want approval confirmation so that I know my request's outcome.
2. As a submitting Event Organiser, I want rejection confirmation with the rejection reason so that I understand the decision.
3. As a submitting Event Organiser, I want the event name and decision in the notification so that I can identify the affected request.
4. As a submitting Event Organiser, I want a link to the request's decision details so that I can inspect the outcome.
5. As a submitting Event Organiser, I want to know the initially assigned coordinator's name so that I know who is responsible.
6. As a submitting Event Organiser, I want to know the replacement coordinator's name after reassignment so that I know who is now responsible.
7. As a submitting Event Organiser, I want approval and assignment represented separately so that neither update is lost when they occur together.
8. As a submitting Event Organiser, I want notifications retained while I am absent so that I can read them later in the existing inbox.
9. As a submitting Event Organiser, I want retries to avoid duplicate inbox entries so that one change does not appear to be multiple changes.
10. As a submitting Event Organiser, I want earlier assignment notifications to retain the correct person's identity so that rapid reassignments do not rewrite history.
11. As an organiser, I want my inbox scoped to my identity so that it does not expose another organiser's notifications, within the existing demo authentication limitations.
12. As a coordinator recording an action, I want temporary delivery outages not to undo a successful decision or assignment so that notification delivery does not block the business operation.

## Acceptance Criteria

- **AC1:** A successfully recorded approval sends an in-app approval notification to the submitting Event Organiser.
- **AC2:** A successfully recorded rejection sends an in-app rejection notification to the submitting Event Organiser, including the rejection reason.
- **AC3:** Both decision notifications include event name, decision, and a link to the event request and its decision details.
- **AC4:** A successfully recorded initial assignment or reassignment sends the submitting Event Organiser an in-app notification with event name, newly assigned coordinator name, and an event-details link.

Additional agreed rules are labelled **DR**, not invented ACs: DR1 separate approval/assignment messages; DR2 transactional intent and no notification for failed/no-op changes; DR3 retry and deduplication; DR4 historical change identity and frozen content; DR5 legacy missing-recipient diagnostics; DR6 missing-name retry/hold without blocking unrelated deliveries; DR7 future changes only; DR8 demo identity and recipient isolation; DR9 existing inbox behaviour.

## Implementation Decisions

- Event Service remains the owner of decision and assignment mutations and saves notification intent in the same database transaction. Cover dedicated approval/rejection routes and the supported progress-update route, plus initial assignment and reassignment.
- Persist a stable per-change identity, submitting organiser identity, event identity/name, decision and reason where relevant, and the newly assigned coordinator ID where relevant. Do not reconstruct historical facts from the current event record.
- Introduce an Event-owned transactional outbox and authenticated internal APIs for claiming, freezing, and completing notification work. Reuse the established lease-fencing and retry conventions rather than inventing a second delivery protocol. Final endpoint names and envelope fields are implementation details to establish during the first relevant TDD slice.
- Run one dispatcher as a separate worker from the existing Event Workflow service image. It pulls work over Event Service HTTP APIs, resolves names through User Service by the saved coordinator ID, freezes the prepared envelope, and publishes to the existing durable RabbitMQ notification pipeline.
- Atomics never call other services or RabbitMQ. This explicitly extends Event Workflow's remit and follows the repository boundary rule rather than the conflicting outward arrow in an older diagram.
- Preserve existing stable-source deduplication and commit-before-ack consumption. Extend the validated destination contract and frontend allowlist to support event details without requiring a venue booking ID. Keep existing venue destinations working.
- Resolve coordinator names at first successful preparation, not necessarily at mutation time. Once prepared, content is immutable across retries. A rapid Alice-to-Bob change must not turn Alice's notification into Bob's.
- Retry temporary name-lookup failures. Missing users or unusable names remain diagnosed delivery failures pending repair/retry; no ID-only or current-coordinator substitution. Unrelated notifications continue.
- Legacy records without an organiser remain actionable but produce no organiser notification and record a diagnostic. Do not guess or broadcast. These records cannot satisfy delivery until ownership is repaired.
- Extend the existing organiser details page to display decision and rejection reason. Keep approval/rejection distinct from safety confirmation/cancellation.
- Reuse the existing inbox, read/unread behaviour and asynchronous refresh; no end-to-end latency guarantee is introduced.
- Apply only to newly recorded changes after feature enablement. No historical backfill.
- Preserve the current demo-only identity mechanism. Recipient-isolation tests are not proof of production authentication.

## Testing Decisions

### Approved boundaries

1. Event mutation and pending-notification APIs: trigger correctness, historical information and transactional/no-op behaviour. This does not prove broker delivery or rendering.
2. Worker and consumer boundaries: recipient/content, lookup handling, retry and deduplication. Mocked dependencies do not prove real service integration.
3. Real backend flow from mutation through database, worker, RabbitMQ and inbox API: actual persisted delivery and retrievability. This does not prove browser rendering or click navigation.

Prefer these external boundaries over private helpers. No new seam is silently added. Real database integration may verify transaction outcomes through the owning service APIs rather than coupling tests to private table layout.

### Test quality and documentation

- Every feature Python test file starts with a module docstring containing SCRUM-45's user story and the AC/DR mapping relevant to the file.
- Each test has a meaningful behaviour-based name and a brief docstring naming the AC or agreed design rule and explaining how it is exercised and observed.
- Test real application logic; mock external boundaries in unit tests, not the behaviour being tested. Expected values come from independent fixture facts and requirements.
- One test covers one coherent behaviour. Parameterize genuinely equivalent cases, such as both decision entry routes, rather than duplicating entire setups.
- No tautologies, tests solely asserting configured mock responses, private-method assertions, meaningless coverage padding, or hardcoded test-only production shortcuts.
- Retain existing regression tests; tests already green may be legitimate regression coverage but do not count as demonstrated RED for new behaviour.

### TDD execution protocol

Write and execute one meaningful test before its production change. Confirm RED is an assertion failure attributable to missing behaviour, not missing infrastructure, imports, credentials or broken fixtures. Save real command/output evidence. Implement the smallest general solution, rerun the focused test and relevant suite, then refactor with tests green. Repeat vertically; the planned matrix is not permission to write all executable tests ahead of implementation.

Use the repository's pytest configuration and service-level uv commands. Unit tests are hermetic and default CI coverage applies. Real integration tests are explicitly marked, opt-in, and run against isolated test resources with deterministic cleanup and bounded condition-based waits. Do not touch production records. Missing infrastructure is a blocked run, never a pass or valid RED. Report skipped, failed and executed tests separately.

### Prior art

Reuse existing venue-notification consumer, dispatcher, transaction/outbox and integration patterns; existing event-decision/progress tests; notification recipient-scoping tests; and assignment validation tests. Reuse existing test factories without importing one test module from another.

### Ordered meaningful test plan

These are planned behaviours, not claims of generated or executed tests. Start with a consumer contract tracer test if it is runnable with the current environment, then build the approved feature vertically.

| Suggested pytest name | Traceability | Method and independently observable result | Level |
|---|---|---|---|
| test_rejection_notification_with_event_details_destination_is_stored | AC2, AC3 | Submit a valid SCRUM-45 rejection envelope through the real consumer boundary; verify accepted inbox persistence with the fixture reason and event destination, not quarantine. | Unit |
| test_approval_records_notification_for_submitting_organiser | AC1, AC3 | Approve through each supported route and observe pending work for the submitting organiser with event name and approval decision. | Unit; real integration validates persistence |
| test_rejection_records_notification_with_reason | AC2, AC3 | Reject through each supported route and observe the submitted reason and event details in pending work. | Unit |
| test_initial_assignment_records_named_coordinator_notification | AC4 | Record initial assignment; prepare its notification by resolving the saved user ID and observe the expected name and event destination. | Unit |
| test_reassignment_records_new_coordinator_notification | AC4 | Reassign to a distinct coordinator and verify the resulting notification identifies that new person. | Unit |
| test_approval_and_assignment_create_distinct_notifications | DR1, AC1, AC4 | Record both changes and observe two distinct notification identities/types rather than one overwritten message. | Integration |
| test_failed_event_change_leaves_no_notification_work | DR2 | Force failure after mutation processing begins and verify both event state and pending-work APIs reflect rollback. | Real database integration |
| test_unchanged_assignment_creates_no_notification | DR2 | Assign the already assigned coordinator and observe no additional work. | Unit |
| test_broker_outage_keeps_recorded_decision_deliverable | DR3, AC1 | Interrupt publication, verify decision remains saved, restore broker and observe eventual inbox delivery. | Integration |
| test_redelivered_change_appears_once_in_organiser_inbox | DR3 | Redeliver the same source message through the real broker/consumer and retrieve exactly one inbox entry for that source. | Integration |
| test_rapid_reassignment_preserves_each_assigned_person | DR4, AC4 | Record Alice then Bob before processing, resolve each saved identity, and verify the two messages name Alice and Bob respectively. | Unit |
| test_publish_retry_preserves_prepared_notification_content | DR4 | Prepare and freeze content, simulate failed publication and changed lookup data, then verify retry publishes the original prepared content. | Unit |
| test_legacy_event_without_organiser_is_diagnosed_without_delivery | DR5 | Record a supported ownerless legacy change; verify action succeeds and a diagnostic occurs without publishable organiser work. | Unit |
| test_temporary_coordinator_lookup_failure_remains_retryable | DR6 | Make lookup temporarily unavailable, then recover it and verify the same pending change can deliver the required name. | Unit |
| test_missing_coordinator_name_does_not_block_other_notifications | DR6 | Process one missing-user/blank-name item and one valid item; verify diagnosed hold for the former and successful processing of the latter. | Unit; parameterized missing/blank |
| test_organiser_cannot_read_another_organisers_notification | DR8 | Query the inbox with a different demo identity and verify the new notification is absent. Reuse existing scoping coverage where sufficient. | Integration |
| test_decision_notification_is_retrievable_with_required_details | AC1–AC3 | Parameterize approved/rejected; execute the real backend path, retrieve recipient inbox and linked organiser details, and compare independent fixture values. | Backend integration |
| test_assignment_notification_is_retrievable_with_required_details | AC4 | Parameterize initial/reassignment; execute the real backend path and verify event name, correct user name and event destination in the recipient inbox. | Backend integration |

Do not add a dedicated rollout/backfill test unless the implementation introduces rollout/backfill logic; code that only reacts to new mutations does not need a contrived test of a nonexistent backfill function. Likewise, reuse existing inbox regression coverage instead of rewriting it for this story.

### Separate browser verification

Browser verification remains separate and explicitly reported: bell/inbox rendering, notification click to the correct organiser detail screen, displayed rejection reason, and existing venue-link regression. Backend pytest does not establish these outcomes. No new browser toolchain is required by this specification.

## Out of Scope

Lead/coordinator recipient notifications, submission alerts, email/SMS/push, instant live updates, historical backfill, changed approval permissions, production authentication, a new notification UI, unrelated service redesign, production data mutation, automatic Git commits or pushes, and bulk test generation before TDD cycles.

## Further Notes

The approved design and ADR are the architectural basis. At specification creation the checkout was another story's notification branch with pre-existing local edits; verifying the intended base and isolating SCRUM-45 was a prerequisite, not a current blocker. Implementation and final verification now use the dedicated `SCRUM-45-event-organiser-status-and-update-notifications` integration branch. Preserve original worktrees and do not silently stash or overwrite local work.

Publish to the project's configured tracker with the ready-for-agent label only when the tracker configuration and label mapping are verified. If configuration is absent, run /setup-matt-pocock-skills; local specification creation is not tracker publication.
