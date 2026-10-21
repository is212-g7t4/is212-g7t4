# 05: Verify combined updates and delivery recovery

**What to build:** Verify combined updates and delivery recovery for the submitting Event Organiser, per the SCRUM-45 implementation specification.

**Blocked by:** 02, 04

**Status:** completed

Verified final integration merge `1e0586b`: all ACs covered; 20 real integration tests passed on identical tree; final affected unit suites passed; independent spec review passed and both standards findings resolved. Full frontend/browser verification recorded in docs/scrum-45-final-verification.md.

- [x] Approval and assignment yield two distinct notifications.
- [x] Real broker outage/recovery and duplicate redelivery tests.
- [x] Recipient isolation, regression suites and separate browser evidence.

## Mandatory TDD

Use approved public boundaries. Observe a meaningful RED, implement minimally to GREEN, then refactor with passing tests. Each Python feature test module begins with the user story; each test documents AC/design-rule and method. Unit tests mock external I/O only. Real integration results and browser checks must be reported separately; blocked infrastructure is not a pass. No production changes before an applicable observed failing test.
