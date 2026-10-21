# 04: Deliver reassignment notifications without rewriting history

**What to build:** Deliver reassignment notifications without rewriting history for the submitting Event Organiser, per the SCRUM-45 implementation specification.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] AC4 reassignment names new coordinator.
- [ ] Alice-to-Bob rapid changes preserve each identity; retries preserve frozen content.
- [ ] Unchanged assignment creates no new work; real reassignment integration.

## Mandatory TDD

Use approved public boundaries. Observe a meaningful RED, implement minimally to GREEN, then refactor with passing tests. Each Python feature test module begins with the user story; each test documents AC/design-rule and method. Unit tests mock external I/O only. Real integration results and browser checks must be reported separately; blocked infrastructure is not a pass. No production changes before an applicable observed failing test.
