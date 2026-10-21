# 01: Deliver rejection notifications and linked decision details

**What to build:** Deliver rejection notifications and linked decision details for the submitting Event Organiser, per the SCRUM-45 implementation specification.

**Blocked by:** None

**Status:** ready-for-agent

- [ ] AC2/AC3 through both decision paths; event name, rejection reason and event-details link reach submitting organiser.
- [ ] Transactional intent and Event Workflow worker deliver via existing RabbitMQ pipeline.
- [ ] Failed-action rollback and ownerless legacy diagnostics are covered.
- [ ] Real rejection-to-inbox integration and separate browser verification.

## Mandatory TDD

Use approved public boundaries. Observe a meaningful RED, implement minimally to GREEN, then refactor with passing tests. Each Python feature test module begins with the user story; each test documents AC/design-rule and method. Unit tests mock external I/O only. Real integration results and browser checks must be reported separately; blocked infrastructure is not a pass. No production changes before an applicable observed failing test.
