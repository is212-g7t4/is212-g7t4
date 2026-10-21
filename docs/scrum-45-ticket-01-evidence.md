# SCRUM-45 ticket 01 — rejection notification evidence

## Scope and provenance

- Worktree: `codes/scrum-45-ticket-01`; branch: `SCRUM-45-rejection-notifications`.
- Base and integration tip checked: `9884460e3d1e3f41ed9cb75c6e5366c02f014b1a`.
- `git merge --no-edit SCRUM-45-event-organiser-status-and-update-notifications` returned `Already up to date.` before reporting. No push or ticket completion performed.
- Read AGENTS.md, implementation spec, glossary, ADR 0001 and local ticket 01; loaded both TDD skills. Initial rejection consumer test copied from the integration worktree and run RED before consumer changes.
- Only rejection behavior is implemented. Neither approval nor assignment notifications are added.

## Implemented seams and acceptance coverage

| Requirement | Executed seam and observation |
| --- | --- |
| AC2/AC3, both decision paths | Event HTTP `/events/:id/reject` and `/events/:id/progress`, rejection reason and submitting organiser captured transactionally. Unit plus real service integration. |
| Durable intent, no outward atomic calls | Event-owned `EventNotificationOutbox` migration and same-transaction insert. Real PostgreSQL trigger-injected outbox failure rolls back decision/status through both routes. |
| Worker ownership and reliability | Separate Event Workflow process uses authenticated Event HTTP claim/freeze/published/retry; leases fence stale workers, one immutable ID/content per intent. Persistent RabbitMQ messages with blocking publisher confirms. 50-second subprocess bound includes claim in 60-second lease. |
| Consumer isolation and dedup | Existing Notification pipeline; real broker stop/start, worker retry, frozen message replay, one inbox row with readAt preserved, different user's inbox empty. |
| Event-only destination | Consumer accepts `event-details` without bookingId; frontend UUID-validated `/events/:eventId` route. |
| Organiser decision details | Organiser event detail page renders rejection outcome/reason, React text rendering. Separate component and mocked browser navigation tests. |
| Ownerless legacy events | Both HTTP mutation paths log missing organiser, succeed without inventing recipient/delivery. Unit boundary coverage. |

Real integration uses ephemeral local `postgres:17` and `rabbitmq:4-management`, random loopback ports and separate events/notifications databases. It starts actual Event/Notification Flask processes, Event Workflow one-shot worker, and Notification broker consumer. Environment is explicitly constructed with dotenv loading disabled. Only disposable containers/databases and synthetic identities/credentials are mutated. Teardown terminates owned processes and removes owned containers/volumes. This is not remote Supabase testing or a production authentication proof (Notification uses its explicit development-auth mode).

## RED → GREEN cycles

These are chronological observations retained from execution, not reconstructed expected output. Assertion failures are meaningful RED; syntax/import/harness mistakes were corrected separately and are not claimed as feature RED.

| Cycle | RED | GREEN |
| --- | --- | --- |
| Consumer event-only rejection | Initial copied test quarantined rather than inserted; 1 failed | 82 consumer tests passed, 100% coverage |
| Both mutation paths save intent | Missing INSERT; 2 failed | Both new route cases passed |
| Ownerless legacy diagnosis | Missing warning; 2 failed | 465 Event tests passed |
| Owner HTTP pending-work API | Claim endpoint 404; 1 failed | 5 feature tests passed |
| Durable retry | Retry endpoint 404; 1 failed | 6 feature tests passed |
| Worker dispatch | Initial no-op returns 0 rather than 1 | 65 workflow tests passed |
| Broker outage recovery | RuntimeError escaped rather than retrying | 66 workflow tests passed |
| Authenticated HTTP adapter | OutboxAPI missing | 67 workflow tests passed |
| Broker durable publish | publish missing | 4 workflow feature tests passed |
| Bounded attempt | attempt missing | 5 workflow feature tests passed |
| Retry-reporting outage | Retry API error escaped | 6 workflow feature tests passed |
| Worker lifecycle | run missing | 7 workflow feature tests passed |
| Consumer malformed rejection | 4 invalid rejection envelopes not quarantined | 86 consumer tests passed, 100% coverage |
| Frontend event-only link | notificationPath returned wrong result | 42 notification feature tests passed |
| Organiser reason | Decision heading missing | 10 organiser component tests passed |

Integration setup initially failed collection, RabbitMQ readiness and notification delivery; these were actual failures, not green. Corrected the test harness (runner via python -m pytest, explicit rabbitmq exec user, isolated explicit ports/environment); final real tests below pass. No remote infrastructure was substituted.

## REFACTOR and review

After GREEN, reused service-local venue outbox/worker conventions (no shared library), retained one rejection-intent helper for both mutation paths, removed redundant outbox validation guard and organised dispatcher imports without adding behavior. Tests remained green; final post-refactor real integration was rerun.

Independent Claude CLI review completed with `passed: true`, empty security/logic concern arrays. Two initial review false positives were resolved using surrounding source / installed dependency source, not speculative code changes: existing `decide_event` locks the row and rejects statuses outside Submitted/Under Review before mutation; Pika BlockingChannel.basic_publish synchronously waits for publisher confirmation when confirm_delivery is enabled. Local Docker HTTP is the existing approved dev convention, not a claim of production transport security. Codex reviewer was unavailable (native executable ENOENT); some Claude attempts timed out before the successful review.

Static added-line check: no os.system/shell=True, eval/pickle, or dynamic execute(f...) matches. New Python story test modules have module user stories and per-test AC/design-rule/method docstrings. `git diff --check` passes. No real credentials copied into tracked files.

## Final verification

- All backend services: root `npm run test:backend`, exit 0 (per-service results retained below).
- Event: `uv run pytest`, **490 passed**, **98.79%** overall; new outbox **100%**. Raised coverage ratchet to 98.79%; remaining missing lines/branches are pre-existing unrelated Event behavior listed in coverage output, not hidden/omitted.
- Event Workflow: `uv run pytest`, **75 passed, 4 deselected**, **100%** line/branch coverage.
- Notification: `uv run pytest`, **86 passed**, **100%** line/branch coverage.
- Real local integration: **4 passed, 75 deselected**; both rejection routes plus both transactional failure routes.
- Frontend build, lint and full Vitest suite: exit 0, **59 test files / 720 tests passed**. Lint reports three existing fast-refresh warnings in untouched `ClosureDetails.tsx`.
- Separate Chromium Playwright notification scenarios: **5 passed**. All backend responses are mocked; browser success is not used as real persistence/delivery evidence.
- Compose dispatcher configuration parsed successfully with no env-file resolution / no interpolation. This validates wiring, not production deployment.

### Deployment prerequisites / boundaries

Apply `database/supabase/migrations/20261021000000_event_notification_outbox.sql` to the Event-owned database before deploying rejection writes. Configure the same internal token on Event Service and dispatcher, enable the separate dispatcher process and existing Notification consumer. No remote migration or production DB write was performed. Ticket completion and integration merge remain parent-owned; local commit was separately authorised with the `SCRUM-45:` prefix.

## Actual execution excerpts

Excerpts below are literal captured output, shortened to the assertion/summary sections where noted. Full raw local history stays outside git at `~/.hermes/cache/scratch/scrum45-ticket01-test-history.json`.

### Cycle observation 1

Directory: `services/notification-service`. Command: `uv run pytest tests/unit/test_event_notifications.py`. Exit: `1`.

```text
       )

        inbox_inserts = [
            call.args[1]
            for call in cursor.execute.call_args_list
            if call.args[0].startswith('INSERT INTO public."Notification" ')
        ]
>       assert len(inbox_inserts) == 1, (
            "Rejection must reach inbox storage, not quarantine"
        )
E       AssertionError: Rejection must reach inbox storage, not quarantine
E       assert 0 == 1
E        +  where 0 = len([])

tests/unit/test_event_notifications.py:58: AssertionError
------------------------------ Captured log call -------------------------------
WARNING  app.consumer:consumer.py:98 notification quarantined: Unknown destination
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                 Stmts   Miss Branch BrPart   Cover   Missing
-----------------------------------------------------------------
app/__init__.py         51     45     16      0   8.96%   11-93
app/consumer.py        108     63     46      9  40.26%   20, 32, 38-39, 41, 51, 55, 57, 59, 66-83, 100-101, 106-112, 116, 120-150, 154
app/diagnostics.py      32     32      6      0   0.00%   7-56
app/store.py            61     35      8      0  37.68%   26, 37-46, 50-70, 74-79, 83-89, 93-94
-----------------------------------------------------------------
TOTAL                  252    175     76      9  28.66%
FAIL Required test coverage of 100.0% not reached. Total coverage: 28.66%
=========================== short test summary info ============================
FAILED tests/unit/test_event_notifications.py::test_rejection_notification_with_event_details_destination_is_stored
============================== 1 failed in 1.50s ===============================
```

### Cycle observation 2

Directory: `services/notification-service`. Command: `uv run pytest`. Exit: `0`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.7.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/notification-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 82 items

tests/unit/test_event_notifications.py .                                 [  1%]
tests/unit/test_notification_scrum173.py ............................... [ 39%]
..................................................                       [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                 Stmts   Miss Branch BrPart    Cover   Missing
------------------------------------------------------------------
app/__init__.py         51      0     16      0  100.00%
app/consumer.py        108      0     46      0  100.00%
app/diagnostics.py      32      0      6      0  100.00%
app/store.py            61      0      8      0  100.00%
------------------------------------------------------------------
TOTAL                  252      0     76      0  100.00%
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================== 82 passed in 0.32s ==============================
```

### Cycle observation 3

Directory: `services/event-service`. Command: `uv run pytest tests/unit/test_rejection_notifications.py --no-cov`. Exit: `1`.

```text
st save durable notification intent"
E       AssertionError: Successful rejection must save durable notification intent
E       assert 0 == 1
E        +  where 0 = len([])

tests/unit/test_rejection_notifications.py:57: AssertionError
__________ test_rejection_records_notification_with_reason[progress] ___________

boundary = (<FlaskClient <Flask 'app'>>, <MagicMock id='4382176992'>, <MagicMock name='mock.cursor().__enter__()' id='4382179056'>)
route = 'progress'

    @pytest.mark.parametrize("route", ["reject", "progress"])
    def test_rejection_records_notification_with_reason(boundary, route):
        """AC2/AC3/DR2: execute each mutation HTTP route with DB I/O mocked;
        observe same-transaction insertion with independent organiser/event facts.
        """
        client, connection, cursor = boundary
        cursor.fetchone.side_effect = [row(), row("Rejected")]
        response = reject(client, route)
        assert response.status_code == 200
        inserts = [call.args[1] for call in cursor.execute.call_args_list
                   if 'INSERT INTO public."EventNotificationOutbox"' in call.args[0]]
>       assert len(inserts) == 1, "Successful rejection must save durable notification intent"
E       AssertionError: Successful rejection must save durable notification intent
E       assert 0 == 1
E        +  where 0 = len([])

tests/unit/test_rejection_notifications.py:57: AssertionError
=========================== short test summary info ============================
FAILED tests/unit/test_rejection_notifications.py::test_rejection_records_notification_with_reason[reject]
FAILED tests/unit/test_rejection_notifications.py::test_rejection_records_notification_with_reason[progress]
============================== 2 failed in 1.56s ===============================
```

### Cycle observation 6

Directory: `services/event-service`. Command: `uv run pytest tests/unit/test_rejection_notifications.py --no-cov`. Exit: `0`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/event-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1
collected 2 items

tests/unit/test_rejection_notifications.py ..                            [100%]

============================== 2 passed in 0.06s ===============================
```

### Cycle observation 8

Directory: `services/event-service`. Command: `uv run pytest tests/unit/test_rejection_notifications.py --no-cov`. Exit: `1`.

```text
   assert reject(client, route).status_code == 200
>       assert "missing organiser" in caplog.text
E       AssertionError: assert 'missing organiser' in ''
E        +  where '' = <_pytest.logging.LogCaptureFixture object at 0x103c8f5c0>.text

tests/unit/test_rejection_notifications.py:72: AssertionError
_ test_legacy_event_without_organiser_is_diagnosed_without_delivery[progress] __

boundary = (<FlaskClient <Flask 'app'>>, <MagicMock id='4358705840'>, <MagicMock name='mock.cursor().__enter__()' id='4358709344'>)
route = 'progress'
caplog = <_pytest.logging.LogCaptureFixture object at 0x103cfe030>

    @pytest.mark.parametrize("route", ["reject", "progress"])
    def test_legacy_event_without_organiser_is_diagnosed_without_delivery(boundary, route, caplog):
        """DR5: reject ownerless legacy records through HTTP; observe success,
        diagnostic and absence of publishable outbox intent without guessing owner.
        """
        client, _, cursor = boundary
        cursor.fetchone.side_effect = [row(organiser=None), row("Rejected", organiser=None)]
        assert reject(client, route).status_code == 200
>       assert "missing organiser" in caplog.text
E       AssertionError: assert 'missing organiser' in ''
E        +  where '' = <_pytest.logging.LogCaptureFixture object at 0x103cfe030>.text

tests/unit/test_rejection_notifications.py:72: AssertionError
=========================== short test summary info ============================
FAILED tests/unit/test_rejection_notifications.py::test_legacy_event_without_organiser_is_diagnosed_without_delivery[reject]
FAILED tests/unit/test_rejection_notifications.py::test_legacy_event_without_organiser_is_diagnosed_without_delivery[progress]
========================= 2 failed, 2 passed in 0.09s ==========================
```

### Cycle observation 9

Directory: `services/event-service`. Command: `uv run pytest`. Exit: `0`.

```text
........                [ 44%]
tests/unit/test_event_progress.py .............................          [ 50%]
tests/unit/test_notification_context.py ..                               [ 50%]
tests/unit/test_rejection_notifications.py ....                          [ 51%]
tests/unit/test_safety_approve_status.py ......................          [ 56%]
tests/unit/test_safety_gate.py ................................          [ 63%]
tests/unit/test_safety_reject_changes_status.py ........................ [ 68%]
............                                                             [ 70%]
tests/unit/test_safety_status_access.py .........                        [ 72%]
tests/unit/test_safety_submit_status.py ................................ [ 79%]
..                                                                       [ 80%]
tests/unit/test_submission.py .......................................... [ 89%]
..................................................                       [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                Stmts   Miss Branch BrPart   Cover   Missing
----------------------------------------------------------------
app/__init__.py       474     10    150      5  97.60%   126->129, 383-384, 392, 638->673, 724, 820-821, 827, 835, 844-845
app/models.py         471      1    150      2  99.52%   774->777, 1386
app/validation.py      23      0     12      0 100.00%
----------------------------------------------------------------
TOTAL                 968     11    312      7  98.59%
Required test coverage of 98.57% reached. Total coverage: 98.59%
============================= 465 passed in 2.67s ==============================
```

### Cycle observation 10

Directory: `services/event-service`. Command: `uv run pytest tests/unit/test_rejection_notifications.py --no-cov`. Exit: `1`.

```text
ement/proj/codes/scrum-45-ticket-01/services/event-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1
collected 5 items

tests/unit/test_rejection_notifications.py ....F                         [100%]

=================================== FAILURES ===================================
__________ test_pending_rejection_can_be_claimed_frozen_and_completed __________

boundary = (<FlaskClient <Flask 'app'>>, <MagicMock id='4385412624'>, <MagicMock name='mock.cursor().__enter__()' id='4385224608'>)

    def test_pending_rejection_can_be_claimed_frozen_and_completed(boundary):
        """DR3/DR4: exercise authenticated owning-service claim/freeze/published
        HTTP lifecycle against DB-driver fixtures, observing the frozen readback.
        """
        client, _, cursor = boundary
        pending = dict(source_id=JOB_ID, source=SOURCE, type="event.rejection",
                       envelope=None, attempts=1, lease_token=LEASE, lease_valid=True,
                       created_at=datetime(2026, 10, 21, tzinfo=UTC))
        cursor.fetchall.return_value = [pending]
        claim = client.post("/internal/notification-outbox/claim", json={}, headers=HEADERS)
>       assert claim.status_code == 200, "Event must expose durable pending work to its worker"
E       AssertionError: Event must expose durable pending work to its worker
E       assert 404 == 200
E        +  where 404 = <WrapperTestResponse streamed [404 NOT FOUND]>.status_code

tests/unit/test_rejection_notifications.py:93: AssertionError
=========================== short test summary info ============================
FAILED tests/unit/test_rejection_notifications.py::test_pending_rejection_can_be_claimed_frozen_and_completed
========================= 1 failed, 4 passed in 0.09s ==========================
```

### Cycle observation 11

Directory: `services/event-service`. Command: `uv run pytest tests/unit/test_rejection_notifications.py --no-cov`. Exit: `0`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/event-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1
collected 5 items

tests/unit/test_rejection_notifications.py .....                         [100%]

============================== 5 passed in 0.08s ===============================
```

### Cycle observation 12

Directory: `services/event-service`. Command: `uv run pytest tests/unit/test_rejection_notifications.py --no-cov`. Exit: `1`.

```text
=========================== test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/event-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1
collected 6 items

tests/unit/test_rejection_notifications.py .....F                        [100%]

=================================== FAILURES ===================================
_ test_publish_outage_releases_claim_for_retry_without_erasing_frozen_content __

boundary = (<FlaskClient <Flask 'app'>>, <MagicMock id='4407403696'>, <MagicMock name='mock.cursor().__enter__()' id='4408121136'>)

    def test_publish_outage_releases_claim_for_retry_without_erasing_frozen_content(boundary):
        """DR3: retry HTTP operation records backoff and releases lease; observe
        SQL boundary retains envelope and never marks undelivered work published.
        """
        client, _, cursor = boundary
        cursor.fetchone.return_value = dict(lease_valid=True, attempts=1)
        response = client.post(f"/internal/notification-outbox/{JOB_ID}/retry",
                               json={"leaseToken": LEASE, "error": "BrokerUnavailable"}, headers=HEADERS)
>       assert response.status_code == 200
E       assert 404 == 200
E        +  where 404 = <WrapperTestResponse streamed [404 NOT FOUND]>.status_code

tests/unit/test_rejection_notifications.py:119: AssertionError
=========================== short test summary info ============================
FAILED tests/unit/test_rejection_notifications.py::test_publish_outage_releases_claim_for_retry_without_erasing_frozen_content
========================= 1 failed, 5 passed in 0.12s ==========================
```

### Cycle observation 13

Directory: `services/event-service`. Command: `uv run pytest tests/unit/test_rejection_notifications.py --no-cov`. Exit: `0`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/event-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1
collected 6 items

tests/unit/test_rejection_notifications.py ......                        [100%]

============================== 6 passed in 0.09s ===============================
```

### Cycle observation 15

Directory: `services/event-workflow-service`. Command: `uv run pytest tests/unit/test_rejection_notifications.py --no-cov`. Exit: `1`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/event-workflow-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 1 item

tests/unit/test_rejection_notifications.py F                             [100%]

=================================== FAILURES ===================================
_________ test_worker_delivers_rejection_to_saved_submitting_organiser _________

    def test_worker_delivers_rejection_to_saved_submitting_organiser():
        """AC2/AC3/DR4: worker public boundary prepares saved facts, freezes via
        Event API before broker I/O, then marks published only after acceptance.
        """
        from app.dispatcher import dispatch_once
        api, publish = Mock(), Mock()
        api.claim.return_value = [JOB]
        api.freeze.side_effect = lambda job, envelope: envelope
>       assert dispatch_once(api, publish) == 1
E       AssertionError: assert 0 == 1
E        +  where 0 = <function dispatch_once at 0x1025682c0>(<Mock id='4333891136'>, <Mock id='4338837616'>)

tests/unit/test_rejection_notifications.py:25: AssertionError
=========================== short test summary info ============================
FAILED tests/unit/test_rejection_notifications.py::test_worker_delivers_rejection_to_saved_submitting_organiser
============================== 1 failed in 0.06s ===============================
```

### Cycle observation 16

Directory: `services/event-workflow-service`. Command: `uv run pytest`. Exit: `0`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/event-workflow-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 65 items

tests/unit/test_checks.py ........................                       [ 36%]
tests/unit/test_clients.py ..............                                [ 58%]
tests/unit/test_rejection_notifications.py .                             [ 60%]
tests/unit/test_startup_warning.py ..                                    [ 63%]
tests/unit/test_update_details.py ........................               [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                Stmts   Miss Branch BrPart  Cover   Missing
---------------------------------------------------------------
app/__init__.py        28      0      8      0   100%
app/checks.py          92      0     30      0   100%
app/clients.py         70      0      8      0   100%
app/dispatcher.py       9      0      2      0   100%
app/routes.py          50      0     12      0   100%
---------------------------------------------------------------
TOTAL                 249      0     60      0   100%
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================== 65 passed in 0.26s ==============================
```

### Cycle observation 17

Directory: `services/event-workflow-service`. Command: `uv run pytest tests/unit/test_rejection_notifications.py --no-cov`. Exit: `1`.

```text

>       assert dispatch_once(api, publish) == 1
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/unit/test_rejection_notifications.py:44:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
app/dispatcher.py:15: in dispatch_once
    publish(envelope)
/Users/daphnetok/.local/share/uv/python/cpython-3.12.14-macos-aarch64-none/lib/python3.12/unittest/mock.py:1139: in __call__
    return self._mock_call(*args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/Users/daphnetok/.local/share/uv/python/cpython-3.12.14-macos-aarch64-none/lib/python3.12/unittest/mock.py:1143: in _mock_call
    return self._execute_mock_call(*args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

self = <Mock id='4350552800'>
args = ({'version': 1, 'id': '20000000-0000-0000-0000-000000000001', 'type': 'event.rejection', 'recipientId': '10000000-0000-0000-0000-000000000001', ...},)
kwargs = {}

    def _execute_mock_call(self, /, *args, **kwargs):
        # separate from _increment_mock_call so that awaited functions are
        # executed separately from their call, also AsyncMock overrides this method

        effect = self.side_effect
        if effect is not None:
            if _is_exception(effect):
>               raise effect
E               RuntimeError: broker down

/Users/daphnetok/.local/share/uv/python/cpython-3.12.14-macos-aarch64-none/lib/python3.12/unittest/mock.py:1198: RuntimeError
=========================== short test summary info ============================
FAILED tests/unit/test_rejection_notifications.py::test_publish_retry_preserves_prepared_notification_content
========================= 1 failed, 1 passed in 0.08s ==========================
```

### Cycle observation 18

Directory: `services/event-workflow-service`. Command: `uv run pytest`. Exit: `0`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/event-workflow-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 66 items

tests/unit/test_checks.py ........................                       [ 36%]
tests/unit/test_clients.py ..............                                [ 57%]
tests/unit/test_rejection_notifications.py ..                            [ 60%]
tests/unit/test_startup_warning.py ..                                    [ 63%]
tests/unit/test_update_details.py ........................               [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                Stmts   Miss Branch BrPart  Cover   Missing
---------------------------------------------------------------
app/__init__.py        28      0      8      0   100%
app/checks.py          92      0     30      0   100%
app/clients.py         70      0      8      0   100%
app/dispatcher.py      17      0      4      0   100%
app/routes.py          50      0     12      0   100%
---------------------------------------------------------------
TOTAL                 257      0     62      0   100%
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================== 66 passed in 0.21s ==============================
```

### Cycle observation 19

Directory: `services/event-workflow-service`. Command: `uv run pytest tests/unit/test_rejection_notifications.py --no-cov`. Exit: `1`.

```text
====================== test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/event-workflow-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 3 items

tests/unit/test_rejection_notifications.py ..F                           [100%]

=================================== FAILURES ===================================
__________ test_worker_uses_authenticated_event_http_outbox_protocol ___________

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x104e8bfb0>

    def test_worker_uses_authenticated_event_http_outbox_protocol(monkeypatch):
        """DR3: mock HTTP transport only; claim/freeze/complete/retry adapters send
        the owning Event API contract with token, lease and bounded timeouts.
        """
        import app.dispatcher as worker
        from unittest.mock import patch
        monkeypatch.setenv("EVENT_SERVICE_URL", "http://event.test/")
        monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "test-token")
        with patch("httpx.request") as request:
            request.return_value.json.side_effect = [{"jobs": [JOB]}, {"envelope": {"frozen": True}}, {}, {}]
>           api = worker.OutboxAPI()
                  ^^^^^^^^^^^^^^^^
E           AttributeError: module 'app.dispatcher' has no attribute 'OutboxAPI'

tests/unit/test_rejection_notifications.py:67: AttributeError
=========================== short test summary info ============================
FAILED tests/unit/test_rejection_notifications.py::test_worker_uses_authenticated_event_http_outbox_protocol
========================= 1 failed, 2 passed in 0.06s ==========================
```

### Cycle observation 20

Directory: `services/event-workflow-service`. Command: `uv run pytest`. Exit: `0`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/event-workflow-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 67 items

tests/unit/test_checks.py ........................                       [ 35%]
tests/unit/test_clients.py ..............                                [ 56%]
tests/unit/test_rejection_notifications.py ...                           [ 61%]
tests/unit/test_startup_warning.py ..                                    [ 64%]
tests/unit/test_update_details.py ........................               [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                Stmts   Miss Branch BrPart  Cover   Missing
---------------------------------------------------------------
app/__init__.py        28      0      8      0   100%
app/checks.py          92      0     30      0   100%
app/clients.py         70      0      8      0   100%
app/dispatcher.py      37      0      4      0   100%
app/routes.py          50      0     12      0   100%
---------------------------------------------------------------
TOTAL                 277      0     62      0   100%
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================== 67 passed in 0.22s ==============================
```

### Cycle observation 22

Directory: `services/event-workflow-service`. Command: `uv run pytest tests/unit/test_rejection_notifications.py --no-cov`. Exit: `1`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/event-workflow-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 4 items

tests/unit/test_rejection_notifications.py ...F                          [100%]

=================================== FAILURES ===================================
_________ test_broker_publish_requires_confirm_and_persistent_message __________

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x10774c9e0>

    def test_broker_publish_requires_confirm_and_persistent_message(monkeypatch):
        """DR3: execute real publication adapter with only broker socket mocked;
        observe durable queue, publisher confirms, mandatory routing and stable ID.
        """
        import app.dispatcher as worker
        from unittest.mock import MagicMock, patch
        import json
        monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:[REDACTED]@localhost/%2F")
        connection = MagicMock()
        with patch("pika.BlockingConnection", return_value=connection):
>           worker.publish({"id": JOB["id"], "type": "event.rejection"})
            ^^^^^^^^^^^^^^
E           AttributeError: module 'app.dispatcher' has no attribute 'publish'

tests/unit/test_rejection_notifications.py:93: AttributeError
=========================== short test summary info ============================
FAILED tests/unit/test_rejection_notifications.py::test_broker_publish_requires_confirm_and_persistent_message
========================= 1 failed, 3 passed in 0.11s ==========================
```

### Cycle observation 23

Directory: `services/event-workflow-service`. Command: `uv run pytest tests/unit/test_rejection_notifications.py --no-cov`. Exit: `0`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/event-workflow-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 4 items

tests/unit/test_rejection_notifications.py ....                          [100%]

============================== 4 passed in 0.06s ===============================
```

### Cycle observation 24

Directory: `services/event-workflow-service`. Command: `uv run pytest tests/unit/test_rejection_notifications.py --no-cov`. Exit: `1`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/event-workflow-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 5 items

tests/unit/test_rejection_notifications.py ....F                         [100%]

=================================== FAILURES ===================================
__________________ test_worker_attempt_bounds_io_inside_lease __________________

    def test_worker_attempt_bounds_io_inside_lease():
        """DR3: execute worker process adapter with only subprocess mocked;
        child claims inside its 50-second budget, less than Event's 60-second lease.
        """
        import app.dispatcher as worker
        import subprocess
        from unittest.mock import patch
        import pytest
        with patch("subprocess.run") as run:
>           assert worker.attempt() == 1
                   ^^^^^^^^^^^^^^
E           AttributeError: module 'app.dispatcher' has no attribute 'attempt'

tests/unit/test_rejection_notifications.py:113: AttributeError
=========================== short test summary info ============================
FAILED tests/unit/test_rejection_notifications.py::test_worker_attempt_bounds_io_inside_lease
========================= 1 failed, 4 passed in 0.07s ==========================
```

### Cycle observation 25

Directory: `services/event-workflow-service`. Command: `uv run pytest tests/unit/test_rejection_notifications.py --no-cov`. Exit: `0`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/event-workflow-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 5 items

tests/unit/test_rejection_notifications.py .....                         [100%]

============================== 5 passed in 0.06s ===============================
```

### Cycle observation 26

Directory: `services/event-workflow-service`. Command: `uv run pytest tests/unit/test_rejection_notifications.py --no-cov`. Exit: `1`.

```text
ython-3.12.14-macos-aarch64-none/lib/python3.12/unittest/mock.py:1139: in __call__
    return self._mock_call(*args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/Users/daphnetok/.local/share/uv/python/cpython-3.12.14-macos-aarch64-none/lib/python3.12/unittest/mock.py:1143: in _mock_call
    return self._execute_mock_call(*args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

self = <Mock name='mock.retry' id='4381258624'>
args = ({'id': '20000000-0000-0000-0000-000000000001', 'source': {'eventId': '30000000-0000-0000-0000-000000000001', 'recipie...kshop', 'decision': 'Rejected', ...}, 'envelope': None, 'createdAt': '2026-10-21T00:00:00+00:00', ...}, 'RuntimeError')
kwargs = {}

    def _execute_mock_call(self, /, *args, **kwargs):
        # separate from _increment_mock_call so that awaited functions are
        # executed separately from their call, also AsyncMock overrides this method

        effect = self.side_effect
        if effect is not None:
            if _is_exception(effect):
>               raise effect
E               RuntimeError: owner unavailable

/Users/daphnetok/.local/share/uv/python/cpython-3.12.14-macos-aarch64-none/lib/python3.12/unittest/mock.py:1198: RuntimeError
------------------------------ Captured log call -------------------------------
WARNING  app.dispatcher:dispatcher.py:65 Dispatch retry source=20000000-0000-0000-0000-000000000001 error=RuntimeError
=========================== short test summary info ============================
FAILED tests/unit/test_rejection_notifications.py::test_retry_state_outage_does_not_block_unrelated_pending_notification
========================= 1 failed, 5 passed in 0.12s ==========================
```

### Cycle observation 27

Directory: `services/event-workflow-service`. Command: `uv run pytest tests/unit/test_rejection_notifications.py --no-cov`. Exit: `0`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/event-workflow-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 6 items

tests/unit/test_rejection_notifications.py ......                        [100%]

============================== 6 passed in 0.06s ===============================
```

### Cycle observation 28

Directory: `services/event-workflow-service`. Command: `uv run pytest tests/unit/test_rejection_notifications.py --no-cov`. Exit: `1`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/event-workflow-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 7 items

tests/unit/test_rejection_notifications.py ......F                       [100%]

=================================== FAILURES ===================================
_____________ test_worker_runner_retries_then_polls_until_stopped ______________

    def test_worker_runner_retries_then_polls_until_stopped():
        """DR3: exercise public long-running worker entry with process/time mocked;
        transient failure backs off, empty work polls, keyboard interrupt exits.
        """
        import app.dispatcher as worker
        from unittest.mock import patch
        with patch.object(worker, "attempt", side_effect=[RuntimeError(), 0, 1, KeyboardInterrupt()]), patch("time.sleep") as sleep:
>           worker.run()
            ^^^^^^^^^^
E           AttributeError: module 'app.dispatcher' has no attribute 'run'

tests/unit/test_rejection_notifications.py:142: AttributeError
=========================== short test summary info ============================
FAILED tests/unit/test_rejection_notifications.py::test_worker_runner_retries_then_polls_until_stopped
========================= 1 failed, 6 passed in 0.08s ==========================
```

### Cycle observation 29

Directory: `services/event-workflow-service`. Command: `uv run pytest tests/unit/test_rejection_notifications.py --no-cov`. Exit: `0`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/event-workflow-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 7 items

tests/unit/test_rejection_notifications.py .......                       [100%]

============================== 7 passed in 0.06s ===============================
```

### Cycle observation 34

Directory: `services/notification-service`. Command: `uv run pytest tests/unit/test_event_notifications.py --no-cov`. Exit: `1`.

```text
ked.
        """
        envelope = dict(version=1, id="20000000-0000-0000-0000-000000000001",
            recipientId="10000000-0000-0000-0000-000000000001", type="event.rejection",
            createdAt="2026-10-21T01:00:00+00:00", message="Workshop was rejected: No plan",
            destination=dict(kind="event-details", eventId="30000000-0000-0000-0000-000000000001"),
            details=dict(eventName="Workshop", reason="No plan"))
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        channel = Mock()
        with patch("psycopg2.connect", return_value=connection):
            process("synthetic", channel, Mock(delivery_tag=10), json.dumps({**envelope, **change}).encode())
>       assert not any(call.args[0].startswith('INSERT INTO public."Notification" ') for call in cursor.execute.call_args_list)
E       assert not True
E        +  where True = any(<generator object test_rejection_missing_display_content_or_event_destination_is_quarantined.<locals>.<genexpr> at 0x11a49af60>)

tests/unit/test_event_notifications.py:88: AssertionError
=========================== short test summary info ============================
FAILED tests/unit/test_event_notifications.py::test_rejection_missing_display_content_or_event_destination_is_quarantined[change0]
FAILED tests/unit/test_event_notifications.py::test_rejection_missing_display_content_or_event_destination_is_quarantined[change1]
FAILED tests/unit/test_event_notifications.py::test_rejection_missing_display_content_or_event_destination_is_quarantined[change2]
FAILED tests/unit/test_event_notifications.py::test_rejection_missing_display_content_or_event_destination_is_quarantined[change3]
========================= 4 failed, 1 passed in 0.13s ==========================
```

### Cycle observation 37

Directory: `services/notification-service`. Command: `uv run pytest`. Exit: `0`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.7.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/notification-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 86 items

tests/unit/test_event_notifications.py .....                             [  5%]
tests/unit/test_notification_scrum173.py ............................... [ 41%]
..................................................                       [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                 Stmts   Miss Branch BrPart    Cover   Missing
------------------------------------------------------------------
app/__init__.py         51      0     16      0  100.00%
app/consumer.py        115      0     54      0  100.00%
app/diagnostics.py      32      0      6      0  100.00%
app/store.py            61      0      8      0  100.00%
------------------------------------------------------------------
TOTAL                  259      0     84      0  100.00%
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================== 86 passed in 0.32s ==============================
```

### Cycle observation 38

Directory: `frontend/event-management-ui`. Command: `npm test -- src/features/notifications/eventRejection.test.ts`. Exit: `1`.

```text
> event-management-ui@0.0.0 test
> vitest run src/features/notifications/eventRejection.test.ts


 RUN  v4.1.11 /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/frontend/event-management-ui

 ❯ src/features/notifications/eventRejection.test.ts (1 test | 1 failed) 3ms
   × event details notification opens existing organiser event route without a booking 2ms

⎯⎯⎯⎯⎯⎯⎯ Failed Tests 1 ⎯⎯⎯⎯⎯⎯⎯

 FAIL  src/features/notifications/eventRejection.test.ts > event details notification opens existing organiser event route without a booking
AssertionError: expected null to be '/events/30000000-0000-0000-0000-00000…' // Object.is equality

- Expected:
"/events/30000000-0000-0000-0000-000000000001"

+ Received:
null

 ❯ src/features/notifications/eventRejection.test.ts:6:64
      4| const eventId = '30000000-0000-0000-0000-000000000001'
      5| test('event details notification opens existing organiser event route …
      6|   expect(notificationPath({ kind: 'event-details', eventId })).toBe(`/…
       |                                                                ^
      7|   expect(notificationPath({ kind: 'event-details', eventId: '../../out…
      8| })

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[1/1]⎯


 Test Files  1 failed (1)
      Tests  1 failed (1)
   Start at  18:35:54
   Duration  509ms (transform 23ms, setup 79ms, import 16ms, tests 3ms, environment 346ms)
```

### Cycle observation 39

Directory: `frontend/event-management-ui`. Command: `npm test -- src/features/notifications/`. Exit: `0`.

```text
> event-management-ui@0.0.0 test
> vitest run src/features/notifications/


 RUN  v4.1.11 /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/frontend/event-management-ui


 Test Files  4 passed (4)
      Tests  42 passed (42)
   Start at  18:36:19
   Duration  945ms (transform 152ms, setup 396ms, import 179ms, tests 594ms, environment 1.66s)
```

### Cycle observation 40

Directory: `frontend/event-management-ui`. Command: `npm test -- src/pages/OrganiserEventRejection.test.tsx`. Exit: `1`.

```text
ity needs
            </dt>
            <dd>
              Not specified
            </dd>
          </div>
          <div
            class="event-detail"
          >
            <dt>
              Equipment requirements
            </dt>
            <dd>
              Not specified
            </dd>
          </div>
          <div
            class="event-detail"
          >
            <dt>
              Registration needs
            </dt>
            <dd>
              Not specified
            </dd>
          </div>
        </dl>
        <p
          class="event-footnote muted"
        >
          Assigned to
          <strong>
            Not assigned
          </strong>
        </p>
        <div
          class="event-card-section"
        >
          <h3>
            Registrations
          </h3>
          <p>
            Registrations are only available for approved events.
          </p>
        </div>
      </article>
    </div>
  </div>
</body>
 ❯ waitForWrapper node_modules/@testing-library/dom/dist/wait-for.js:163:27
 ❯ node_modules/@testing-library/dom/dist/query-helpers.js:86:33
 ❯ src/pages/OrganiserEventRejection.test.tsx:16:23
     14|   render(<OrganiserEventDetailPage eventId="30000000-0000-0000-0000-00…
     15|     organiserId="10000000-0000-0000-0000-000000000001" backLabel="My e…
     16|   expect(await screen.findByRole('heading', { name: 'Event request dec…
       |                       ^
     17|   expect(screen.getByText('Rejection reason')).toBeInTheDocument()
     18|   expect(screen.getByText(/The proposal needs a safety plan/)).toHaveT…

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[1/1]⎯


 Test Files  1 failed (1)
      Tests  1 failed (1)
   Start at  18:36:26
   Duration  1.38s (transform 42ms, setup 47ms, import 40ms, tests 1.02s, environment 204ms)
```

### Cycle observation 41

Directory: `frontend/event-management-ui`. Command: `npm test -- src/pages/OrganiserEventRejection.test.tsx src/pages/OrganiserEvents.test.tsx`. Exit: `0`.

```text
> event-management-ui@0.0.0 test
> vitest run src/pages/OrganiserEventRejection.test.tsx src/pages/OrganiserEvents.test.tsx


 RUN  v4.1.11 /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/frontend/event-management-ui


 Test Files  2 passed (2)
      Tests  10 passed (10)
   Start at  18:36:37
   Duration  614ms (transform 152ms, setup 112ms, import 163ms, tests 234ms, environment 445ms)
```

### Final `services/event-service`

Command: `uv run pytest`. Exit: `0`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/event-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 490 items

tests/test_event_summaries.py .....................                      [  4%]
tests/test_registration_events.py ..                                     [  4%]
tests/unit/test_clarification.py ...............................         [ 11%]
tests/unit/test_event_details.py .....................                   [ 15%]
tests/unit/test_event_details_recheck.py ............................... [ 21%]
..............................................................           [ 34%]
tests/unit/test_event_details_workflow.py ..........                     [ 36%]
tests/unit/test_event_list.py ...........................                [ 41%]
tests/unit/test_event_progress.py .............................          [ 47%]
tests/unit/test_notification_context.py ..                               [ 48%]
tests/unit/test_rejection_notifications.py ............................. [ 54%]
                                                                         [ 54%]
tests/unit/test_safety_approve_status.py ......................          [ 58%]
tests/unit/test_safety_gate.py ................................          [ 65%]
tests/unit/test_safety_reject_changes_status.py ........................ [ 70%]
............                                                             [ 72%]
tests/unit/test_safety_status_access.py .........                        [ 74%]
tests/unit/test_safety_submit_status.py ................................ [ 80%]
..                                                                       [ 81%]
tests/unit/test_submission.py .......................................... [ 89%]
..................................................                       [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                Stmts   Miss Branch BrPart   Cover   Missing
----------------------------------------------------------------
app/__init__.py       476      9    150      5  97.76%   126->129, 383-384, 392, 638->673, 724, 820-821, 827, 835, 845
app/models.py         471      1    150      2  99.52%   774->777, 1386
app/outbox.py          88      0     36      0 100.00%
app/validation.py      23      0     12      0 100.00%
----------------------------------------------------------------
TOTAL                1058     10    348      7  98.79%
Required test coverage of 98.79% reached. Total coverage: 98.79%
============================= 490 passed in 3.22s ==============================
```

### Final `services/event-workflow-service`

Command: `uv run pytest`. Exit: `0`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/event-workflow-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 79 items / 4 deselected / 75 selected

tests/unit/test_checks.py ........................                       [ 32%]
tests/unit/test_clients.py ..............                                [ 50%]
tests/unit/test_rejection_notifications.py ...........                   [ 65%]
tests/unit/test_startup_warning.py ..                                    [ 68%]
tests/unit/test_update_details.py ........................               [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                Stmts   Miss Branch BrPart  Cover   Missing
---------------------------------------------------------------
app/__init__.py        28      0      8      0   100%
app/checks.py          92      0     30      0   100%
app/clients.py         70      0      8      0   100%
app/dispatcher.py      89      0     14      0   100%
app/routes.py          50      0     12      0   100%
---------------------------------------------------------------
TOTAL                 329      0     72      0   100%
Required test coverage of 100.0% reached. Total coverage: 100.00%
======================= 75 passed, 4 deselected in 0.27s =======================
```

### Final `services/notification-service`

Command: `uv run pytest`. Exit: `0`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.7.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/notification-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 86 items

tests/unit/test_event_notifications.py .....                             [  5%]
tests/unit/test_notification_scrum173.py ............................... [ 41%]
..................................................                       [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                 Stmts   Miss Branch BrPart    Cover   Missing
------------------------------------------------------------------
app/__init__.py         51      0     16      0  100.00%
app/consumer.py        115      0     54      0  100.00%
app/diagnostics.py      32      0      6      0  100.00%
app/store.py            61      0      8      0  100.00%
------------------------------------------------------------------
TOTAL                  259      0     84      0  100.00%
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================== 86 passed in 0.32s ==============================
```

### Final `frontend/event-management-ui`

Command: `npm run build && npm run lint && npm test`. Exit: `0`.

```text
> event-management-ui@0.0.0 build
> tsc -b && vite build

vite v8.3.0 building client environment for production...
transforming...
✓ 100 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.73 kB │ gzip:   0.40 kB
dist/assets/index-_NRGdoq_.css   52.28 kB │ gzip:   9.54 kB
dist/assets/index-b1fEYn1E.js   438.61 kB │ gzip: 118.80 kB

✓ built in 113ms

> event-management-ui@0.0.0 lint
> oxlint

src/features/calendar/ClosureDetails.tsx:4:17: warning react(only-export-components): Fast refresh only works when a file only exports components. Use a new file to share constants or functions between components.
src/features/calendar/ClosureDetails.tsx:7:17: warning react(only-export-components): Fast refresh only works when a file only exports components. Use a new file to share constants or functions between components.
src/features/calendar/ClosureDetails.tsx:10:14: warning react(only-export-components): Fast refresh only works when a file only exports components. Use a new file to share constants or functions between components.

> event-management-ui@0.0.0 test
> vitest run


 RUN  v4.1.11 /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/frontend/event-management-ui


 Test Files  59 passed (59)
      Tests  720 passed (720)
   Start at  19:06:32
   Duration  11.40s (transform 3.22s, setup 6.85s, import 5.81s, tests 36.61s, environment 31.37s)
```

### Final `services/event-workflow-service`

Command: `uv run pytest`. Exit: `0`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/event-workflow-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 79 items / 4 deselected / 75 selected

tests/unit/test_checks.py ........................                       [ 32%]
tests/unit/test_clients.py ..............                                [ 50%]
tests/unit/test_rejection_notifications.py ...........                   [ 65%]
tests/unit/test_startup_warning.py ..                                    [ 68%]
tests/unit/test_update_details.py ........................               [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                Stmts   Miss Branch BrPart  Cover   Missing
---------------------------------------------------------------
app/__init__.py        28      0      8      0   100%
app/checks.py          92      0     30      0   100%
app/clients.py         70      0      8      0   100%
app/dispatcher.py      89      0     14      0   100%
app/routes.py          50      0     12      0   100%
---------------------------------------------------------------
TOTAL                 329      0     72      0   100%
Required test coverage of 100.0% reached. Total coverage: 100.00%
======================= 75 passed, 4 deselected in 0.29s =======================
```

### Final `services/event-workflow-service`

Command: `uv run --with psycopg2-binary python -m pytest -m integration --no-cov --tb=short --basetemp=/Users/daphnetok/.hermes/cache/scratch/scrum45-ticket01-post-refactor`. Exit: `0`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-01/services/event-workflow-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 79 items / 75 deselected / 4 selected

tests/integration/test_rejection_delivery.py ....                        [100%]

====================== 4 passed, 75 deselected in 36.61s =======================
```

### Final `frontend/event-management-ui`

Command: `npm run test:e2e -- e2e/event-rejection-notifications.spec.ts e2e/notifications.spec.ts`. Exit: `0`.

```text
> event-management-ui@0.0.0 test:e2e
> playwright test -c e2e e2e/event-rejection-notifications.spec.ts e2e/notifications.spec.ts


Running 5 tests using 5 workers

  ✓  4 [chromium] › e2e/notifications.spec.ts:76:4 › linked request fallback and legacy null card: viewable reassigned Lead event (1.2s)
  ✓  5 [chromium] › e2e/event-rejection-notifications.spec.ts:5:1 › organiser bell and inbox open event-only decision details with rejection reason (1.2s)
  ✓  2 [chromium] › e2e/notifications.spec.ts:56:1 › inaccessible event keeps notification read and renders ordinary permission fallback (1.2s)
  ✓  3 [chromium] › e2e/notifications.spec.ts:76:4 › linked request fallback and legacy null card: cancelled assigned event (1.3s)
  ✓  1 [chromium] › e2e/notifications.spec.ts:21:1 › bell opens without reading; click focuses exact rejected request; unread and identity isolation (2.3s)

  5 passed (3.3s)
```

### All-backend regression

Command: `npm run test:backend` at repository root. Exit: `0`. Exact per-service summary lines:

```text
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================== 1 passed in 0.16s ===============================
Required test coverage of 61.0% reached. Total coverage: 61.11%
============================== 1 passed in 0.12s ===============================
Required test coverage of 98.0% reached. Total coverage: 98.30%
============================== 34 passed in 0.22s ==============================
Required test coverage of 87.0% reached. Total coverage: 87.85%
============================== 37 passed in 0.24s ==============================
============================== 76 passed in 0.25s ==============================
============================= 110 passed in 0.20s ==============================
Required test coverage of 99.0% reached. Total coverage: 99.46%
============================== 53 passed in 0.24s ==============================
Required test coverage of 98.79% reached. Total coverage: 98.79%
============================= 490 passed in 3.12s ==============================
Required test coverage of 100.0% reached. Total coverage: 100.00%
======================= 75 passed, 4 deselected in 0.27s =======================
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================== 86 passed in 0.33s ==============================
Required test coverage of 98.0% reached. Total coverage: 98.77%
============================== 38 passed in 0.24s ==============================
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================= 149 passed in 0.70s ==============================
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================= 462 passed in 1.47s ==============================
Required test coverage of 97.0% reached. Total coverage: 97.87%
============================== 8 passed in 0.20s ===============================
Required test coverage of 100.0% reached. Total coverage: 100.00%
====================== 447 passed, 1 deselected in 2.34s =======================
Required test coverage of 100.0% reached. Total coverage: 100.00%
====================== 334 passed, 1 deselected in 2.60s =======================
Required test coverage of 94.0% reached. Total coverage: 94.86%
============================== 96 passed in 0.42s ==============================
```

### Final all-backend rerun after import/docstring cleanup

`npm run test:backend`, repository root, exit 0. Exact summary output:

```text
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================== 1 passed in 0.13s ===============================
Required test coverage of 61.0% reached. Total coverage: 61.11%
============================== 1 passed in 0.12s ===============================
Required test coverage of 98.0% reached. Total coverage: 98.30%
============================== 34 passed in 0.22s ==============================
Required test coverage of 87.0% reached. Total coverage: 87.85%
============================== 37 passed in 0.24s ==============================
============================== 76 passed in 0.26s ==============================
============================= 110 passed in 0.18s ==============================
Required test coverage of 99.0% reached. Total coverage: 99.46%
============================== 53 passed in 0.24s ==============================
Required test coverage of 98.79% reached. Total coverage: 98.79%
============================= 490 passed in 3.11s ==============================
Required test coverage of 100.0% reached. Total coverage: 100.00%
======================= 75 passed, 4 deselected in 0.28s =======================
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================== 86 passed in 0.34s ==============================
Required test coverage of 98.0% reached. Total coverage: 98.77%
============================== 38 passed in 0.25s ==============================
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================= 149 passed in 0.71s ==============================
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================= 462 passed in 1.49s ==============================
Required test coverage of 97.0% reached. Total coverage: 97.87%
============================== 8 passed in 0.18s ===============================
Required test coverage of 100.0% reached. Total coverage: 100.00%
====================== 447 passed, 1 deselected in 2.32s =======================
Required test coverage of 100.0% reached. Total coverage: 100.00%
====================== 334 passed, 1 deselected in 2.57s =======================
Required test coverage of 94.0% reached. Total coverage: 94.86%
============================== 96 passed in 0.46s ==============================
```
