# SCRUM-45 ticket 02 — actual execution evidence

## Verified outcome

- Approval notifications are saved transactionally by both `PATCH /events/<id>/approve` and `/progress`, preserving the submitting organiser and event name captured at the decision.
- Worker prepares/freeze-validates `event.approval`; consumer validates approval event name, decision and event-details destination. Rejection and venue notification behavior remains intact.
- New forward migration extends the existing type constraint; no historical intent is backfilled.
- Strict execution cycles below cover mutation, worker, freeze, consumer, real schema and ownerless diagnosis. Already-green rollback/no-op/isolation/frozen-retry checks are explicitly regression evidence, not invented RED observations.
- Final Event Service: **507 passed**, displayed **98.81%** coverage; floor increased **98.79 → 98.80** (unrounded coverage is 98.80534082923401%). Event Workflow: **77 passed, 8 integration tests deselected**, **100%**. Notification: **91 passed**, **100%**.
- Full backend: **17 service suites, 2521 passing tests**, exit 0. See exact per-suite output below, including a final full rerun after the coverage-floor change and completed test-only extraction.
- Real isolated PostgreSQL 17 / RabbitMQ 4: **8 passed, 77 unit tests deselected** after successful shared-helper extraction; four approval cases and four rejection regressions. Both decision routes cover actual delivery, outage recovery, replay deduplication, recipient isolation and rollback. No infrastructure skips or production database access.
- Separate browser verification: **6 passed** (approval + rejection + existing venue/inbox regression), mocked backend. Existing approval detail UI verified via status badge, recorded approval timestamp, correct event heading, read transition and bell navigation. No production frontend changes.
- Frontend build and lint exit 0; **59 Vitest files / 720 tests passed**. Three inherited Fast Refresh lint warnings and npm install's report of one high dependency vulnerability remain outside this ticket. Initial browser test had an incomplete registration fixture and an incorrect assumption that approval shares the rejection-only heading; corrected to the existing UI contract, with no production UI change.
- Self-review against AGENTS/spec: no assignment work, cross-service atomic I/O, test-to-test imports, pushes, ticket closure or production infrastructure changes. New Python feature tests contain the full story plus AC/method docstrings. Shared integration helper is extracted rather than importing a test module.
- Integration branch merged at start and rechecked before finish: `f9b02df72bd1a7546afdadfe14bc2cae274b0a09`, already up to date on final checks. Commit prefix `SCRUM-45:` was explicitly approved by the user.


Approved seams: Event HTTP mutation/outbox, worker/consumer boundaries, real isolated backend flow; separate existing UI browser seam. Initial integration merge: ce20a76 → f9b02df.

## RED 1 — approval intent

`services/event-service`: `uv run pytest tests/unit/test_approval_notifications.py --no-cov`; exit 1.

```text
Using CPython 3.12.14
Creating virtual environment at: .venv
Installed 17 packages in 12ms
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1
collected 2 items

tests/unit/test_approval_notifications.py FF                             [100%]

=================================== FAILURES ===================================
________ test_approval_records_saved_organiser_and_event_facts[approve] ________

boundary = (<FlaskClient <Flask 'app'>>, <MagicMock id='4422719424'>, <MagicMock name='mock.cursor().__enter__()' id='4457093872'>)
route = 'approve'

    @pytest.mark.parametrize("route", ["approve", "progress"])
    def test_approval_records_saved_organiser_and_event_facts(boundary, route):
        """AC1/AC3/DR4: HTTP mutation with DB I/O mocked saves original recipient/name,
        not the changed values returned by UPDATE, in its own transaction.
        """
        client, connection, cursor = boundary
        updated = {**row("Approved"), "event_name": "Renamed", "organiser_id": ACTOR}
        cursor.fetchone.side_effect = [row(), updated]
        assert approve(client, route).status_code == 200
        inserts = [call.args[1] for call in cursor.execute.call_args_list
                   if 'INSERT INTO public."EventNotificationOutbox"' in call.args[0]]
>       assert len(inserts) == 1, "Successful approval must save notification intent"
E       AssertionError: Successful approval must save notification intent
E       assert 0 == 1
E        +  where 0 = len([])

tests/unit/test_approval_notifications.py:56: AssertionError
_______ test_approval_records_saved_organiser_and_event_facts[progress] ________

boundary = (<FlaskClient <Flask 'app'>>, <MagicMock id='4469201456'>, <MagicMock name='mock.cursor().__enter__()' id='4469211360'>)
route = 'progress'

    @pytest.mark.parametrize("route", ["approve", "progress"])
    def test_approval_records_saved_organiser_and_event_facts(boundary, route):
        """AC1/AC3/DR4: HTTP mutation with DB I/O mocked saves original recipient/name,
        not the changed values returned by UPDATE, in its own transaction.
        """
        client, connection, cursor = boundary
        updated = {**row("Approved"), "event_name": "Renamed", "organiser_id": ACTOR}
        cursor.fetchone.side_effect = [row(), updated]
        assert approve(client, route).status_code == 200
        inserts = [call.args[1] for call in cursor.execute.call_args_list
                   if 'INSERT INTO public."EventNotificationOutbox"' in call.args[0]]
>       assert len(inserts) == 1, "Successful approval must save notification intent"
E       AssertionError: Successful approval must save notification intent
E       assert 0 == 1
E        +  where 0 = len([])

tests/unit/test_approval_notifications.py:56: AssertionError
=========================== short test summary info ============================
FAILED tests/unit/test_approval_notifications.py::test_approval_records_saved_organiser_and_event_facts[approve]
FAILED tests/unit/test_approval_notifications.py::test_approval_records_saved_organiser_and_event_facts[progress]
============================== 2 failed in 1.66s ===============================
```

## GREEN 1

`services/event-service`: `uv run pytest tests/unit/test_approval_notifications.py --no-cov`; exit 0.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1
collected 2 items

tests/unit/test_approval_notifications.py ..                             [100%]

============================== 2 passed in 0.11s ===============================
```

## Approval negative-path regression (already GREEN; not claimed RED)

`services/event-service`: `uv run pytest tests/unit/test_approval_notifications.py --no-cov`; exit 0.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1
collected 10 items

tests/unit/test_approval_notifications.py ..........                     [100%]

============================== 10 passed in 0.15s ==============================
```

## RED 2 — worker approval envelope

`services/event-workflow-service`: `uv run pytest tests/unit/test_approval_notifications.py --no-cov`; exit 1.

```text
Using CPython 3.12.14
Creating virtual environment at: .venv
Installed 23 packages in 52ms
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-workflow-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 1 item

tests/unit/test_approval_notifications.py F                              [100%]

=================================== FAILURES ===================================
___________ test_approval_worker_freezes_saved_facts_before_publish ____________

    def test_approval_worker_freezes_saved_facts_before_publish():
        """AC1/AC3/DR4: real dispatch boundary with external API/broker mocked;
        saved approval facts produce frozen message before confirmed publication.
        """
        api, publish = Mock(), Mock()
        api.claim.return_value = [JOB]
        api.freeze.side_effect = lambda job, envelope: envelope
        assert dispatch_once(api, publish) == 1
        expected = dict(version=1, id=JOB["id"], type="event.approval",
            recipientId=SOURCE["recipientId"], createdAt=JOB["createdAt"],
            message="Community Workshop was approved",
            destination=dict(kind="event-details", eventId=SOURCE["eventId"]), details=SOURCE)
>       publish.assert_called_once_with(expected)

tests/unit/test_approval_notifications.py:27:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

self = <Mock id='4356934064'>
args = ({'version': 1, 'id': '20000000-0000-0000-0000-000000000001', 'type': 'event.approval', 'recipientId': '10000000-0000-0000-0000-000000000001', ...},)
kwargs = {}

    def assert_called_once_with(self, /, *args, **kwargs):
        """assert that the mock was called exactly once and that that call was
        with the specified arguments."""
        if not self.call_count == 1:
            msg = ("Expected '%s' to be called once. Called %s times.%s"
                   % (self._mock_name or 'mock',
                      self.call_count,
                      self._calls_repr()))
>           raise AssertionError(msg)
E           AssertionError: Expected 'mock' to be called once. Called 0 times.

/Users/daphnetok/.local/share/uv/python/cpython-3.12.14-macos-aarch64-none/lib/python3.12/unittest/mock.py:960: AssertionError
------------------------------ Captured log call -------------------------------
WARNING  app.dispatcher:dispatcher.py:66 Dispatch retry source=20000000-0000-0000-0000-000000000001 error=KeyError
=========================== short test summary info ============================
FAILED tests/unit/test_approval_notifications.py::test_approval_worker_freezes_saved_facts_before_publish
============================== 1 failed in 0.56s ===============================
```

## GREEN 2 — approval plus rejection

`services/event-workflow-service`: `uv run pytest tests/unit/test_approval_notifications.py tests/unit/test_rejection_notifications.py --no-cov`; exit 0.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-workflow-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 12 items

tests/unit/test_approval_notifications.py .                              [  8%]
tests/unit/test_rejection_notifications.py ...........                   [100%]

============================== 12 passed in 0.10s ==============================
```

## RED 3 — owner freeze approval

`services/event-service`: `uv run pytest tests/unit/test_approval_notifications.py -k frozen --no-cov`; exit 1.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1
collected 11 items / 10 deselected / 1 selected

tests/unit/test_approval_notifications.py F                              [100%]

=================================== FAILURES ===================================
______________ test_approval_envelope_can_be_frozen_and_read_back ______________

boundary = (<FlaskClient <Flask 'app'>>, <MagicMock id='4376902688'>, <MagicMock name='mock.cursor().__enter__()' id='4372127648'>)

    def test_approval_envelope_can_be_frozen_and_read_back(boundary):
        """AC1/AC3/DR4: owner HTTP accepts approval facts and returns immutable envelope."""
        client, _, cursor = boundary
        pending = dict(source_id=JOB_ID, source=SOURCE, type="event.approval",
                       envelope=None, attempts=1, lease_token=LEASE, lease_valid=True,
                       created_at=datetime(2026, 10, 21, tzinfo=UTC))
        cursor.fetchone.side_effect = [pending, {**pending, "envelope": ENVELOPE}]
>       result = client.post(f"/internal/notification-outbox/{JOB_ID}/freeze", headers=HEADERS,
                             json={"leaseToken": LEASE, "envelope": ENVELOPE})

tests/unit/test_approval_notifications.py:124:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
.venv/lib/python3.12/site-packages/werkzeug/test.py:1171: in post
    return self.open(*args, **kw)
           ^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.12/site-packages/flask/testing.py:235: in open
    response = super().open(
.venv/lib/python3.12/site-packages/werkzeug/test.py:1120: in open
    response_parts = self.run_wsgi_app(request.environ, buffered=buffered)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.12/site-packages/werkzeug/test.py:992: in run_wsgi_app
    rv = run_wsgi_app(self.application, environ, buffered=buffered)
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.12/site-packages/werkzeug/test.py:1268: in run_wsgi_app
    app_rv = app(environ, start_response)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.12/site-packages/flask/app.py:1536: in __call__
    return self.wsgi_app(environ, start_response)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.12/site-packages/flask/app.py:1514: in wsgi_app
    response = self.handle_exception(e)
               ^^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.12/site-packages/flask/app.py:1511: in wsgi_app
    response = self.full_dispatch_request()
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.12/site-packages/flask/app.py:919: in full_dispatch_request
    rv = self.handle_user_exception(e)
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.12/site-packages/flask/app.py:917: in full_dispatch_request
    rv = self.dispatch_request()
         ^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.12/site-packages/flask/app.py:902: in dispatch_request
    return self.ensure_sync(self.view_functions[rule.endpoint])(**view_args)  # type: ignore[no-any-return]
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
app/outbox.py:135: in operate
    result = mutate(dsn, str(identifier), token, action, data)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
app/outbox.py:63: in mutate
    validate_envelope(envelope, row)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

value = {'createdAt': '2026-10-21T00:00:00+00:00', 'destination': {'eventId': '30000000-0000-0000-0000-000000000001', 'kind': ...y Workshop', 'recipientId': '10000000-0000-0000-0000-000000000001'}, 'id': '20000000-0000-0000-0000-000000000001', ...}
row = {'source_id': '20000000-0000-0000-0000-000000000001', 'source': {'eventId': '30000000-0000-0000-0000-000000000001', 'e...tId': '10000000-0000-0000-0000-000000000001', 'decision': 'Approved'}, 'type': 'event.approval', 'envelope': None, ...}

    def validate_envelope(value, row):
        if (
            not isinstance(value, dict)
            or type(value.get("version")) is not int
            or value.get("version") != 1
        ):
            raise ValueError("Invalid envelope")
        source = row["source"]
        destination = value.get("destination")
        if value.get("id") != str(row["source_id"]) or value.get("type") != row["type"]:
            raise ValueError("Invalid source identity")
        if value.get("recipientId") != source["recipientId"]:
            raise ValueError("Invalid recipient")
        if value.get("createdAt") != row["created_at"].isoformat():
            raise ValueError("Invalid creation instant")
        if destination != dict(kind="event-details", eventId=source["eventId"]):
            raise ValueError("Invalid destination")
        if value.get("details") != source:
            raise ValueError("Invalid historical content")
>       if value.get("message") != f"{source['eventName']} was rejected: {source['reason']}":
                                                                          ^^^^^^^^^^^^^^^^
E       KeyError: 'reason'

app/outbox.py:108: KeyError
=========================== short test summary info ============================
FAILED tests/unit/test_approval_notifications.py::test_approval_envelope_can_be_frozen_and_read_back
======================= 1 failed, 10 deselected in 0.15s =======================
```

## RED 3 confirmed HTTP assertion — missing approval handling

`services/event-service`: `uv run pytest tests/unit/test_approval_notifications.py -k frozen --no-cov --tb=short`; exit 1.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1
collected 11 items / 10 deselected / 1 selected

tests/unit/test_approval_notifications.py F                              [100%]

=================================== FAILURES ===================================
______________ test_approval_envelope_can_be_frozen_and_read_back ______________
tests/unit/test_approval_notifications.py:127: in test_approval_envelope_can_be_frozen_and_read_back
    assert result.status_code == 200
E   assert 500 == 200
E    +  where 500 = <WrapperTestResponse streamed [500 INTERNAL SERVER ERROR]>.status_code
------------------------------ Captured log call -------------------------------
ERROR    app:app.py:875 Exception on /internal/notification-outbox/20000000-0000-0000-0000-000000000001/freeze [POST]
Traceback (most recent call last):
  File "/Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-service/.venv/lib/python3.12/site-packages/flask/app.py", line 1511, in wsgi_app
    response = self.full_dispatch_request()
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-service/.venv/lib/python3.12/site-packages/flask/app.py", line 919, in full_dispatch_request
    rv = self.handle_user_exception(e)
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-service/.venv/lib/python3.12/site-packages/flask/app.py", line 917, in full_dispatch_request
    rv = self.dispatch_request()
         ^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-service/.venv/lib/python3.12/site-packages/flask/app.py", line 902, in dispatch_request
    return self.ensure_sync(self.view_functions[rule.endpoint])(**view_args)  # type: ignore[no-any-return]
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-service/app/outbox.py", line 135, in operate
    result = mutate(dsn, str(identifier), token, action, data)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-service/app/outbox.py", line 63, in mutate
    validate_envelope(envelope, row)
  File "/Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-service/app/outbox.py", line 108, in validate_envelope
    if value.get("message") != f"{source['eventName']} was rejected: {source['reason']}":
                                                                      ~~~~~~^^^^^^^^^^
KeyError: 'reason'
=========================== short test summary info ============================
FAILED tests/unit/test_approval_notifications.py::test_approval_envelope_can_be_frozen_and_read_back
======================= 1 failed, 10 deselected in 0.12s =======================
```

## GREEN 3 — approval freeze and rejection regression

`services/event-service`: `uv run pytest tests/unit/test_approval_notifications.py tests/unit/test_rejection_notifications.py --no-cov`; exit 0.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1
collected 40 items

tests/unit/test_approval_notifications.py ...........                    [ 27%]
tests/unit/test_rejection_notifications.py ............................. [100%]

============================== 40 passed in 0.21s ==============================
```

## RED 4 — invalid approval quarantine

`services/notification-service`: `uv run pytest tests/unit/test_approval_notifications.py --no-cov --tb=short`; exit 1.

```text
Using CPython 3.12.14
Creating virtual environment at: .venv
Installed 17 packages in 36ms
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.7.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/notification-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1
collected 4 items

tests/unit/test_approval_notifications.py FFFF                           [100%]

=================================== FAILURES ===================================
________ test_invalid_approval_display_contract_is_quarantined[change0] ________
tests/unit/test_approval_notifications.py:30: in test_invalid_approval_display_contract_is_quarantined
    assert not any(call.args[0].startswith('INSERT INTO public."Notification" ')
E   assert not True
E    +  where True = any(<generator object test_invalid_approval_display_contract_is_quarantined.<locals>.<genexpr> at 0x111120fb0>)
________ test_invalid_approval_display_contract_is_quarantined[change1] ________
tests/unit/test_approval_notifications.py:30: in test_invalid_approval_display_contract_is_quarantined
    assert not any(call.args[0].startswith('INSERT INTO public."Notification" ')
E   assert not True
E    +  where True = any(<generator object test_invalid_approval_display_contract_is_quarantined.<locals>.<genexpr> at 0x10676c040>)
________ test_invalid_approval_display_contract_is_quarantined[change2] ________
tests/unit/test_approval_notifications.py:30: in test_invalid_approval_display_contract_is_quarantined
    assert not any(call.args[0].startswith('INSERT INTO public."Notification" ')
E   assert not True
E    +  where True = any(<generator object test_invalid_approval_display_contract_is_quarantined.<locals>.<genexpr> at 0x10676c040>)
________ test_invalid_approval_display_contract_is_quarantined[change3] ________
tests/unit/test_approval_notifications.py:30: in test_invalid_approval_display_contract_is_quarantined
    assert not any(call.args[0].startswith('INSERT INTO public."Notification" ')
E   assert not True
E    +  where True = any(<generator object test_invalid_approval_display_contract_is_quarantined.<locals>.<genexpr> at 0x1111239f0>)
=========================== short test summary info ============================
FAILED tests/unit/test_approval_notifications.py::test_invalid_approval_display_contract_is_quarantined[change0]
FAILED tests/unit/test_approval_notifications.py::test_invalid_approval_display_contract_is_quarantined[change1]
FAILED tests/unit/test_approval_notifications.py::test_invalid_approval_display_contract_is_quarantined[change2]
FAILED tests/unit/test_approval_notifications.py::test_invalid_approval_display_contract_is_quarantined[change3]
============================== 4 failed in 1.79s ===============================
```

## GREEN 4

`services/notification-service`: `uv run pytest tests/unit/test_approval_notifications.py --no-cov`; exit 0.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.7.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/notification-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1
collected 4 items

tests/unit/test_approval_notifications.py ....                           [100%]

============================== 4 passed in 0.10s ===============================
```

## Full relevant service GREEN and regression

`services/event-service`: `uv run pytest`; exit 0.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 507 items

tests/test_event_summaries.py .....................                      [  4%]
tests/test_registration_events.py ..                                     [  4%]
tests/unit/test_approval_notifications.py .................              [  7%]
tests/unit/test_clarification.py ...............................         [ 14%]
tests/unit/test_event_details.py .....................                   [ 18%]
tests/unit/test_event_details_recheck.py ............................... [ 24%]
..............................................................           [ 36%]
tests/unit/test_event_details_workflow.py ..........                     [ 38%]
tests/unit/test_event_list.py ...........................                [ 43%]
tests/unit/test_event_progress.py .............................          [ 49%]
tests/unit/test_notification_context.py ..                               [ 49%]
tests/unit/test_rejection_notifications.py ............................. [ 55%]
                                                                         [ 55%]
tests/unit/test_safety_approve_status.py ......................          [ 59%]
tests/unit/test_safety_gate.py ................................          [ 66%]
tests/unit/test_safety_reject_changes_status.py ........................ [ 71%]
............                                                             [ 73%]
tests/unit/test_safety_status_access.py .........                        [ 75%]
tests/unit/test_safety_submit_status.py ................................ [ 81%]
..                                                                       [ 81%]
tests/unit/test_submission.py .......................................... [ 90%]
..................................................                       [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                Stmts   Miss Branch BrPart   Cover   Missing
----------------------------------------------------------------
app/__init__.py       476      9    150      5  97.76%   126->129, 383-384, 392, 638->673, 724, 820-821, 827, 835, 845
app/models.py         481      1    156      2  99.53%   774->777, 1388
app/outbox.py          89      0     36      0 100.00%
app/validation.py      23      0     12      0 100.00%
----------------------------------------------------------------
TOTAL                1069     10    354      7  98.81%
Required test coverage of 98.79% reached. Total coverage: 98.81%
============================= 507 passed in 3.52s ==============================
```

## Full relevant service GREEN and regression

`services/event-workflow-service`: `uv run pytest`; exit 0.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-workflow-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 81 items / 4 deselected / 77 selected

tests/unit/test_approval_notifications.py ..                             [  2%]
tests/unit/test_checks.py ........................                       [ 33%]
tests/unit/test_clients.py ..............                                [ 51%]
tests/unit/test_rejection_notifications.py ...........                   [ 66%]
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
======================= 77 passed, 4 deselected in 0.32s =======================
```

## Full relevant service GREEN and regression

`services/notification-service`: `uv run pytest`; exit 0.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.7.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/notification-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 91 items

tests/unit/test_approval_notifications.py .....                          [  5%]
tests/unit/test_event_notifications.py .....                             [ 10%]
tests/unit/test_notification_scrum173.py ............................... [ 45%]
..................................................                       [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                 Stmts   Miss Branch BrPart    Cover   Missing
------------------------------------------------------------------
app/__init__.py         51      0     16      0  100.00%
app/consumer.py        123      0     62      0  100.00%
app/diagnostics.py      32      0      6      0  100.00%
app/store.py            61      0      8      0  100.00%
------------------------------------------------------------------
TOTAL                  267      0     92      0  100.00%
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================== 91 passed in 0.32s ==============================
```

## Harness baseline — shared helper copied, rejection still used its local fixture (see review correction)

`services/event-workflow-service`: `uv run --with psycopg2-binary python -m pytest -m integration --no-cov --tb=short --basetemp=../../.scratch/ticket02-refactor`; exit 0.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-workflow-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 81 items / 77 deselected / 4 selected

tests/integration/test_rejection_delivery.py ....                        [100%]

====================== 4 passed, 77 deselected in 36.80s =======================
```

## RED 5 — real approval schema persistence

`services/event-workflow-service`: `uv run --with psycopg2-binary python -m pytest tests/integration/test_approval_delivery.py -m integration --no-cov --tb=short --basetemp=../../.scratch/ticket02-red-schema`; exit 1.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-workflow-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 2 items

tests/integration/test_approval_delivery.py FF                           [100%]

=================================== FAILURES ===================================
_ test_real_approval_is_retrievable_after_broker_outage_with_saved_facts[approve] _
tests/integration/test_approval_delivery.py:25: in test_real_approval_is_retrievable_after_broker_outage_with_saved_facts
    assert result.status_code == 200, result.text
E   AssertionError: {"message":"Unable to save or load event requests. Please check the Event Service database connection and schema."}
E
E   assert 503 == 200
E    +  where 503 = <Response [503 SERVICE UNAVAILABLE]>.status_code
_ test_real_approval_is_retrievable_after_broker_outage_with_saved_facts[progress] _
tests/integration/test_approval_delivery.py:25: in test_real_approval_is_retrievable_after_broker_outage_with_saved_facts
    assert result.status_code == 200, result.text
E   AssertionError: {"message":"Unable to save or load event requests. Please check the Event Service database connection and schema."}
E
E   assert 503 == 200
E    +  where 503 = <Response [503 SERVICE UNAVAILABLE]>.status_code
=========================== short test summary info ============================
FAILED tests/integration/test_approval_delivery.py::test_real_approval_is_retrievable_after_broker_outage_with_saved_facts[approve]
FAILED tests/integration/test_approval_delivery.py::test_real_approval_is_retrievable_after_broker_outage_with_saved_facts[progress]
============================== 2 failed in 11.42s ==============================
```

## GREEN 5 — real approval persistence and outage recovery

`services/event-workflow-service`: `uv run --with psycopg2-binary python -m pytest tests/integration/test_approval_delivery.py -m integration --no-cov --tb=short --basetemp=../../.scratch/ticket02-green-schema`; exit 0.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-workflow-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 2 items

tests/integration/test_approval_delivery.py ..                           [100%]

============================== 2 passed in 19.84s ==============================
```

## Separate UI browser verification (existing UI, not new production behavior)

`frontend/event-management-ui`: `npm ci && npm run test:e2e -- e2e/event-approval-notifications.spec.ts e2e/event-rejection-notifications.spec.ts e2e/notifications.spec.ts`; exit 1.

```text
added 138 packages, and audited 139 packages in 5s

29 packages are looking for funding
  run `npm fund` for details

1 high severity vulnerability

To address all issues, run:
  npm audit fix

Run `npm audit` for details.
npm warn install-scripts 1 package has install scripts not yet covered by allowScripts:
npm warn install-scripts   fsevents@2.3.3 (install: (install scripts present))
npm warn install-scripts
npm warn install-scripts Run `npm install-scripts ls` to review, or `npm install-scripts approve <pkg>` to allow.

> event-management-ui@0.0.0 test:e2e
> playwright test -c e2e e2e/event-approval-notifications.spec.ts e2e/event-rejection-notifications.spec.ts e2e/notifications.spec.ts


Running 6 tests using 5 workers

  ✓  2 [chromium] › e2e/event-rejection-notifications.spec.ts:5:1 › organiser bell and inbox open event-only decision details with rejection reason (1.2s)
  ✓  3 [chromium] › e2e/notifications.spec.ts:76:4 › linked request fallback and legacy null card: cancelled assigned event (1.2s)
  ✓  4 [chromium] › e2e/notifications.spec.ts:56:1 › inaccessible event keeps notification read and renders ordinary permission fallback (1.2s)
  ✓  6 [chromium] › e2e/notifications.spec.ts:76:4 › linked request fallback and legacy null card: viewable reassigned Lead event (561ms)
  ✓  5 [chromium] › e2e/notifications.spec.ts:21:1 › bell opens without reading; click focuses exact rejected request; unread and identity isolation (2.2s)
  ✘  1 [chromium] › e2e/event-approval-notifications.spec.ts:4:1 › organiser bell and inbox open event-only decision details with recorded approval (6.1s)


  1) [chromium] › e2e/event-approval-notifications.spec.ts:4:1 › organiser bell and inbox open event-only decision details with recorded approval

    Error: expect(locator).toBeVisible() failed

    Locator: getByRole('heading', { name: 'Event request decision' })
    Expected: visible
    Timeout: 5000ms
    Error: element(s) not found

    Call log:
      - Expect "toBeVisible" getByRole('heading', { name: 'Event request decision' }) with timeout 5000ms
      - waiting for getByRole('heading', { name: 'Event request decision' })


      21 |   await page.getByRole('link', { name: 'Open notification' }).click()
      22 |   await expect(page).toHaveURL(`/events/${eventId}`)
    > 23 |   await expect(page.getByRole('heading', { name: 'Event request decision' })).toBeVisible()
         |                                                                               ^
      24 |   await expect(page.getByText('Approved', { exact: true })).toHaveCount(2)
      25 |   await expect(page.getByRole('heading', { name: 'Rejection reason' })).toHaveCount(0)
      26 |   await expect(page.getByRole('heading', { name: 'Community Workshop', exact: true })).toBeVisible()
        at /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/frontend/event-management-ui/e2e/event-approval-notifications.spec.ts:23:79

    Error: requests to services with no mock

    expect(received).toEqual(expected) // deep equality

    - Expected  - 1
    + Received  + 3

    - Array []
    + Array [
    +   "GET http://localhost:5009/events/30000000-0000-0000-0000-000000000001/registrations",
    + ]

       at fixtures.ts:60

      58 |     const calls: string[] = []
      59 |     await use(calls)
    > 60 |     expect(calls, 'requests to services with no mock').toEqual([])
         |                                                        ^
      61 |   },
      62 |   mockApi: async ({ unmocked }, use) => {
      63 |     await use(async (page) => {
        at Object.unmocked (/Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/frontend/event-management-ui/e2e/fixtures.ts:60:56)

    Error Context: test-results/event-approval-notificatio-33236-ails-with-recorded-approval-chromium/error-context.md

  1 failed
    [chromium] › e2e/event-approval-notifications.spec.ts:4:1 › organiser bell and inbox open event-only decision details with recorded approval
  5 passed (9.1s)
```

## Separate UI corrected fixture and existing approval display assertions

`frontend/event-management-ui`: `npm run test:e2e -- e2e/event-approval-notifications.spec.ts e2e/event-rejection-notifications.spec.ts e2e/notifications.spec.ts`; exit 0.

```text
> event-management-ui@0.0.0 test:e2e
> playwright test -c e2e e2e/event-approval-notifications.spec.ts e2e/event-rejection-notifications.spec.ts e2e/notifications.spec.ts


Running 6 tests using 5 workers

  ✓  2 [chromium] › e2e/notifications.spec.ts:56:1 › inaccessible event keeps notification read and renders ordinary permission fallback (1.2s)
  ✓  4 [chromium] › e2e/event-rejection-notifications.spec.ts:5:1 › organiser bell and inbox open event-only decision details with rejection reason (1.2s)
  ✓  1 [chromium] › e2e/event-approval-notifications.spec.ts:4:1 › organiser bell and inbox open event-only decision details with recorded approval (1.3s)
  ✓  5 [chromium] › e2e/notifications.spec.ts:76:4 › linked request fallback and legacy null card: cancelled assigned event (1.3s)
  ✓  6 [chromium] › e2e/notifications.spec.ts:76:4 › linked request fallback and legacy null card: viewable reassigned Lead event (939ms)
  ✓  3 [chromium] › e2e/notifications.spec.ts:21:1 › bell opens without reading; click focuses exact rejected request; unread and identity isolation (2.3s)

  6 passed (3.4s)
```

## Full real isolated approval/rejection integration

`services/event-workflow-service`: `uv run --with psycopg2-binary python -m pytest -m integration --no-cov --tb=short --basetemp=../../.scratch/ticket02-full-integration`; exit 0.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-workflow-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 85 items / 77 deselected / 8 selected

tests/integration/test_approval_delivery.py ....                         [ 50%]
tests/integration/test_rejection_delivery.py ....                        [100%]

================= 8 passed, 77 deselected in 69.67s (0:01:09) ==================
```

## Frontend full build/lint/unit regression

`frontend/event-management-ui`: `npm run build && npm run lint && npm test`; exit 0.

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

✓ built in 597ms

> event-management-ui@0.0.0 lint
> oxlint

src/features/calendar/ClosureDetails.tsx:4:17: warning react(only-export-components): Fast refresh only works when a file only exports components. Use a new file to share constants or functions between components.
src/features/calendar/ClosureDetails.tsx:7:17: warning react(only-export-components): Fast refresh only works when a file only exports components. Use a new file to share constants or functions between components.
src/features/calendar/ClosureDetails.tsx:10:14: warning react(only-export-components): Fast refresh only works when a file only exports components. Use a new file to share constants or functions between components.

> event-management-ui@0.0.0 test
> vitest run


 RUN  v4.1.11 /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/frontend/event-management-ui


 Test Files  59 passed (59)
      Tests  720 passed (720)
   Start at  19:30:54
   Duration  34.81s (transform 9.55s, setup 22.28s, import 15.56s, tests 108.62s, environment 110.05s)
```

## Full backend regression

``: `npm run test:backend`; exit 0.

```text
> is212-g7t4@0.0.0 test:backend
> for d in services/*/; do (cd "$d" && uv run pytest) || exit 1; done

Using CPython 3.12.14
Creating virtual environment at: .venv
Installed 15 packages in 66ms
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/_template-atomic-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 1 item

tests/unit/test_health.py .                                              [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name              Stmts   Miss Branch BrPart  Cover   Missing
-------------------------------------------------------------
app/__init__.py       6      0      0      0   100%
app/models.py         0      0      0      0   100%
app/routes.py         5      0      0      0   100%
-------------------------------------------------------------
TOTAL                11      0      0      0   100%
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================== 1 passed in 0.69s ===============================
Using CPython 3.12.14
Creating virtual environment at: .venv
Installed 22 packages in 26ms
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/_template-composite-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 1 item

tests/unit/test_health.py .                                              [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name              Stmts   Miss Branch BrPart  Cover   Missing
-------------------------------------------------------------
app/__init__.py       6      0      0      0   100%
app/clients.py        7      7      0      0     0%   1-15
app/routes.py         5      0      0      0   100%
-------------------------------------------------------------
TOTAL                18      7      0      0    61%
Required test coverage of 61.0% reached. Total coverage: 61.11%
============================== 1 passed in 0.66s ===============================
Using CPython 3.12.14
Creating virtual environment at: .venv
Installed 22 packages in 25ms
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/attendee-registration-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 34 items

tests/unit/test_clients.py .........                                     [ 26%]
tests/unit/test_routes.py ......................                         [ 91%]
tests/unit/test_validation.py ...                                        [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                Stmts   Miss Branch BrPart  Cover   Missing
---------------------------------------------------------------
app/__init__.py        25      0      6      1    97%   20->23
app/clients.py         37      0      4      0   100%
app/routes.py          66      0     10      0   100%
app/validation.py      20      1      8      1    93%   33
---------------------------------------------------------------
TOTAL                 148      1     28      2    98%
Required test coverage of 98.0% reached. Total coverage: 98.30%
============================== 34 passed in 1.26s ==============================
Using CPython 3.12.14
Creating virtual environment at: .venv
Installed 22 packages in 29ms
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/coordinator-assignment-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 37 items

tests/unit/test_clients.py ......                                        [ 16%]
tests/unit/test_health.py ...............................                [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name              Stmts   Miss Branch BrPart  Cover   Missing
-------------------------------------------------------------
app/__init__.py      24      5      6      3    73%   17->20, 21-24, 26
app/clients.py       30      5      4      0    79%   32-36
app/routes.py        93      6     24      1    94%   21, 39-40, 156, 211-212
-------------------------------------------------------------
TOTAL               147     16     34      4    88%
Required test coverage of 87.0% reached. Total coverage: 87.85%
============================== 37 passed in 1.02s ==============================
Using CPython 3.13.9 interpreter at: /opt/anaconda3/bin/python3
Creating virtual environment at: .venv
Installed 16 packages in 23ms
============================= test session starts ==============================
platform darwin -- Python 3.13.9, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/equipment-request-service
configfile: pyproject.toml
plugins: cov-7.1.0
collected 76 items

tests/test_equipment_requests.py ....................................... [ 51%]
.....................................                                    [100%]

============================== 76 passed in 3.00s ==============================
Using CPython 3.12.14
Creating virtual environment at: .venv
Installed 21 packages in 35ms
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/equipment-reservation-service
configfile: pyproject.toml
plugins: cov-7.1.0, anyio-4.15.1
collected 110 items

tests/test_availability.py ........                                      [  7%]
tests/test_clients.py ..................                                 [ 23%]
tests/test_health.py .                                                   [ 24%]
tests/test_reservations_api.py ......................................... [ 61%]
..........................................                               [100%]

============================= 110 passed in 0.81s ==============================
Using CPython 3.12.14
Creating virtual environment at: .venv
Installed 17 packages in 23ms
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/equipment-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 53 items

tests/unit/test_equipment_api.py ...........................             [ 50%]
tests/unit/test_equipment_classes.py .............                       [ 75%]
tests/unit/test_seed_data.py .............                               [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name               Stmts   Miss Branch BrPart  Cover   Missing
--------------------------------------------------------------
app/__init__.py       87      0     32      1    99%   65->68
app/equipment.py      42      0      0      0   100%
app/models.py         21      0      2      0   100%
--------------------------------------------------------------
TOTAL                150      0     34      1    99%
Required test coverage of 99.0% reached. Total coverage: 99.46%
============================== 53 passed in 3.84s ==============================
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 507 items

tests/test_event_summaries.py .....................                      [  4%]
tests/test_registration_events.py ..                                     [  4%]
tests/unit/test_approval_notifications.py .................              [  7%]
tests/unit/test_clarification.py ...............................         [ 14%]
tests/unit/test_event_details.py .....................                   [ 18%]
tests/unit/test_event_details_recheck.py ............................... [ 24%]
..............................................................           [ 36%]
tests/unit/test_event_details_workflow.py ..........                     [ 38%]
tests/unit/test_event_list.py ...........................                [ 43%]
tests/unit/test_event_progress.py .............................          [ 49%]
tests/unit/test_notification_context.py ..                               [ 49%]
tests/unit/test_rejection_notifications.py ............................. [ 55%]
                                                                         [ 55%]
tests/unit/test_safety_approve_status.py ......................          [ 59%]
tests/unit/test_safety_gate.py ................................          [ 66%]
tests/unit/test_safety_reject_changes_status.py ........................ [ 71%]
............                                                             [ 73%]
tests/unit/test_safety_status_access.py .........                        [ 75%]
tests/unit/test_safety_submit_status.py ................................ [ 81%]
..                                                                       [ 81%]
tests/unit/test_submission.py .......................................... [ 90%]
..................................................                       [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                Stmts   Miss Branch BrPart   Cover   Missing
----------------------------------------------------------------
app/__init__.py       476      9    150      5  97.76%   126->129, 383-384, 392, 638->673, 724, 820-821, 827, 835, 845
app/models.py         481      1    156      2  99.53%   774->777, 1388
app/outbox.py          89      0     36      0 100.00%
app/validation.py      23      0     12      0 100.00%
----------------------------------------------------------------
TOTAL                1069     10    354      7  98.81%
Required test coverage of 98.79% reached. Total coverage: 98.81%
============================= 507 passed in 7.73s ==============================
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-workflow-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 85 items / 8 deselected / 77 selected

tests/unit/test_approval_notifications.py ..                             [  2%]
tests/unit/test_checks.py ........................                       [ 33%]
tests/unit/test_clients.py ..............                                [ 51%]
tests/unit/test_rejection_notifications.py ...........                   [ 66%]
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
======================= 77 passed, 8 deselected in 0.39s =======================
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.7.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/notification-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 91 items

tests/unit/test_approval_notifications.py .....                          [  5%]
tests/unit/test_event_notifications.py .....                             [ 10%]
tests/unit/test_notification_scrum173.py ............................... [ 45%]
..................................................                       [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                 Stmts   Miss Branch BrPart    Cover   Missing
------------------------------------------------------------------
app/__init__.py         51      0     16      0  100.00%
app/consumer.py        123      0     62      0  100.00%
app/diagnostics.py      32      0      6      0  100.00%
app/store.py            61      0      8      0  100.00%
------------------------------------------------------------------
TOTAL                  267      0     92      0  100.00%
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================== 91 passed in 0.45s ==============================
Using CPython 3.12.14
Creating virtual environment at: .venv
Installed 17 packages in 14ms
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/registration-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 38 items

tests/unit/test_registrations.py ......................................  [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name              Stmts   Miss Branch BrPart  Cover   Missing
-------------------------------------------------------------
app/__init__.py      87      1     22      1    98%   35->38, 50
app/models.py        48      0      6      0   100%
-------------------------------------------------------------
TOTAL               135      1     28      1    99%
Required test coverage of 98.0% reached. Total coverage: 98.77%
============================== 38 passed in 2.99s ==============================
Using CPython 3.12.14
Creating virtual environment at: .venv
Installed 17 packages in 14ms
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/safety-check-record-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 149 items

tests/unit/test_health.py .                                              [  0%]
tests/unit/test_safety_decision.py ........................              [ 16%]
tests/unit/test_safety_reject_changes.py ..............................  [ 36%]
tests/unit/test_safety_rounds.py ....................................... [ 63%]
........                                                                 [ 68%]
tests/unit/test_safety_withdrawal.py ................................... [ 91%]
............                                                             [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name              Stmts   Miss Branch BrPart  Cover   Missing
-------------------------------------------------------------
app/__init__.py     260      0    116      0   100%
app/models.py       154      0     40      0   100%
-------------------------------------------------------------
TOTAL               414      0    156      0   100%
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================= 149 passed in 3.34s ==============================
Using CPython 3.12.14
Creating virtual environment at: .venv
Installed 22 packages in 36ms
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/safety-check-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 462 items

tests/unit/test_clients.py ............................................. [  9%]
...................................                                      [ 17%]
tests/unit/test_safety_approve.py ...................................... [ 25%]
..........                                                               [ 27%]
tests/unit/test_safety_feedback.py ...........                           [ 30%]
tests/unit/test_safety_queue.py .......................................  [ 38%]
tests/unit/test_safety_readiness.py ..............................       [ 45%]
tests/unit/test_safety_recheck.py ...................................... [ 53%]
..................................                                       [ 60%]
tests/unit/test_safety_reject_changes.py ............................... [ 67%]
.................................................                        [ 77%]
tests/unit/test_safety_review.py ..........                              [ 80%]
tests/unit/test_safety_submit.py ....................................... [ 88%]
...................................................                      [ 99%]
tests/unit/test_startup_warning.py ..                                    [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name               Stmts   Miss Branch BrPart  Cover   Missing
--------------------------------------------------------------
app/__init__.py       28      0      8      0   100%
app/clients.py       178      0     52      0   100%
app/readiness.py      53      0     18      0   100%
app/routes.py        649      0    236      0   100%
--------------------------------------------------------------
TOTAL                908      0    314      0   100%
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================= 462 passed in 3.36s ==============================
Using CPython 3.12.14
Creating virtual environment at: .venv
Installed 17 packages in 21ms
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/user-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 8 items

tests/unit/test_users.py ........                                        [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name              Stmts   Miss Branch BrPart  Cover   Missing
-------------------------------------------------------------
app/__init__.py      48      1     10      1    97%   28->31, 43
app/models.py        30      0      6      0   100%
-------------------------------------------------------------
TOTAL                78      1     16      1    98%
Required test coverage of 97.0% reached. Total coverage: 97.87%
============================== 8 passed in 2.97s ===============================
Using CPython 3.12.14
Creating virtual environment at: .venv
Installed 17 packages in 11ms
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/venue-availability-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 448 items / 1 deselected / 447 selected

tests/unit/test_availability_submission.py ............................. [  6%]
.........................                                                [ 12%]
tests/unit/test_bookings.py .................................            [ 19%]
tests/unit/test_calendar.py ............................................ [ 29%]
...................................                                      [ 37%]
tests/unit/test_calendar_sql.py ..................                       [ 41%]
tests/unit/test_closure_confirmation.py ....................             [ 45%]
tests/unit/test_closure_rejections.py ...........                        [ 48%]
tests/unit/test_dated_closure_reads.py ................................. [ 55%]
................................                                         [ 62%]
tests/unit/test_holds.py .........................                       [ 68%]
tests/unit/test_legacy_buffer_conflicts.py .............                 [ 71%]
tests/unit/test_notification_scrum173.py ...................             [ 75%]
tests/unit/test_temporary_closures.py .................................. [ 82%]
......................................                                   [ 91%]
tests/unit/test_window.py ....................                           [ 95%]
tests/unit/test_write_regressions.py ..................                  [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                      Stmts   Miss Branch BrPart    Cover   Missing
-----------------------------------------------------------------------
app/__init__.py             309      0    118      0  100.00%
app/calendar.py              12      0      4      0  100.00%
app/closure_contract.py      62      0     26      0  100.00%
app/closure_store.py         87      0     10      0  100.00%
app/closures.py              74      0     28      0  100.00%
app/models.py               292      0     76      0  100.00%
app/outbox.py                91      0     36      0  100.00%
-----------------------------------------------------------------------
TOTAL                       927      0    298      0  100.00%
Required test coverage of 100.0% reached. Total coverage: 100.00%
====================== 447 passed, 1 deselected in 9.35s =======================
Using CPython 3.12.14
Creating virtual environment at: .venv
Installed 23 packages in 33ms
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/venue-booking-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 335 items / 1 deselected / 334 selected

tests/unit/test_availability_submission.py ............................. [  8%]
..............                                                           [ 12%]
tests/unit/test_booking_management_clients.py .........                  [ 15%]
tests/unit/test_booking_requests.py .................................... [ 26%]
...........................                                              [ 34%]
tests/unit/test_closure_confirmation.py ...................              [ 40%]
tests/unit/test_closure_rejections.py ....                               [ 41%]
tests/unit/test_dated_closure_search.py ................................ [ 50%]
........                                                                 [ 53%]
tests/unit/test_legacy_buffer_conflicts.py .............                 [ 57%]
tests/unit/test_notification_scrum173.py ................                [ 61%]
tests/unit/test_temporary_closures.py .................................. [ 72%]
.....................................................                    [ 88%]
tests/unit/test_venue_search.py ........................................ [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                      Stmts   Miss Branch BrPart  Cover   Missing
---------------------------------------------------------------------
app/__init__.py              27      0      6      0   100%
app/clients.py              115      0     26      0   100%
app/closure_clients.py       70      0     30      0   100%
app/closure_contract.py      58      0     26      0   100%
app/closures.py              54      0     16      0   100%
app/dispatcher.py           104      0     20      0   100%
app/routes.py               331      0     86      0   100%
app/search.py               137      0     52      0   100%
---------------------------------------------------------------------
TOTAL                       896      0    262      0   100%
Required test coverage of 100.0% reached. Total coverage: 100.00%
====================== 334 passed, 1 deselected in 5.18s =======================
Using CPython 3.12.14
Creating virtual environment at: .venv
Installed 17 packages in 14ms
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/venue-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 96 items

tests/unit/test_add_venue.py .................                           [ 17%]
tests/unit/test_edit_venue.py ........................                   [ 42%]
tests/unit/test_seed_data.py ...........                                 [ 54%]
tests/unit/test_venue_buffer_times.py ........                           [ 62%]
tests/unit/test_venue_details.py ..............                          [ 77%]
tests/unit/test_venue_search_filters.py ......................           [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                Stmts   Miss Branch BrPart  Cover   Missing
---------------------------------------------------------------
app/__init__.py       126      9     30      1    92%   80->83, 119-121, 142-143, 226-233
app/models.py          66      0     22      0   100%
app/validation.py      39      2     28      2    94%   25, 34
---------------------------------------------------------------
TOTAL                 231     11     80      3    95%
Required test coverage of 94.0% reached. Total coverage: 94.86%
============================== 96 passed in 3.02s ==============================
```

## TDD discipline correction

The approval-only legacy guard was initially copied with the successful intent implementation without its own observed RED. Removed that untested branch completely and restarted DR5 from the already-written HTTP diagnostic test before reintroducing it. Existing generic no-op, transaction-failure and frozen-retry behavior remained regression coverage, not claimed as new RED.

## RED 6 — ownerless approval diagnosis

`services/event-service`: `uv run pytest tests/unit/test_approval_notifications.py -k ownerless --no-cov --tb=short`; exit 1.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1
collected 17 items / 15 deselected / 2 selected

tests/unit/test_approval_notifications.py FF                             [100%]

=================================== FAILURES ===================================
___ test_ownerless_approval_is_diagnosed_without_guessing_recipient[approve] ___
tests/unit/test_approval_notifications.py:69: in test_ownerless_approval_is_diagnosed_without_guessing_recipient
    assert "missing organiser" in caplog.text
E   AssertionError: assert 'missing organiser' in ''
E    +  where '' = <_pytest.logging.LogCaptureFixture object at 0x1180b35f0>.text
__ test_ownerless_approval_is_diagnosed_without_guessing_recipient[progress] ___
tests/unit/test_approval_notifications.py:69: in test_ownerless_approval_is_diagnosed_without_guessing_recipient
    assert "missing organiser" in caplog.text
E   AssertionError: assert 'missing organiser' in ''
E    +  where '' = <_pytest.logging.LogCaptureFixture object at 0x1181a4050>.text
=========================== short test summary info ============================
FAILED tests/unit/test_approval_notifications.py::test_ownerless_approval_is_diagnosed_without_guessing_recipient[approve]
FAILED tests/unit/test_approval_notifications.py::test_ownerless_approval_is_diagnosed_without_guessing_recipient[progress]
======================= 2 failed, 15 deselected in 0.37s =======================
```

## GREEN 6 — ownerless approvals remain actionable without delivery

`services/event-service`: `uv run pytest tests/unit/test_approval_notifications.py -k ownerless --no-cov`; exit 0.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-service
configfile: pyproject.toml
plugins: cov-7.1.0, socket-0.8.1
collected 17 items / 15 deselected / 2 selected

tests/unit/test_approval_notifications.py ..                             [100%]

======================= 2 passed, 15 deselected in 0.24s =======================
```

## Review correction: shared helper extraction

The first guarded overwrite of the rejection test was refused by the file tool (the new helper existed but the old module-local fixture still shadowed it). Review caught the duplicate harness; read the exact target and completed the extraction. Rejection assertions remain unchanged. Final integration rerun below exercises both slices using the one shared fixture.

## Regression before targeted extraction succeeded — second guarded overwrite still refused

`services/event-workflow-service`: `uv run --with psycopg2-binary python -m pytest -m integration --no-cov --tb=short --basetemp=../../.scratch/ticket02-final-integration`; exit 0.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-workflow-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 85 items / 77 deselected / 8 selected

tests/integration/test_approval_delivery.py ....                         [ 50%]
tests/integration/test_rejection_delivery.py ....                        [100%]

================= 8 passed, 77 deselected in 104.34s (0:01:44) =================
```

## Final actual shared-harness integration (after successful targeted extraction)

`services/event-workflow-service`: `uv run --with psycopg2-binary python -m pytest -m integration --no-cov --tb=short --basetemp=../../.scratch/ticket02-post-extraction`; exit 0.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-workflow-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 85 items / 77 deselected / 8 selected

tests/integration/test_approval_delivery.py ....                         [ 50%]
tests/integration/test_rejection_delivery.py ....                        [100%]

================= 8 passed, 77 deselected in 131.83s (0:02:11) =================
```

## Final Event full suite with raised coverage floor

`services/event-service`: `uv run pytest`; exit 0.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 507 items

tests/test_event_summaries.py .....................                      [  4%]
tests/test_registration_events.py ..                                     [  4%]
tests/unit/test_approval_notifications.py .................              [  7%]
tests/unit/test_clarification.py ...............................         [ 14%]
tests/unit/test_event_details.py .....................                   [ 18%]
tests/unit/test_event_details_recheck.py ............................... [ 24%]
..............................................................           [ 36%]
tests/unit/test_event_details_workflow.py ..........                     [ 38%]
tests/unit/test_event_list.py ...........................                [ 43%]
tests/unit/test_event_progress.py .............................          [ 49%]
tests/unit/test_notification_context.py ..                               [ 49%]
tests/unit/test_rejection_notifications.py ............................. [ 55%]
                                                                         [ 55%]
tests/unit/test_safety_approve_status.py ......................          [ 59%]
tests/unit/test_safety_gate.py ................................          [ 66%]
tests/unit/test_safety_reject_changes_status.py ........................ [ 71%]
............                                                             [ 73%]
tests/unit/test_safety_status_access.py .........                        [ 75%]
tests/unit/test_safety_submit_status.py ................................ [ 81%]
..                                                                       [ 81%]
tests/unit/test_submission.py .......................................... [ 90%]
..................................................                       [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                Stmts   Miss Branch BrPart   Cover   Missing
----------------------------------------------------------------
app/__init__.py       476      9    150      5  97.76%   126->129, 383-384, 392, 638->673, 724, 820-821, 827, 835, 845
app/models.py         481      1    156      2  99.53%   774->777, 1388
app/outbox.py          89      0     36      0 100.00%
app/validation.py      23      0     12      0 100.00%
----------------------------------------------------------------
TOTAL                1069     10    354      7  98.81%
FAIL Required test coverage of 98.81% not reached. Total coverage: 98.81%
============================= 507 passed in 29.66s =============================
```

## Coverage ratchet correction

Coverage JSON reports 98.80534082923401%, displayed as 98.81%. pytest-cov compares the unrounded value, so 98.81 caused a threshold-only failure despite 507 passing tests. Set the floor to 98.80 (raised from 98.79), the highest passing two-decimal floor. Existing uncovered lines/branches are inherited, not new approval logic.

## Final passing Event suite and corrected coverage ratchet

`services/event-service`: `uv run pytest`; exit 0.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 507 items

tests/test_event_summaries.py .....................                      [  4%]
tests/test_registration_events.py ..                                     [  4%]
tests/unit/test_approval_notifications.py .................              [  7%]
tests/unit/test_clarification.py ...............................         [ 14%]
tests/unit/test_event_details.py .....................                   [ 18%]
tests/unit/test_event_details_recheck.py ............................... [ 24%]
..............................................................           [ 36%]
tests/unit/test_event_details_workflow.py ..........                     [ 38%]
tests/unit/test_event_list.py ...........................                [ 43%]
tests/unit/test_event_progress.py .............................          [ 49%]
tests/unit/test_notification_context.py ..                               [ 49%]
tests/unit/test_rejection_notifications.py ............................. [ 55%]
                                                                         [ 55%]
tests/unit/test_safety_approve_status.py ......................          [ 59%]
tests/unit/test_safety_gate.py ................................          [ 66%]
tests/unit/test_safety_reject_changes_status.py ........................ [ 71%]
............                                                             [ 73%]
tests/unit/test_safety_status_access.py .........                        [ 75%]
tests/unit/test_safety_submit_status.py ................................ [ 81%]
..                                                                       [ 81%]
tests/unit/test_submission.py .......................................... [ 90%]
..................................................                       [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                Stmts   Miss Branch BrPart   Cover   Missing
----------------------------------------------------------------
app/__init__.py       476      9    150      5  97.76%   126->129, 383-384, 392, 638->673, 724, 820-821, 827, 835, 845
app/models.py         481      1    156      2  99.53%   774->777, 1388
app/outbox.py          89      0     36      0 100.00%
app/validation.py      23      0     12      0 100.00%
----------------------------------------------------------------
TOTAL                1069     10    354      7  98.81%
Required test coverage of 98.8% reached. Total coverage: 98.81%
============================= 507 passed in 3.53s ==============================
```

## Final Event Workflow unit suite after shared fixture extraction

`services/event-workflow-service`: `uv run pytest`; exit 0.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-workflow-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 85 items / 8 deselected / 77 selected

tests/unit/test_approval_notifications.py ..                             [  2%]
tests/unit/test_checks.py ........................                       [ 33%]
tests/unit/test_clients.py ..............                                [ 51%]
tests/unit/test_rejection_notifications.py ...........                   [ 66%]
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
======================= 77 passed, 8 deselected in 0.34s =======================
```

## Final full backend rerun after coverage ratchet and completed extraction

``: `npm run test:backend`; exit 0.

```text
> is212-g7t4@0.0.0 test:backend
> for d in services/*/; do (cd "$d" && uv run pytest) || exit 1; done

============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/_template-atomic-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 1 item

tests/unit/test_health.py .                                              [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name              Stmts   Miss Branch BrPart  Cover   Missing
-------------------------------------------------------------
app/__init__.py       6      0      0      0   100%
app/models.py         0      0      0      0   100%
app/routes.py         5      0      0      0   100%
-------------------------------------------------------------
TOTAL                11      0      0      0   100%
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================== 1 passed in 0.14s ===============================
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/_template-composite-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 1 item

tests/unit/test_health.py .                                              [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name              Stmts   Miss Branch BrPart  Cover   Missing
-------------------------------------------------------------
app/__init__.py       6      0      0      0   100%
app/clients.py        7      7      0      0     0%   1-15
app/routes.py         5      0      0      0   100%
-------------------------------------------------------------
TOTAL                18      7      0      0    61%
Required test coverage of 61.0% reached. Total coverage: 61.11%
============================== 1 passed in 0.12s ===============================
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/attendee-registration-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 34 items

tests/unit/test_clients.py .........                                     [ 26%]
tests/unit/test_routes.py ......................                         [ 91%]
tests/unit/test_validation.py ...                                        [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                Stmts   Miss Branch BrPart  Cover   Missing
---------------------------------------------------------------
app/__init__.py        25      0      6      1    97%   20->23
app/clients.py         37      0      4      0   100%
app/routes.py          66      0     10      0   100%
app/validation.py      20      1      8      1    93%   33
---------------------------------------------------------------
TOTAL                 148      1     28      2    98%
Required test coverage of 98.0% reached. Total coverage: 98.30%
============================== 34 passed in 0.22s ==============================
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/coordinator-assignment-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 37 items

tests/unit/test_clients.py ......                                        [ 16%]
tests/unit/test_health.py ...............................                [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name              Stmts   Miss Branch BrPart  Cover   Missing
-------------------------------------------------------------
app/__init__.py      24      5      6      3    73%   17->20, 21-24, 26
app/clients.py       30      5      4      0    79%   32-36
app/routes.py        93      6     24      1    94%   21, 39-40, 156, 211-212
-------------------------------------------------------------
TOTAL               147     16     34      4    88%
Required test coverage of 87.0% reached. Total coverage: 87.85%
============================== 37 passed in 0.23s ==============================
============================= test session starts ==============================
platform darwin -- Python 3.13.9, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/equipment-request-service
configfile: pyproject.toml
plugins: cov-7.1.0
collected 76 items

tests/test_equipment_requests.py ....................................... [ 51%]
.....................................                                    [100%]

============================== 76 passed in 0.26s ==============================
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/equipment-reservation-service
configfile: pyproject.toml
plugins: cov-7.1.0, anyio-4.15.1
collected 110 items

tests/test_availability.py ........                                      [  7%]
tests/test_clients.py ..................                                 [ 23%]
tests/test_health.py .                                                   [ 24%]
tests/test_reservations_api.py ......................................... [ 61%]
..........................................                               [100%]

============================= 110 passed in 0.18s ==============================
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/equipment-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 53 items

tests/unit/test_equipment_api.py ...........................             [ 50%]
tests/unit/test_equipment_classes.py .............                       [ 75%]
tests/unit/test_seed_data.py .............                               [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name               Stmts   Miss Branch BrPart  Cover   Missing
--------------------------------------------------------------
app/__init__.py       87      0     32      1    99%   65->68
app/equipment.py      42      0      0      0   100%
app/models.py         21      0      2      0   100%
--------------------------------------------------------------
TOTAL                150      0     34      1    99%
Required test coverage of 99.0% reached. Total coverage: 99.46%
============================== 53 passed in 0.24s ==============================
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 507 items

tests/test_event_summaries.py .....................                      [  4%]
tests/test_registration_events.py ..                                     [  4%]
tests/unit/test_approval_notifications.py .................              [  7%]
tests/unit/test_clarification.py ...............................         [ 14%]
tests/unit/test_event_details.py .....................                   [ 18%]
tests/unit/test_event_details_recheck.py ............................... [ 24%]
..............................................................           [ 36%]
tests/unit/test_event_details_workflow.py ..........                     [ 38%]
tests/unit/test_event_list.py ...........................                [ 43%]
tests/unit/test_event_progress.py .............................          [ 49%]
tests/unit/test_notification_context.py ..                               [ 49%]
tests/unit/test_rejection_notifications.py ............................. [ 55%]
                                                                         [ 55%]
tests/unit/test_safety_approve_status.py ......................          [ 59%]
tests/unit/test_safety_gate.py ................................          [ 66%]
tests/unit/test_safety_reject_changes_status.py ........................ [ 71%]
............                                                             [ 73%]
tests/unit/test_safety_status_access.py .........                        [ 75%]
tests/unit/test_safety_submit_status.py ................................ [ 81%]
..                                                                       [ 81%]
tests/unit/test_submission.py .......................................... [ 90%]
..................................................                       [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                Stmts   Miss Branch BrPart   Cover   Missing
----------------------------------------------------------------
app/__init__.py       476      9    150      5  97.76%   126->129, 383-384, 392, 638->673, 724, 820-821, 827, 835, 845
app/models.py         481      1    156      2  99.53%   774->777, 1388
app/outbox.py          89      0     36      0 100.00%
app/validation.py      23      0     12      0 100.00%
----------------------------------------------------------------
TOTAL                1069     10    354      7  98.81%
Required test coverage of 98.8% reached. Total coverage: 98.81%
============================= 507 passed in 3.19s ==============================
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/event-workflow-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 85 items / 8 deselected / 77 selected

tests/unit/test_approval_notifications.py ..                             [  2%]
tests/unit/test_checks.py ........................                       [ 33%]
tests/unit/test_clients.py ..............                                [ 51%]
tests/unit/test_rejection_notifications.py ...........                   [ 66%]
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
======================= 77 passed, 8 deselected in 0.28s =======================
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.7.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/notification-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 91 items

tests/unit/test_approval_notifications.py .....                          [  5%]
tests/unit/test_event_notifications.py .....                             [ 10%]
tests/unit/test_notification_scrum173.py ............................... [ 45%]
..................................................                       [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                 Stmts   Miss Branch BrPart    Cover   Missing
------------------------------------------------------------------
app/__init__.py         51      0     16      0  100.00%
app/consumer.py        123      0     62      0  100.00%
app/diagnostics.py      32      0      6      0  100.00%
app/store.py            61      0      8      0  100.00%
------------------------------------------------------------------
TOTAL                  267      0     92      0  100.00%
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================== 91 passed in 0.36s ==============================
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/registration-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 38 items

tests/unit/test_registrations.py ......................................  [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name              Stmts   Miss Branch BrPart  Cover   Missing
-------------------------------------------------------------
app/__init__.py      87      1     22      1    98%   35->38, 50
app/models.py        48      0      6      0   100%
-------------------------------------------------------------
TOTAL               135      1     28      1    99%
Required test coverage of 98.0% reached. Total coverage: 98.77%
============================== 38 passed in 0.26s ==============================
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/safety-check-record-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 149 items

tests/unit/test_health.py .                                              [  0%]
tests/unit/test_safety_decision.py ........................              [ 16%]
tests/unit/test_safety_reject_changes.py ..............................  [ 36%]
tests/unit/test_safety_rounds.py ....................................... [ 63%]
........                                                                 [ 68%]
tests/unit/test_safety_withdrawal.py ................................... [ 91%]
............                                                             [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name              Stmts   Miss Branch BrPart  Cover   Missing
-------------------------------------------------------------
app/__init__.py     260      0    116      0   100%
app/models.py       154      0     40      0   100%
-------------------------------------------------------------
TOTAL               414      0    156      0   100%
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================= 149 passed in 0.71s ==============================
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/safety-check-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 462 items

tests/unit/test_clients.py ............................................. [  9%]
...................................                                      [ 17%]
tests/unit/test_safety_approve.py ...................................... [ 25%]
..........                                                               [ 27%]
tests/unit/test_safety_feedback.py ...........                           [ 30%]
tests/unit/test_safety_queue.py .......................................  [ 38%]
tests/unit/test_safety_readiness.py ..............................       [ 45%]
tests/unit/test_safety_recheck.py ...................................... [ 53%]
..................................                                       [ 60%]
tests/unit/test_safety_reject_changes.py ............................... [ 67%]
.................................................                        [ 77%]
tests/unit/test_safety_review.py ..........                              [ 80%]
tests/unit/test_safety_submit.py ....................................... [ 88%]
...................................................                      [ 99%]
tests/unit/test_startup_warning.py ..                                    [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name               Stmts   Miss Branch BrPart  Cover   Missing
--------------------------------------------------------------
app/__init__.py       28      0      8      0   100%
app/clients.py       178      0     52      0   100%
app/readiness.py      53      0     18      0   100%
app/routes.py        649      0    236      0   100%
--------------------------------------------------------------
TOTAL                908      0    314      0   100%
Required test coverage of 100.0% reached. Total coverage: 100.00%
============================= 462 passed in 1.38s ==============================
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/user-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 8 items

tests/unit/test_users.py ........                                        [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name              Stmts   Miss Branch BrPart  Cover   Missing
-------------------------------------------------------------
app/__init__.py      48      1     10      1    97%   28->31, 43
app/models.py        30      0      6      0   100%
-------------------------------------------------------------
TOTAL                78      1     16      1    98%
Required test coverage of 97.0% reached. Total coverage: 97.87%
============================== 8 passed in 0.18s ===============================
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/venue-availability-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 448 items / 1 deselected / 447 selected

tests/unit/test_availability_submission.py ............................. [  6%]
.........................                                                [ 12%]
tests/unit/test_bookings.py .................................            [ 19%]
tests/unit/test_calendar.py ............................................ [ 29%]
...................................                                      [ 37%]
tests/unit/test_calendar_sql.py ..................                       [ 41%]
tests/unit/test_closure_confirmation.py ....................             [ 45%]
tests/unit/test_closure_rejections.py ...........                        [ 48%]
tests/unit/test_dated_closure_reads.py ................................. [ 55%]
................................                                         [ 62%]
tests/unit/test_holds.py .........................                       [ 68%]
tests/unit/test_legacy_buffer_conflicts.py .............                 [ 71%]
tests/unit/test_notification_scrum173.py ...................             [ 75%]
tests/unit/test_temporary_closures.py .................................. [ 82%]
......................................                                   [ 91%]
tests/unit/test_window.py ....................                           [ 95%]
tests/unit/test_write_regressions.py ..................                  [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                      Stmts   Miss Branch BrPart    Cover   Missing
-----------------------------------------------------------------------
app/__init__.py             309      0    118      0  100.00%
app/calendar.py              12      0      4      0  100.00%
app/closure_contract.py      62      0     26      0  100.00%
app/closure_store.py         87      0     10      0  100.00%
app/closures.py              74      0     28      0  100.00%
app/models.py               292      0     76      0  100.00%
app/outbox.py                91      0     36      0  100.00%
-----------------------------------------------------------------------
TOTAL                       927      0    298      0  100.00%
Required test coverage of 100.0% reached. Total coverage: 100.00%
====================== 447 passed, 1 deselected in 2.35s =======================
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/venue-booking-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1, anyio-4.15.1
collected 335 items / 1 deselected / 334 selected

tests/unit/test_availability_submission.py ............................. [  8%]
..............                                                           [ 12%]
tests/unit/test_booking_management_clients.py .........                  [ 15%]
tests/unit/test_booking_requests.py .................................... [ 26%]
...........................                                              [ 34%]
tests/unit/test_closure_confirmation.py ...................              [ 40%]
tests/unit/test_closure_rejections.py ....                               [ 41%]
tests/unit/test_dated_closure_search.py ................................ [ 50%]
........                                                                 [ 53%]
tests/unit/test_legacy_buffer_conflicts.py .............                 [ 57%]
tests/unit/test_notification_scrum173.py ................                [ 61%]
tests/unit/test_temporary_closures.py .................................. [ 72%]
.....................................................                    [ 88%]
tests/unit/test_venue_search.py ........................................ [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                      Stmts   Miss Branch BrPart  Cover   Missing
---------------------------------------------------------------------
app/__init__.py              27      0      6      0   100%
app/clients.py              115      0     26      0   100%
app/closure_clients.py       70      0     30      0   100%
app/closure_contract.py      58      0     26      0   100%
app/closures.py              54      0     16      0   100%
app/dispatcher.py           104      0     20      0   100%
app/routes.py               331      0     86      0   100%
app/search.py               137      0     52      0   100%
---------------------------------------------------------------------
TOTAL                       896      0    262      0   100%
Required test coverage of 100.0% reached. Total coverage: 100.00%
====================== 334 passed, 1 deselected in 2.57s =======================
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-02/services/venue-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 96 items

tests/unit/test_add_venue.py .................                           [ 17%]
tests/unit/test_edit_venue.py ........................                   [ 42%]
tests/unit/test_seed_data.py ...........                                 [ 54%]
tests/unit/test_venue_buffer_times.py ........                           [ 62%]
tests/unit/test_venue_details.py ..............                          [ 77%]
tests/unit/test_venue_search_filters.py ......................           [100%]

================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.14-final-0 _______________

Name                Stmts   Miss Branch BrPart  Cover   Missing
---------------------------------------------------------------
app/__init__.py       126      9     30      1    92%   80->83, 119-121, 142-143, 226-233
app/models.py          66      0     22      0   100%
app/validation.py      39      2     28      2    94%   25, 34
---------------------------------------------------------------
TOTAL                 231     11     80      3    95%
Required test coverage of 94.0% reached. Total coverage: 94.86%
============================== 96 passed in 0.43s ==============================
```
