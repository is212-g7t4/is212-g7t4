"""SCRUM-45 user story: As an Event Organiser, I want to receive an in-app
notification when the Lead Coordinator approves or rejects my event request,
so that I know the outcome and who is responsible for coordinating my event.
AC1–AC4: shared disposable delivery infrastructure, including real User lookup.
"""

import json
import os
from pathlib import Path
import re
import socket
import signal
import subprocess
import sys
import time
from uuid import uuid4
import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
ORGANISER = "10000000-0000-0000-0000-000000000001"
ACTOR = "10000000-0000-0000-0000-000000000002"
LEAD = "10000000-0000-0000-0000-000000000005"
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


def assign_as_lead(s, coordinator):
    """AC4: use the real composite's Lead-role and target-user validation."""
    return s["http"]("coordinator-assignment-service", "POST",
        f"/events/{s['event']}/assign-coordinator/{coordinator}", json={"actingUserId": LEAD})


def replay_barrier(s, envelope, inbox):
    """DR3: one FIFO consumer commits a sentinel after replay, not queue emptiness."""
    s["replay"](envelope)
    sentinel = {**envelope, "id": str(uuid4()), "message": "FIFO replay barrier"}
    s["replay"](sentinel)
    def observed():
        rows = inbox()
        return rows if any(row["payload"]["id"] == sentinel["id"] for row in rows) else None
    items = wait(observed)
    originals = [row for row in items if row["payload"]["id"] == envelope["id"]]
    assert len(items) == 2
    assert len(originals) == 1
    return originals[0]


def wait_group_gone(pgid, seconds):
    """Observe ESRCH, not leader exit. Zombies may keep a group observable until
    their parent/init reaps them; timeout reports unverified absence, not success.
    """
    deadline = time.monotonic() + seconds
    while True:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            # macOS may briefly return EPERM while a killed group is reaped.
            # It is not proof of absence: keep polling for ESRCH, bounded below.
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def cleanup_owned_resources(processes, logs, names):
    """DR3 test isolation: attempt all owned resources and verify container absence.
    Return diagnostics so fixture reporting cannot mask an active setup exception.
    """
    failures = []
    for process in reversed(processes):
        try:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            # All entries are session leaders created with start_new_session=True.
            # A reaped leader does not prove that its children have exited.
            if not wait_group_gone(process.pid, seconds=1):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
                if not wait_group_gone(process.pid, seconds=5):
                    raise RuntimeError("owned group absence unverified after SIGKILL (may include unreaped zombies)")
        except Exception as error:
            failures.append(f"process {process.pid}: {type(error).__name__}: {error}")
    for logfile in logs:
        try:
            logfile.close()
        except Exception as error:
            failures.append(f"log close: {type(error).__name__}: {error}")
    for name in reversed(names):
        try:
            removed = subprocess.run(["docker", "rm", "-fv", name], capture_output=True, text=True, timeout=30)
            if removed.returncode:
                failures.append(f"docker rm {name}: {removed.returncode}: {removed.stderr.strip()}")
            # Read back exact target: a successful rm response alone is insufficient.
            inspected = subprocess.run(["docker", "container", "ls", "-a", "--filter", f"name=^/{name}$",
                                        "--format", "{{.Names}}"], capture_output=True, text=True, timeout=15)
            if inspected.returncode or inspected.stdout.strip():
                failures.append(f"container absence unverified {name}: {inspected.returncode}: {inspected.stdout.strip()} {inspected.stderr.strip()}")
        except Exception as error:
            failures.append(f"container {name}: {type(error).__name__}: {error}")
    return failures


@pytest.fixture
def system(tmp_path):
    """Owned disposable containers and four separate owner databases; no .env."""
    import psycopg2
    subprocess.run(["docker", "info"], check=True, capture_output=True, timeout=20)
    names, processes, logs = [], [], []
    env = {key: os.environ[key] for key in ("PATH", "HOME", "SSL_CERT_FILE") if key in os.environ}
    env.update(PYTHON_DOTENV_DISABLED="1", FLASK_SKIP_DOTENV="1", PYTHONUNBUFFERED="1",
               INTERNAL_SERVICE_TOKEN=TOKEN, NOTIFICATION_DEV_MODE="true",
               FRONTEND_ORIGIN=f"http://localhost:{free_port()}")
    dsns, urls = {}, {"frontend": env["FRONTEND_ORIGIN"]}
    identifier = "scrum45-" + uuid4().hex[:12]

    def sql(database, text, params=None):
        with psycopg2.connect(dsns[database]) as connection, connection.cursor() as cursor:
            cursor.execute(text, params)

    def start(service, args, database=None):
        logfile = open(tmp_path / f"{service}-{len(processes)}.log", "w")
        logs.append(logfile)
        process = subprocess.Popen([str(ROOT / "services" / service / ".venv/bin/python"), *args],
            cwd=ROOT / "services" / service,
            env={**env, **({"DATABASE_URL": dsns[database]} if database else {})},
            stdout=logfile, stderr=subprocess.STDOUT, start_new_session=True)
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
        for database, tables in [("events", {"Event", "User"}), ("notifications", {"Event", "User", "Notification"}), ("users", {"User"}),
                                 ("availability", {"User", "Event", "Venue", "VenueBooking", "VenueClosure"})]:
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
            if database == "events":
                for migration in sorted([*migrations.glob("*event_notification*.sql"), *migrations.glob("*_event_approval_notifications.sql")]):
                    sql(database, migration.read_text())
            elif database == "notifications":
                sql(database, (migrations / "20261017000000_notification_inbox.sql").read_text())
            if database == "availability":
                sql(database, (migrations / "20261016100000_add_hold_coordinator.sql").read_text())
            for identity, role in [(ORGANISER, "Event Organiser"), (ACTOR, "Event Coordinator"), (LEAD, "Event Coordinator Lead")]:
                sql(database, 'INSERT INTO public."User"(user_id,username,role) VALUES (%s,%s,%s)',
                    (identity, "Synthetic " + role, role))
        for service, database in [("event-service", "events"), ("notification-service", "notifications"), ("user-service", "users")]:
            port = free_port()
            urls[service] = f"http://127.0.0.1:{port}"
            start(service, ["-m", "flask", "--app", "app", "run", "--host", "127.0.0.1", "--port", str(port)], database)
            wait(lambda: http(service, "GET", "/health").status_code == 200)
        env["EVENT_SERVICE_URL"] = urls["event-service"]
        env["USER_SERVICE_URL"] = urls["user-service"]
        port = free_port()
        urls["coordinator-assignment-service"] = f"http://127.0.0.1:{port}"
        start("coordinator-assignment-service", ["-m", "flask", "--app", "app", "run",
              "--host", "127.0.0.1", "--port", str(port)])
        wait(lambda: http("coordinator-assignment-service", "GET", "/health").status_code == 200)
        event_id = str(uuid4())
        for database in ("events", "notifications"):
            sql(database, 'INSERT INTO public."Event"(event_id,event_name,coordinator_id,organiser_id,status) VALUES (%s,%s,%s,%s,%s)',
                (event_id, "Community Workshop", ACTOR, ORGANISER, "Under Review"))
        def replay(envelope):
            command([str(ROOT / "services/event-workflow-service/.venv/bin/python"), "-c",
                     "import json,sys; from app.dispatcher import publish; publish(json.loads(sys.argv[1]))", json.dumps(envelope)],
                    cwd=ROOT / "services/event-workflow-service", env=env)
        yield dict(http=http, sql=sql, worker=worker, start=start, replay=replay, event=event_id,
                   rabbit=names[1], urls=urls, env=env, processes=processes)
    finally:
        # A teardown error is a separate pytest report, never a silent success.
        # During setup failure retain the original exception and attach cleanup
        # diagnostics instead of replacing it with a secondary cleanup failure.
        primary = sys.exception()
        failures = cleanup_owned_resources(processes, logs, names)
        if failures:
            message = "Owned SCRUM-45 cleanup failures: " + "; ".join(failures)
            if primary is not None:
                primary.add_note(message)
            else:
                pytest.fail(message, pytrace=False)
