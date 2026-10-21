# SCRUM-45 ticket 03 — initial coordinator assignment evidence

Scope: AC4 **initial** assignment only. Reassignment remains ticket 04.
Approved seams: Event mutation/outbox HTTP, worker/consumer, isolated real
PostgreSQL + RabbitMQ + real User HTTP + inbox API. Browser is a separate mocked
journey. Baseline ce20a76; start merge fast-forwarded integration to f9b02df.
No remote database, production credentials, sibling worktree modifications,
push or ticket closure.

## Executed TDD cycles

Focused commands used `uv run pytest <feature-module> --no-cov -q` in the owning
service. Focused `--no-cov` avoids interpreting partial-suite coverage as a gate;
full suites below retain the configured floors. Real integration command:
`uv run --with psycopg2-binary python -m pytest tests/integration/test_initial_assignment_delivery.py -m integration --no-cov -q --basetemp=/Users/daphnetok/.hermes/cache/scratch/scrum45-ticket03-pytest`.

The first assignment test initially addressed the wrong route (404); corrected
the fixture to the existing `PATCH /events/<id>` / `assignedCoordinatorId`
contract before counting its assertion RED below. A hold SQL-write filter also
initially counted `SELECT ... FOR UPDATE`; corrected it to SQL starting with
`UPDATE` before recording GREEN. An initial bare `uv run --with ... pytest`
failed to import the overlay's psycopg2; reran using `python -m pytest`. These
setup/test errors are not product RED evidence. Existing retry, freeze, auth and
rollback regression checks were added after their tracer cycle; passing existing
behavior is not claimed as new RED.

## Event initial intent RED

```text
F                                                                        [100%]
=================================== FAILURES ===================================
__ test_initial_assignment_saves_historical_notification_on_same_transaction ___

boundary = (<FlaskClient <Flask 'app'>>, <MagicMock id='4374864016'>, <MagicMock name='mock.cursor().__enter__()' id='4377404832'>)

    def test_initial_assignment_saves_historical_notification_on_same_transaction(boundary):
        """AC4/DR2/DR4: assign via HTTP with DB driver mocked; observe intent
        storing assigned ID, event name and submitting organiser before commit.
        """
        client, connection, cursor = boundary
        cursor.fetchone.side_effect = [dict(coordinator_id=None, status="Submitted"), assigned_row()]
        response = assign(client)
        assert response.status_code == 200, response.json
        saved = intents(cursor)
>       assert len(saved) == 1, "Initial assignment must persist notification intent"
E       AssertionError: Initial assignment must persist notification intent
E       assert 0 == 1
E        +  where 0 = len([])

tests/unit/test_initial_assignment_notifications.py:51: AssertionError
=========================== short test summary info ============================
FAILED tests/unit/test_initial_assignment_notifications.py::test_initial_assignment_saves_historical_notification_on_same_transaction
1 failed in 0.09s
```

## Event initial intent GREEN

```text
.                                                                        [100%]
1 passed in 0.08s
```

## Legacy RED

```text
.F                                                                       [100%]
=================================== FAILURES ===================================
_ test_legacy_assignment_diagnoses_missing_organiser_without_guessing_recipient _

boundary = (<FlaskClient <Flask 'app'>>, <MagicMock id='4357381856'>, <MagicMock name='mock.cursor().__enter__()' id='4359396368'>)
caplog = <_pytest.logging.LogCaptureFixture object at 0x103d92090>

    def test_legacy_assignment_diagnoses_missing_organiser_without_guessing_recipient(boundary, caplog):
        """DR5: assign legacy ownerless event via HTTP; action succeeds with a
        diagnostic but no publishable intent or guessed recipient.
        """
        client, _, cursor = boundary
        cursor.fetchone.side_effect = [dict(coordinator_id=None, status="Submitted"), assigned_row(None)]
        assert assign(client).status_code == 200
>       assert "missing organiser" in caplog.text
E       AssertionError: assert 'missing organiser' in ''
E        +  where '' = <_pytest.logging.LogCaptureFixture object at 0x103d92090>.text

tests/unit/test_initial_assignment_notifications.py:65: AssertionError
=========================== short test summary info ============================
FAILED tests/unit/test_initial_assignment_notifications.py::test_legacy_assignment_diagnoses_missing_organiser_without_guessing_recipient
1 failed, 1 passed in 0.08s
```

## Legacy GREEN

```text
..                                                                       [100%]
2 passed in 0.11s
```

## Worker lookup RED

```text
F                                                                        [100%]
=================================== FAILURES ===================================
_ test_worker_resolves_saved_id_using_user_username_and_freezes_before_publish _

api = <app.dispatcher.OutboxAPI object at 0x1067cbcb0>

    def test_worker_resolves_saved_id_using_user_username_and_freezes_before_publish(api):
        """AC4/DR4: exercise worker with HTTP transport and broker I/O mocked;
        User's actual username field supplies name for saved coordinator ID.
        """
        published = []
        with httpx.Client(transport=httpx.MockTransport(transport)) as client, patch("httpx.request", side_effect=client.request):
            assert dispatch_once(api, published.append) == 1
>       assert len(published) == 1, "Initial assignment must publish after User lookup"
E       AssertionError: Initial assignment must publish after User lookup
E       assert 0 == 1
E        +  where 0 = len([])

tests/unit/test_initial_assignment_notifications.py:43: AssertionError
------------------------------ Captured log call -------------------------------
WARNING  app.dispatcher:dispatcher.py:66 Dispatch retry source=20000000-0000-0000-0000-000000000001 error=KeyError
=========================== short test summary info ============================
FAILED tests/unit/test_initial_assignment_notifications.py::test_worker_resolves_saved_id_using_user_username_and_freezes_before_publish
1 failed in 0.45s
```

## Worker lookup GREEN

```text
.                                                                        [100%]
1 passed in 0.11s
```

## Name hold RED

```text
.FFFFF                                                                   [100%]
=================================== FAILURES ===================================
_ test_unusable_user_is_held_for_repair_without_blocking_other_work[404-body0] _

api = <app.dispatcher.OutboxAPI object at 0x103161700>, status = 404
body = {'message': 'User not found.'}

    @pytest.mark.parametrize("status,body", [(404, {"message": "User not found."}),
        (200, {"username": "   "}), (200, {}), (200, {"username": None}), (200, {"username": 23})])
    def test_unusable_user_is_held_for_repair_without_blocking_other_work(api, status, body):
        """DR6: missing user/blank or unusable username is a diagnosed hold;
        unrelated rejection still publishes. HTTP mocked, not worker behavior.
        """
        good = {**JOB, "id": "20000000-0000-0000-0000-000000000002", "type": "event.rejection",
                "source": {**SOURCE, "reason": "Missing plan", "decision": "Rejected"}}
        calls, published = [], []
        def respond(request):
            calls.append(request)
            if request.method == "GET":
                return httpx.Response(status, json=body)
            if request.url.path.endswith("claim"):
                return httpx.Response(200, json={"jobs": [JOB, good]})
            return transport(request)
        with httpx.Client(transport=httpx.MockTransport(respond)) as client, patch("httpx.request", side_effect=client.request):
            assert dispatch_once(api, published.append) == 2
        held = [request for request in calls if request.url.path.endswith("/hold")]
>       assert len(held) == 1, "Unusable coordinator name must be held, not endlessly retried"
E       AssertionError: Unusable coordinator name must be held, not endlessly retried
E       assert 0 == 1
E        +  where 0 = len([])

tests/unit/test_initial_assignment_notifications.py:70: AssertionError
------------------------------ Captured log call -------------------------------
WARNING  app.dispatcher:dispatcher.py:78 Dispatch retry source=20000000-0000-0000-0000-000000000001 error=HTTPStatusError
_ test_unusable_user_is_held_for_repair_without_blocking_other_work[200-body1] _

api = <app.dispatcher.OutboxAPI object at 0x10345a030>, status = 200
body = {'username': '   '}

    @pytest.mark.parametrize("status,body", [(404, {"message": "User not found."}),
        (200, {"username": "   "}), (200, {}), (200, {"username": None}), (200, {"username": 23})])
    def test_unusable_user_is_held_for_repair_without_blocking_other_work(api, status, body):
        """DR6: missing user/blank or unusable username is a diagnosed hold;
        unrelated rejection still publishes. HTTP mocked, not worker behavior.
        """
        good = {**JOB, "id": "20000000-0000-0000-0000-000000000002", "type": "event.rejection",
                "source": {**SOURCE, "reason": "Missing plan", "decision": "Rejected"}}
        calls, published = [], []
        def respond(request):
            calls.append(request)
            if request.method == "GET":
                return httpx.Response(status, json=body)
            if request.url.path.endswith("claim"):
                return httpx.Response(200, json={"jobs": [JOB, good]})
            return transport(request)
        with httpx.Client(transport=httpx.MockTransport(respond)) as client, patch("httpx.request", side_effect=client.request):
            assert dispatch_once(api, published.append) == 2
        held = [request for request in calls if request.url.path.endswith("/hold")]
>       assert len(held) == 1, "Unusable coordinator name must be held, not endlessly retried"
E       AssertionError: Unusable coordinator name must be held, not endlessly retried
E       assert 0 == 1
E        +  where 0 = len([])

tests/unit/test_initial_assignment_notifications.py:70: AssertionError
_ test_unusable_user_is_held_for_repair_without_blocking_other_work[200-body2] _

api = <app.dispatcher.OutboxAPI object at 0x10348ae70>, status = 200, body = {}

    @pytest.mark.parametrize("status,body", [(404, {"message": "User not found."}),
        (200, {"username": "   "}), (200, {}), (200, {"username": None}), (200, {"username": 23})])
    def test_unusable_user_is_held_for_repair_without_blocking_other_work(api, status, body):
        """DR6: missing user/blank or unusable username is a diagnosed hold;
        unrelated rejection still publishes. HTTP mocked, not worker behavior.
        """
        good = {**JOB, "id": "20000000-0000-0000-0000-000000000002", "type": "event.rejection",
                "source": {**SOURCE, "reason": "Missing plan", "decision": "Rejected"}}
        calls, published = [], []
        def respond(request):
            calls.append(request)
            if request.method == "GET":
                return httpx.Response(status, json=body)
            if request.url.path.endswith("claim"):
                return httpx.Response(200, json={"jobs": [JOB, good]})
            return transport(request)
        with httpx.Client(transport=httpx.MockTransport(respond)) as client, patch("httpx.request", side_effect=client.request):
            assert dispatch_once(api, published.append) == 2
        held = [request for request in calls if request.url.path.endswith("/hold")]
>       assert len(held) == 1, "Unusable coordinator name must be held, not endlessly retried"
E       AssertionError: Unusable coordinator name must be held, not endlessly retried
E       assert 0 == 1
E        +  where 0 = len([])

tests/unit/test_initial_assignment_notifications.py:70: AssertionError
------------------------------ Captured log call -------------------------------
WARNING  app.dispatcher:dispatcher.py:78 Dispatch retry source=20000000-0000-0000-0000-000000000001 error=KeyError
_ test_unusable_user_is_held_for_repair_without_blocking_other_work[200-body3] _

api = <app.dispatcher.OutboxAPI object at 0x10348b680>, status = 200
body = {'username': None}

    @pytest.mark.parametrize("status,body", [(404, {"message": "User not found."}),
        (200, {"username": "   "}), (200, {}), (200, {"username": None}), (200, {"username": 23})])
    def test_unusable_user_is_held_for_repair_without_blocking_other_work(api, status, body):
        """DR6: missing user/blank or unusable username is a diagnosed hold;
        unrelated rejection still publishes. HTTP mocked, not worker behavior.
        """
        good = {**JOB, "id": "20000000-0000-0000-0000-000000000002", "type": "event.rejection",
                "source": {**SOURCE, "reason": "Missing plan", "decision": "Rejected"}}
        calls, published = [], []
        def respond(request):
            calls.append(request)
            if request.method == "GET":
                return httpx.Response(status, json=body)
            if request.url.path.endswith("claim"):
                return httpx.Response(200, json={"jobs": [JOB, good]})
            return transport(request)
        with httpx.Client(transport=httpx.MockTransport(respond)) as client, patch("httpx.request", side_effect=client.request):
            assert dispatch_once(api, published.append) == 2
        held = [request for request in calls if request.url.path.endswith("/hold")]
>       assert len(held) == 1, "Unusable coordinator name must be held, not endlessly retried"
E       AssertionError: Unusable coordinator name must be held, not endlessly retried
E       assert 0 == 1
E        +  where 0 = len([])

tests/unit/test_initial_assignment_notifications.py:70: AssertionError
_ test_unusable_user_is_held_for_repair_without_blocking_other_work[200-body4] _

api = <app.dispatcher.OutboxAPI object at 0x1034cc800>, status = 200
body = {'username': 23}

    @pytest.mark.parametrize("status,body", [(404, {"message": "User not found."}),
        (200, {"username": "   "}), (200, {}), (200, {"username": None}), (200, {"username": 23})])
    def test_unusable_user_is_held_for_repair_without_blocking_other_work(api, status, body):
        """DR6: missing user/blank or unusable username is a diagnosed hold;
        unrelated rejection still publishes. HTTP mocked, not worker behavior.
        """
        good = {**JOB, "id": "20000000-0000-0000-0000-000000000002", "type": "event.rejection",
                "source": {**SOURCE, "reason": "Missing plan", "decision": "Rejected"}}
        calls, published = [], []
        def respond(request):
            calls.append(request)
            if request.method == "GET":
                return httpx.Response(status, json=body)
            if request.url.path.endswith("claim"):
                return httpx.Response(200, json={"jobs": [JOB, good]})
            return transport(request)
        with httpx.Client(transport=httpx.MockTransport(respond)) as client, patch("httpx.request", side_effect=client.request):
            assert dispatch_once(api, published.append) == 2
        held = [request for request in calls if request.url.path.endswith("/hold")]
>       assert len(held) == 1, "Unusable coordinator name must be held, not endlessly retried"
E       AssertionError: Unusable coordinator name must be held, not endlessly retried
E       assert 0 == 1
E        +  where 0 = len([])

tests/unit/test_initial_assignment_notifications.py:70: AssertionError
=========================== short test summary info ============================
FAILED tests/unit/test_initial_assignment_notifications.py::test_unusable_user_is_held_for_repair_without_blocking_other_work[404-body0]
FAILED tests/unit/test_initial_assignment_notifications.py::test_unusable_user_is_held_for_repair_without_blocking_other_work[200-body1]
FAILED tests/unit/test_initial_assignment_notifications.py::test_unusable_user_is_held_for_repair_without_blocking_other_work[200-body2]
FAILED tests/unit/test_initial_assignment_notifications.py::test_unusable_user_is_held_for_repair_without_blocking_other_work[200-body3]
FAILED tests/unit/test_initial_assignment_notifications.py::test_unusable_user_is_held_for_repair_without_blocking_other_work[200-body4]
5 failed, 1 passed in 0.10s
```

## Name hold GREEN

```text
......                                                                   [100%]
6 passed in 0.08s
```

## Assignment claim/freeze RED

```text
.....F                                                                   [100%]
=================================== FAILURES ===================================
__ test_claim_exposes_assignment_type_and_freeze_accepts_named_saved_identity __

boundary = (<FlaskClient <Flask 'app'>>, <MagicMock id='4395438672'>, <MagicMock name='mock.cursor().__enter__()' id='4412498784'>)

    def test_claim_exposes_assignment_type_and_freeze_accepts_named_saved_identity(boundary):
        """AC4/DR4: claim owning HTTP API exposes assignment type; freeze persists
        name while validating historical saved event/recipient/coordinator facts.
        """
        client, _, cursor = boundary
        cursor.fetchall.return_value = [pending()]
        job = client.post("/internal/notification-outbox/claim", headers=HEADERS, json={}).json["jobs"][0]
>       assert job.get("type") == "event.coordinator-assignment"
E       AssertionError: assert None == 'event.coordinator-assignment'
E        +  where None = <built-in method get of dict object at 0x10254f8c0>('type')
E        +    where <built-in method get of dict object at 0x10254f8c0> = {'attempts': 1, 'createdAt': '2026-10-21T00:00:00+00:00', 'envelope': None, 'id': '20000000-0000-0000-0000-000000000001', ...}.get

tests/unit/test_initial_assignment_notifications.py:108: AssertionError
=========================== short test summary info ============================
FAILED tests/unit/test_initial_assignment_notifications.py::test_claim_exposes_assignment_type_and_freeze_accepts_named_saved_identity
1 failed, 5 passed in 0.19s
```

## Assignment claim/freeze GREEN

```text
......                                                                   [100%]
6 passed in 0.12s
```

## Durable hold RED

```text
......F                                                                  [100%]
=================================== FAILURES ===================================
_______ test_name_hold_releases_lease_and_excludes_held_work_from_claims _______

boundary = (<FlaskClient <Flask 'app'>>, <MagicMock id='4387985440'>, <MagicMock name='mock.cursor().__enter__()' id='4387443472'>)

    def test_name_hold_releases_lease_and_excludes_held_work_from_claims(boundary):
        """DR6: owning HTTP hold records durable diagnosis without retry schedule;
        claim boundary excludes held jobs so unrelated work remains eligible.
        """
        client, _, cursor = boundary
        cursor.fetchone.return_value = pending()
        response = client.post(f"/internal/notification-outbox/{JOB_ID}/hold", headers=HEADERS,
            json=dict(leaseToken=LEASE, error=f"CoordinatorNameUnavailable coordinatorId={COORDINATOR}"))
>       assert response.status_code == 200
E       assert 404 == 200
E        +  where 404 = <WrapperTestResponse streamed [404 NOT FOUND]>.status_code

tests/unit/test_initial_assignment_notifications.py:129: AssertionError
=========================== short test summary info ============================
FAILED tests/unit/test_initial_assignment_notifications.py::test_name_hold_releases_lease_and_excludes_held_work_from_claims
1 failed, 6 passed in 0.12s
```

## Durable hold GREEN (corrected SQL write filter)

```text
.                                                                        [100%]
1 passed in 0.11s
```

## Hold inspection/release RED

```text
......FF                                                                 [100%]
=================================== FAILURES ===================================
_______ test_name_hold_releases_lease_and_excludes_held_work_from_claims _______

boundary = (<FlaskClient <Flask 'app'>>, <MagicMock id='4426897440'>, <MagicMock name='mock.cursor().__enter__()' id='4426896000'>)

    def test_name_hold_releases_lease_and_excludes_held_work_from_claims(boundary):
        """DR6: owning HTTP hold records durable diagnosis without retry schedule;
        claim boundary excludes held jobs so unrelated work remains eligible.
        """
        client, _, cursor = boundary
        cursor.fetchone.return_value = pending()
        response = client.post(f"/internal/notification-outbox/{JOB_ID}/hold", headers=HEADERS,
            json=dict(leaseToken=LEASE, error=f"CoordinatorNameUnavailable coordinatorId={COORDINATOR}"))
        assert response.status_code == 200
        writes = [call for call in cursor.execute.call_args_list if "UPDATE" in call.args[0]]
>       assert len(writes) == 1
E       assert 2 == 1
E        +  where 2 = len([call('WITH locked AS MATERIALIZED (SELECT * FROM public."EventNotificationOutbox" WHERE source_id=%s AND lease_token=...ordinatorNameUnavailable coordinatorId=10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000001'))])

tests/unit/test_initial_assignment_notifications.py:131: AssertionError
________ test_held_work_can_be_inspected_and_released_after_name_repair ________

boundary = (<FlaskClient <Flask 'app'>>, <MagicMock id='4427258944'>, <MagicMock name='mock.cursor().__enter__()' id='4427899984'>)

    def test_held_work_can_be_inspected_and_released_after_name_repair(boundary):
        """DR6: authenticated operator reads held source/diagnosis and explicitly
        releases it for retry after repairing User data; no event rewrite needed.
        """
        client, _, cursor = boundary
        held_at = datetime(2026, 10, 21, tzinfo=UTC)
        cursor.fetchall.return_value = [{**pending(), "held_at": held_at, "last_error": "CoordinatorNameUnavailable"}]
        response = client.get("/internal/notification-outbox/held", headers=HEADERS)
>       assert response.status_code == 200
E       assert 404 == 200
E        +  where 404 = <WrapperTestResponse streamed [404 NOT FOUND]>.status_code

tests/unit/test_initial_assignment_notifications.py:148: AssertionError
=========================== short test summary info ============================
FAILED tests/unit/test_initial_assignment_notifications.py::test_name_hold_releases_lease_and_excludes_held_work_from_claims
FAILED tests/unit/test_initial_assignment_notifications.py::test_held_work_can_be_inspected_and_released_after_name_repair
2 failed, 6 passed in 0.12s
```

## Hold inspection/release GREEN

```text
........                                                                 [100%]
8 passed in 0.09s
```

## Real assignment integration RED

```text
F                                                                        [100%]
=================================== FAILURES ===================================
__ test_real_initial_assignment_delivers_username_event_link_and_deduplicates __

system = {'http': <function system.<locals>.http at 0x106d3d080>, 'sql': <function system.<locals>.sql at 0x106d3d800>, 'worker': <function system.<locals>.worker at 0x106d3d260>, 'start': <function system.<locals>.start at 0x106d3e7a0>, ...}

    def test_real_initial_assignment_delivers_username_event_link_and_deduplicates(system):
        """AC4/DR3/DR4: real assignment -> owner DB -> HTTP worker -> real User
        lookup -> RabbitMQ -> consumer -> inbox API; replay yields one inbox item.
        """
        s = system
        initial_event(s)
        user = s["http"]("user-service", "GET", f"/users/{ACTOR}")
        assert user.status_code == 200 and user.json()["username"] == "Synthetic Event Coordinator"
        assert "name" not in user.json()
        result = assign(s)
>       assert result.status_code == 200, result.text
E       AssertionError: {"message":"Unable to save or load event requests. Please check the Event Service database connection and schema."}
E
E       assert 503 == 200
E        +  where 503 = <Response [503 SERVICE UNAVAILABLE]>.status_code

tests/integration/test_initial_assignment_delivery.py:34: AssertionError
=========================== short test summary info ============================
FAILED tests/integration/test_initial_assignment_delivery.py::test_real_initial_assignment_delivers_username_event_link_and_deduplicates
1 failed in 8.44s
```

## Real assignment integration GREEN

```text
.                                                                        [100%]
1 passed in 6.14s
```

## Consumer required name RED

```text
FFFFF                                                                    [100%]
=================================== FAILURES ===================================
___ test_assignment_without_required_display_content_is_quarantined[change0] ___

change = {'details': {}}

    @pytest.mark.parametrize("change", [
        {"details": {}}, {"details": None},
        {"details": {**ENVELOPE["details"], "coordinatorName": " "}},
        {"details": {**ENVELOPE["details"], "eventName": " "}},
        {"destination": dict(kind="event-venue-request", eventId=EVENT, bookingId=COORDINATOR)},
    ])
    def test_assignment_without_required_display_content_is_quarantined(change):
        """AC4: consume malformed assignment through real validation/storage
        adapters; quarantine instead of inbox insertion before acknowledgement.
        """
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        channel = Mock()
        with patch("psycopg2.connect", return_value=connection):
            process("synthetic", channel, Mock(delivery_tag=10), json.dumps({**ENVELOPE, **change}).encode())
>       assert not any(call.args[0].startswith('INSERT INTO public."Notification" ') for call in cursor.execute.call_args_list)
E       assert not True
E        +  where True = any(<generator object test_assignment_without_required_display_content_is_quarantined.<locals>.<genexpr> at 0x10545a5a0>)

tests/unit/test_initial_assignment_notifications.py:33: AssertionError
___ test_assignment_without_required_display_content_is_quarantined[change1] ___

change = {'details': None}

    @pytest.mark.parametrize("change", [
        {"details": {}}, {"details": None},
        {"details": {**ENVELOPE["details"], "coordinatorName": " "}},
        {"details": {**ENVELOPE["details"], "eventName": " "}},
        {"destination": dict(kind="event-venue-request", eventId=EVENT, bookingId=COORDINATOR)},
    ])
    def test_assignment_without_required_display_content_is_quarantined(change):
        """AC4: consume malformed assignment through real validation/storage
        adapters; quarantine instead of inbox insertion before acknowledgement.
        """
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        channel = Mock()
        with patch("psycopg2.connect", return_value=connection):
            process("synthetic", channel, Mock(delivery_tag=10), json.dumps({**ENVELOPE, **change}).encode())
>       assert not any(call.args[0].startswith('INSERT INTO public."Notification" ') for call in cursor.execute.call_args_list)
E       assert not True
E        +  where True = any(<generator object test_assignment_without_required_display_content_is_quarantined.<locals>.<genexpr> at 0x1054d9560>)

tests/unit/test_initial_assignment_notifications.py:33: AssertionError
___ test_assignment_without_required_display_content_is_quarantined[change2] ___

change = {'details': {'eventId': '30000000-0000-0000-0000-000000000001', 'eventName': 'Community Workshop', 'coordinatorId': '10000000-0000-0000-0000-000000000002', 'coordinatorName': ' '}}

    @pytest.mark.parametrize("change", [
        {"details": {}}, {"details": None},
        {"details": {**ENVELOPE["details"], "coordinatorName": " "}},
        {"details": {**ENVELOPE["details"], "eventName": " "}},
        {"destination": dict(kind="event-venue-request", eventId=EVENT, bookingId=COORDINATOR)},
    ])
    def test_assignment_without_required_display_content_is_quarantined(change):
        """AC4: consume malformed assignment through real validation/storage
        adapters; quarantine instead of inbox insertion before acknowledgement.
        """
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        channel = Mock()
        with patch("psycopg2.connect", return_value=connection):
            process("synthetic", channel, Mock(delivery_tag=10), json.dumps({**ENVELOPE, **change}).encode())
>       assert not any(call.args[0].startswith('INSERT INTO public."Notification" ') for call in cursor.execute.call_args_list)
E       assert not True
E        +  where True = any(<generator object test_assignment_without_required_display_content_is_quarantined.<locals>.<genexpr> at 0x1054d93c0>)

tests/unit/test_initial_assignment_notifications.py:33: AssertionError
___ test_assignment_without_required_display_content_is_quarantined[change3] ___

change = {'details': {'eventId': '30000000-0000-0000-0000-000000000001', 'eventName': ' ', 'coordinatorId': '10000000-0000-0000-0000-000000000002', 'coordinatorName': 'Alice Tan'}}

    @pytest.mark.parametrize("change", [
        {"details": {}}, {"details": None},
        {"details": {**ENVELOPE["details"], "coordinatorName": " "}},
        {"details": {**ENVELOPE["details"], "eventName": " "}},
        {"destination": dict(kind="event-venue-request", eventId=EVENT, bookingId=COORDINATOR)},
    ])
    def test_assignment_without_required_display_content_is_quarantined(change):
        """AC4: consume malformed assignment through real validation/storage
        adapters; quarantine instead of inbox insertion before acknowledgement.
        """
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        channel = Mock()
        with patch("psycopg2.connect", return_value=connection):
            process("synthetic", channel, Mock(delivery_tag=10), json.dumps({**ENVELOPE, **change}).encode())
>       assert not any(call.args[0].startswith('INSERT INTO public."Notification" ') for call in cursor.execute.call_args_list)
E       assert not True
E        +  where True = any(<generator object test_assignment_without_required_display_content_is_quarantined.<locals>.<genexpr> at 0x1054da670>)

tests/unit/test_initial_assignment_notifications.py:33: AssertionError
___ test_assignment_without_required_display_content_is_quarantined[change4] ___

change = {'destination': {'kind': 'event-venue-request', 'eventId': '30000000-0000-0000-0000-000000000001', 'bookingId': '10000000-0000-0000-0000-000000000002'}}

    @pytest.mark.parametrize("change", [
        {"details": {}}, {"details": None},
        {"details": {**ENVELOPE["details"], "coordinatorName": " "}},
        {"details": {**ENVELOPE["details"], "eventName": " "}},
        {"destination": dict(kind="event-venue-request", eventId=EVENT, bookingId=COORDINATOR)},
    ])
    def test_assignment_without_required_display_content_is_quarantined(change):
        """AC4: consume malformed assignment through real validation/storage
        adapters; quarantine instead of inbox insertion before acknowledgement.
        """
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        channel = Mock()
        with patch("psycopg2.connect", return_value=connection):
            process("synthetic", channel, Mock(delivery_tag=10), json.dumps({**ENVELOPE, **change}).encode())
>       assert not any(call.args[0].startswith('INSERT INTO public."Notification" ') for call in cursor.execute.call_args_list)
E       assert not True
E        +  where True = any(<generator object test_assignment_without_required_display_content_is_quarantined.<locals>.<genexpr> at 0x1054dae90>)

tests/unit/test_initial_assignment_notifications.py:33: AssertionError
=========================== short test summary info ============================
FAILED tests/unit/test_initial_assignment_notifications.py::test_assignment_without_required_display_content_is_quarantined[change0]
FAILED tests/unit/test_initial_assignment_notifications.py::test_assignment_without_required_display_content_is_quarantined[change1]
FAILED tests/unit/test_initial_assignment_notifications.py::test_assignment_without_required_display_content_is_quarantined[change2]
FAILED tests/unit/test_initial_assignment_notifications.py::test_assignment_without_required_display_content_is_quarantined[change3]
FAILED tests/unit/test_initial_assignment_notifications.py::test_assignment_without_required_display_content_is_quarantined[change4]
5 failed in 0.11s
```

## Consumer required name GREEN

```text
.....                                                                    [100%]
5 passed in 0.12s
```

## Real assignment scenarios

```text
.....                                                                    [100%]
5 passed in 77.06s (0:01:17)
```

## Event full suite

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/daphnetok/Documents/SMU/y3s1/IS212 Software Project Management/proj/codes/scrum-45-ticket-03/services/event-service
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, socket-0.8.1
collected 507 items

tests/test_event_summaries.py .....................                      [  4%]
tests/test_registration_events.py ..                                     [  4%]
tests/unit/test_clarification.py ...............................         [ 10%]
tests/unit/test_event_details.py .....................                   [ 14%]
tests/unit/test_event_details_recheck.py ............................... [ 20%]
..............................................................           [ 33%]
tests/unit/test_event_details_workflow.py ..........                     [ 35%]
tests/unit/test_event_list.py ...........................                [ 40%]
tests/unit/test_event_progress.py .............................          [ 46%]
tests/unit/test_initial_assignment_notifications.py .................    [ 49%]
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
app/models.py         476      1    154      2  99.52%   783->786, 1395
app/outbox.py         119      0     48      0 100.00%
app/validation.py      23      0     12      0 100.00%
----------------------------------------------------------------
TOTAL                1094     10    364      7  98.83%
Required test coverage of 98.79% reached. Total coverage: 98.83%
============================= 507 passed in 8.59s ==============================
```

## Browser assignment and regressions

```text
Running 6 tests using 5 workers

  ✓  3 [chromium] › e2e/notifications.spec.ts:56:1 › inaccessible event keeps notification read and renders ordinary permission fallback (2.6s)
  ✓  5 [chromium] › e2e/event-rejection-notifications.spec.ts:5:1 › organiser bell and inbox open event-only decision details with rejection reason (2.7s)
  ✓  1 [chromium] › e2e/notifications.spec.ts:76:4 › linked request fallback and legacy null card: cancelled assigned event (2.7s)
  ✓  2 [chromium] › e2e/event-assignment-notifications.spec.ts:7:1 › organiser bell and inbox display assigned name and open event details (3.0s)
  ✓  6 [chromium] › e2e/notifications.spec.ts:76:4 › linked request fallback and legacy null card: viewable reassigned Lead event (897ms)
  ✓  4 [chromium] › e2e/notifications.spec.ts:21:1 › bell opens without reading; click focuses exact rejected request; unread and identity isolation (3.9s)

  6 passed (5.7s)
```

## Final verification (before completion merge)

| Command / boundary | Actual result |
| --- | --- |
| Event: `uv run pytest` | 507 passed; coverage 98.83%; floor raised 98.79 → 98.83, new outbox code 100% |
| Event Workflow: `uv run pytest` | 85 passed; 9 integration deselected; coverage 100%, floor 100% |
| Notification: `uv run pytest` | 92 passed; coverage 100%, floor 100% |
| User: `uv run pytest` | 8 passed; coverage 97.87%, existing floor 97% |
| Coordinator Assignment: `uv run pytest` | 37 passed; coverage 87.85%, existing floor 87% |
| Workflow: `uv run --with psycopg2-binary python -m pytest tests/integration -m integration --no-cov -q --basetemp=/Users/daphnetok/.hermes/cache/scratch/scrum45-ticket03-integrations` | **9 passed in 124.15s**: 5 initial-assignment scenarios, 4 preserved rejection scenarios; no skip |
| Frontend: `npm run test:coverage` | 59 files, 720 tests passed; statement 98.1%, branch 92.4%, function 96.6%, line 98.76%; unchanged configured gates |
| Frontend: `npm run build` | TypeScript and Vite build passed |
| Frontend: `npm run lint` | Exit 0; 3 existing react fast-refresh warnings in untouched ClosureDetails.tsx |
| Frontend: `CI=1 npx playwright test -c e2e --retries=0 --reporter=json` | Parsed JSON: **71 expected/pass, 0 skipped, 0 unexpected, 0 flaky**, no report errors |
| Feature Python test module/method docstrings | AST check passed on all 4 feature pytest modules; story and AC/DR method docstrings present |
| Test imports | No test-to-test imports in Workflow tests; service-local `delivery_system.py` fixture reused |

Real integrations launch PostgreSQL 17 and RabbitMQ 4 management containers with
unique names and loopback ephemeral ports. Event, Notification and **real User
Service** use separate local databases; no mock User HTTP server is used. Tests
assert User's direct `username` response shape and the resulting inbox content.
Temporary real User 503 and real broker outage both recover; the original name
remains frozen after User rename. Missing-user and blank-username cases hold,
unrelated rejection delivers, then authenticated repair releases the original
assignment source ID. PostgreSQL trigger-injected insert failure rolls back both
assignment and intent. Containers/processes are cleaned in fixture `finally`.

Browser evidence is **mocked API / real Chromium UI**, not backend persistence.
The new initial-assignment journey already passed on the reused UI: bell and
inbox show Alice Tan and event name, opening the link reaches the organiser event
details and sends a read update. No frontend production changes were required.
Full Playwright also preserves rejection and venue destination regressions.

### Review/tool limitations and unrelated findings

- The independent Codex review executable failed before starting with ENOENT
  (missing native vendor binary), exit 1. This is **not** a passed review.
- One fallback Claude print-mode read-only diff review was attempted; it timed
  out at 180 seconds with an empty result file. This is **not** a passed review.
  Parent agent will perform final integration code review. Commit is not labelled
  independently verified. Actual test execution above is separate evidence.
- `npm audit --json` exits 1 for **one existing high-severity Vite dependency**
  (installed 8.3.0; launch-editor advisories). Lockfile/package dependencies are
  unchanged. No audit suppression or unrelated upgrade was made.
- Event's remaining coverage gaps predate this slice and are in legacy routes
  and decision/progress branches; new outbox code has 100% line/branch coverage.
  No coverage gate was lowered.
- Reassignment remains ticket 04; production auth, backfill and notification
  delivery latency guarantees remain out of scope. No ticket status was changed.
