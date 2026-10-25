# Event owns notification intent; Event Workflow owns delivery orchestration

For SCRUM-45, Event Service will persist notification work transactionally with every supported approval, rejection, initial assignment, and reassignment mutation. A separate worker hosted by Event Workflow Service will retrieve that work through internal HTTP APIs, prepare and freeze the notification, and publish through the existing RabbitMQ pipeline. This preserves atomic service boundaries and covers direct mutation routes without making successful business actions depend on immediate broker availability.

## Considered options

Publishing only from coordinator-assignment routes would miss decision and direct mutation paths. Hosting all delivery in Coordinator Assignment would put decisions outside its assignment-focused remit; splitting delivery between two composites adds workers and type-scoped claiming. A new composite adds a service unnecessarily. We explicitly extend Event Workflow's remit instead, while leaving business mutations in their existing owners.

## Consequences

Event Service owns pending-work persistence and internal claim/freeze/completion APIs; Event Workflow owns cross-service lookup and broker publication. Event Service never calls outward to Event Workflow, despite a conflicting arrow in existing architecture notes; the `AGENTS.md` boundary takes precedence.

Per-change recipient, event name, decision/reason, and assigned coordinator ID are retained rather than reconstructed from current event state. The coordinator name is resolved by that saved ID and frozen at first successful preparation, so later reassignments cannot alter the message identity; name spelling may reflect a rename before preparation. Transient lookup failures retry; missing users or unusable names hold the affected notification for diagnosis and repair without blocking other notifications. Existing retry and inbox-deduplication patterns are retained.

This decision was agreed during the design interview. It is not evidence of implementation or authorisation to begin implementation.
