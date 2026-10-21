# 03: Deliver initial coordinator-assignment notifications

**What to build:** Deliver initial coordinator-assignment notifications for the submitting Event Organiser, per the SCRUM-45 implementation specification.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] AC4 initial assignment names saved coordinator identity.
- [ ] Temporary name lookup retries; missing/blank name diagnosed without blocking unrelated work.
- [ ] Real initial-assignment delivery integration.

## Mandatory TDD

Use approved public boundaries. Observe a meaningful RED, implement minimally to GREEN, then refactor with passing tests. Each Python feature test module begins with the user story; each test documents AC/design-rule and method. Unit tests mock external I/O only. Real integration results and browser checks must be reported separately; blocked infrastructure is not a pass. No production changes before an applicable observed failing test.
