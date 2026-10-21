# 02: Deliver approval notifications

**What to build:** Deliver approval notifications for the submitting Event Organiser, per the SCRUM-45 implementation specification.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] AC1/AC3 through both supported decision paths.
- [ ] Correct submitting recipient, event name, approval and details destination.
- [ ] Failed actions do not notify; real approval-to-inbox integration.

## Mandatory TDD

Use approved public boundaries. Observe a meaningful RED, implement minimally to GREEN, then refactor with passing tests. Each Python feature test module begins with the user story; each test documents AC/design-rule and method. Unit tests mock external I/O only. Real integration results and browser checks must be reported separately; blocked infrastructure is not a pass. No production changes before an applicable observed failing test.
