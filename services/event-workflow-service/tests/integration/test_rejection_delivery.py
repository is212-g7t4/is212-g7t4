"""User story (SCRUM-45): As an Event Organiser, I want in-app notification
when the Lead Coordinator rejects my event request, so I know the outcome
and who coordinates it. AC2/AC3: rejection reason, event name and details link.
DR2/DR3/DR4/DR5: atomic intent, retry identity, frozen facts and legacy diagnosis.
"""

import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time
from uuid import uuid4
import httpx
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
ROOT = Path(__file__).resolve().parents[4]
ORGANISER = "10000000-0000-0000-0000-000000000001"
ACTOR = "10000000-0000-0000-0000-000000000002"
TOKEN = "scrum45-isolated-test-token"
HEADERS = {"X-Internal-Token": TOKEN}
REASON = "The proposal needs a safety plan.\nPlease revise."


def command(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, timeout=90, **kwargs)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def wait(check, seconds=60):
    end = time.monotonic() + seconds
    last = None
    while time.monotonic() < end:
        try:
            value = check()
            if value:
                return value
        except Exception as error:
            last = error
        time.sleep(0.2)
    raise AssertionError(f"Condition timed out: {last}")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def system(tmp_path):
    """Owned disposable containers and two separate owner databases; no .env."""
    import psycopg2
    subprocess.run(["docker", "info"], check=True, capture_output=True, timeout=20)
    names, processes, logs = [], [], []
    env = {key: os.environ[key] for key in ("PATH", "HOME", "SSL_CERT_FILE") if key in os.environ}
    env.update(PYTHON_DOTENV_DISABLED="1", FLASK_SKIP_DOTENV="1", PYTHONUNBUFFERED="1",
               INTERNAL_SERVICE_TOKEN=TOKEN, NOTIFICATION_DEV_MODE="true")
    dsns, urls = {}, {}
    identifier = "scrum45-" + uuid4().hex[:12]

    def sql(database, text, params=None):
        with psycopg2.connect(dsns[database]) as connection, connection.cursor() as cursor:
            cursor.execute(text, params)

    def start(service, args, database):
        logfile = open(tmp_path / f"{service}-{len(processes)}.log", "w")
        logs.append(logfile)
        process = subprocess.Popen([str(ROOT / "services" / service / ".venv/bin/python"), *args],
            cwd=ROOT / "services" / service, env={**env, "DATABASE_URL": dsns[database]},
            stdout=logfile, stderr=subprocess.STDOUT)
        processes.append(process)
        return process

    def http(service, method, path, **kwargs):
        return httpx.request(method, urls[service] + path, timeout=5, **kwargs)

    def worker(failure=False):
        result = subprocess.run([str(ROOT / "services/event-workflow-service/.venv/bin/python"),
                                 "-m", "app.dispatcher", "--attempt"], capture_output=True, text=True,
                                timeout=55, cwd=ROOT / "services/event-workflow-service", env=env)
        output = result.stdout + result.stderr
        with open(tmp_path / "worker.log", "a") as logfile:
            logfile.write(output)
        if result.returncode == 3:
            return False
        assert result.returncode == 0, output
        assert ("Dispatch retry" in output) == failure, output
        return True

    try:
        for suffix, image, port, settings in [
            ("postgres", "postgres:17", 5432, {"POSTGRES_USER": "isolated", "POSTGRES_PASSWORD": "synthetic-only"}),
            ("rabbit", "rabbitmq:4-management", 5672, {"RABBITMQ_DEFAULT_USER": "isolated", "RABBITMQ_DEFAULT_PASS": "synthetic-only"}),
        ]:
            name = identifier + "-" + suffix
            names.append(name)
            command(["docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{free_port()}:{port}",
                     *[part for key, value in settings.items() for part in ("-e", f"{key}={value}")], image])
            selected = command(["docker", "port", name, str(port)]).rsplit(":", 1)[1]
            if suffix == "postgres":
                admin = f"postgresql://isolated:synthetic-only@127.0.0.1:{selected}/postgres"
            else:
                env["RABBITMQ_URL"] = f"amqp://isolated:synthetic-only@127.0.0.1:{selected}/%2F"
        def postgres_ready():
            connection = psycopg2.connect(admin)
            connection.close()
            return True
        wait(postgres_ready)
        wait(lambda: subprocess.run(["docker", "exec", "-u", "rabbitmq", names[1], "rabbitmq-diagnostics", "-q", "check_running"],
                                   capture_output=True, timeout=15).returncode == 0)
        migrations = ROOT / "database/supabase/migrations"
        baseline = re.sub(r"--[^\n]*", "", (migrations / "20261011140000_baseline_schema.sql").read_text())
        for database, tables in [("events", {"Event", "User"}), ("notifications", {"Event", "User", "Notification"})]:
            connection = psycopg2.connect(admin)
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute("CREATE DATABASE " + database)
            connection.close()
            dsns[database] = admin.rsplit("/", 1)[0] + "/" + database
            for statement in baseline.split(";"):
                target = re.search(r'(?:TABLE(?: IF NOT EXISTS| ONLY)?|ON) "public"\."([^"]+)"', statement)
                if target and target.group(1) in tables:
                    sql(database, statement)
            migration = "20261021000000_event_notification_outbox.sql" if database == "events" else "20261017000000_notification_inbox.sql"
            sql(database, (migrations / migration).read_text())
            for identity, role in [(ORGANISER, "Event Organiser"), (ACTOR, "Event Coordinator")]:
                sql(database, 'INSERT INTO public."User"(user_id,username,role) VALUES (%s,%s,%s)',
                    (identity, "Synthetic " + role, role))
        for service, database in [("event-service", "events"), ("notification-service", "notifications")]:
            port = free_port()
            urls[service] = f"http://127.0.0.1:{port}"
            start(service, ["-m", "flask", "--app", "app", "run", "--host", "127.0.0.1", "--port", str(port)], database)
            wait(lambda: http(service, "GET", "/health").status_code == 200)
        env["EVENT_SERVICE_URL"] = urls["event-service"]
        event_id = str(uuid4())
        for database in dsns:
            sql(database, 'INSERT INTO public."Event"(event_id,event_name,coordinator_id,organiser_id,status) VALUES (%s,%s,%s,%s,%s)',
                (event_id, "Community Workshop", ACTOR, ORGANISER, "Under Review"))
        def replay(envelope):
            command([str(ROOT / "services/event-workflow-service/.venv/bin/python"), "-c",
                     "import json,sys; from app.dispatcher import publish; publish(json.loads(sys.argv[1]))", json.dumps(envelope)],
                    cwd=ROOT / "services/event-workflow-service", env=env)
        yield dict(http=http, sql=sql, worker=worker, start=start, replay=replay, event=event_id, rabbit=names[1])
    finally:
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for logfile in logs:
            logfile.close()
        for name in reversed(names):
            subprocess.run(["docker", "rm", "-fv", name], capture_output=True, timeout=30)


@pytest.mark.parametrize("route", ["reject", "progress"])
def test_real_rejection_outage_recovery_deduplication_and_recipient_isolation(system, route):
    """AC2/AC3/DR3/DR4/DR8: real mutation, PostgreSQL, Event Workflow HTTP
    worker, stopped/recovered RabbitMQ, consumer and inbox HTTP. Replay frozen
    publication and verify one read-preserving inbox row plus organiser details.
    """
    s = system
    command(["docker", "stop", s["rabbit"]])
    body = dict(coordinatorId=ACTOR)
    body.update(dict(reason=REASON) if route == "reject" else dict(status="Rejected", actionDetails=REASON))
    result = s["http"]("event-service", "PATCH", f"/events/{s['event']}/{route}", json=body)
    assert result.status_code == 200, result.text
    assert s["worker"](failure=True)  # Real publish outage; durable state survives.
    details = s["http"]("event-service", "GET", f"/events/{s['event']}?organiserId={ORGANISER}")
    assert details.json()["decision"]["reason"] == REASON
    command(["docker", "start", s["rabbit"]])
    wait(lambda: subprocess.run(["docker", "exec", "-u", "rabbitmq", s["rabbit"], "rabbitmq-diagnostics", "-q", "check_running"], capture_output=True, timeout=15).returncode == 0)
    s["start"]("notification-service", ["-m", "app.consumer"], "notifications")
    job = wait(lambda: s["http"]("event-service", "POST", "/internal/notification-outbox/claim", headers=HEADERS, json={}).json()["jobs"])[0]
    # The worker frozen envelope is immutable across the outage.
    envelope = job["envelope"]
    assert s["http"]("event-service", "POST", "/internal/notification-outbox/claim", headers=HEADERS, json={}).json()["jobs"] == []
    stale = s["http"]("event-service", "POST", f"/internal/notification-outbox/{job['id']}/published", headers=HEADERS,
                      json=dict(leaseToken=str(uuid4())))
    assert stale.status_code == 409
    freeze = s["http"]("event-service", "POST", f"/internal/notification-outbox/{job['id']}/freeze", headers=HEADERS,
                       json=dict(leaseToken=job["leaseToken"], envelope={"replacement": True}))
    assert freeze.json()["envelope"] == envelope
    assert envelope["recipientId"] == ORGANISER
    assert envelope["details"]["reason"] == REASON
    assert envelope["destination"] == dict(kind="event-details", eventId=s["event"])
    retry = s["http"]("event-service", "POST", f"/internal/notification-outbox/{job['id']}/retry", headers=HEADERS,
                      json=dict(leaseToken=job["leaseToken"], error="integration retry"))
    assert retry.status_code == 200
    # Empty claim exits 3 until retry availability; execute worker conditionally,
    # without stealing its lease or modifying the owner's scheduling table.
    wait(s["worker"])
    own = {"X-Dev-User-Id": ORGANISER, "X-Dev-Role": "Event Organiser"}
    inbox = lambda: s["http"]("notification-service", "GET", "/notifications", headers=own).json()["notifications"]
    items = wait(inbox)
    assert len(items) == 1
    assert items[0]["payload"] == envelope
    notification_id = items[0]["id"]
    assert s["http"]("notification-service", "PATCH", f"/notifications/{notification_id}", headers=own, json=dict(read=True)).status_code == 200
    read_at = inbox()[0]["readAt"]
    # Simulate lost published receipt: same immutable identity must deduplicate.
    s["replay"](envelope)
    wait(lambda: "notifications.v1\t0" in command(["docker", "exec", "-u", "rabbitmq", s["rabbit"], "rabbitmqctl", "list_queues", "-q", "name", "messages"]))
    assert inbox()[0]["readAt"] == read_at
    assert len(inbox()) == 1
    other = {"X-Dev-User-Id": ACTOR, "X-Dev-Role": "Event Coordinator"}
    assert s["http"]("notification-service", "GET", "/notifications", headers=other).json()["notifications"] == []
    assert s["http"]("event-service", "POST", "/internal/notification-outbox/claim", headers=HEADERS, json={}).json()["jobs"] == []


@pytest.mark.parametrize("route", ["reject", "progress"])
def test_failed_rejection_rolls_back_event_and_pending_work(system, route):
    """DR2: a real PostgreSQL intent-insert failure rolls back the mutation;
    observe original decision/status and no pending work via owner HTTP APIs.
    """
    s = system
    s["sql"]("events", '''CREATE FUNCTION fail_intent() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected isolated failure'; END $$;
        CREATE TRIGGER fail_intent BEFORE INSERT ON public."EventNotificationOutbox" FOR EACH ROW EXECUTE FUNCTION fail_intent();''')
    body = dict(coordinatorId=ACTOR)
    body.update(dict(reason=REASON) if route == "reject" else dict(status="Rejected", actionDetails=REASON))
    result = s["http"]("event-service", "PATCH", f"/events/{s['event']}/{route}", json=body)
    assert result.status_code == 503
    event = s["http"]("event-service", "GET", f"/events/{s['event']}?organiserId={ORGANISER}").json()
    assert event["status"] == "Under Review" and event["decision"] is None
    assert s["http"]("event-service", "POST", "/internal/notification-outbox/claim", headers=HEADERS, json={}).json()["jobs"] == []
