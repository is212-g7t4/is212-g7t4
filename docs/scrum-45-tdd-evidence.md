# SCRUM-45 — TDD execution evidence

## First slice: RED verified

Test: `services/notification-service/tests/unit/test_event_notifications.py::test_rejection_notification_with_event_details_destination_is_stored`

**AC2/AC3:** A rejection notification must retain its rejection reason and event-details destination. The test submits an envelope through the real consumer and inspects its inbox-storage payload at the mocked PostgreSQL driver boundary. Broker I/O is also mocked. It does not prove real database persistence, recipient selection, complete delivery, or browser navigation.

The first-slice proposed wire values are `event.rejection` and destination kind `event-details`. They extend the existing envelope conventions; they are not previously supported wire values. Producer, consumer and frontend must agree on the finalized contract during implementation.

Command from Notification Service directory:

```sh
uv run pytest
```

Observed output:

```text
WARNING app.consumer: notification quarantined: Unknown destination
AssertionError: Rejection must reach inbox storage, not quarantine
assert 0 == 1
1 failed, 81 passed in 0.31s
Required test coverage of 100.0% reached. Total coverage: 100.00%
```

The new test fails because the consumer only supports venue-request destinations. Existing tests pass. This is an expected missing-behaviour failure, not an import, fixture, database-connectivity or coverage failure.

The initial focused command (`uv run pytest tests/unit/test_event_notifications.py -q`) showed the same assertion failure but also missed the whole-service coverage threshold because only one test ran. The full-suite command above removes that unrelated coverage ambiguity without weakening repository settings.

## Next cycles — not executed

GREEN: minimally support the agreed event-only notification destination in the consumer while retaining validation and existing venue destinations. Then rerun the focused behaviour and full service suite.

REFACTOR: only after GREEN, improve names or remove duplication without changing externally observable behaviour, rerunning the suite.

Continue the implementation spec's behaviour plan one test/change at a time. Do not mistake this first consumer test for full AC2/AC3 coverage. Integration tests require isolated real database/broker infrastructure; none were generated or executed in this step. Browser verification remains separate.

## Delivery state

No production implementation, commit, branch switch, or tracker publication was performed. The specification is local. Jira is named in repository instructions, but tracker connection configuration and ready-for-agent label mapping were not found. Run `/setup-matt-pocock-skills` to establish the required tracker setup before publishing.
