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
    """Owned disposable containers and three separate owner databases; no .env."""
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
        for database, tables in [("events", {"Event", "User"}), ("notifications", {"Event", "User", "Notification"}), ("users", {"User"})]:
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
            for identity, role in [(ORGANISER, "Event Organiser"), (ACTOR, "Event Coordinator")]:
                sql(database, 'INSERT INTO public."User"(user_id,username,role) VALUES (%s,%s,%s)',
                    (identity, "Synthetic " + role, role))
        for service, database in [("event-service", "events"), ("notification-service", "notifications"), ("user-service", "users")]:
            port = free_port()
            urls[service] = f"http://127.0.0.1:{port}"
            start(service, ["-m", "flask", "--app", "app", "run", "--host", "127.0.0.1", "--port", str(port)], database)
            wait(lambda: http(service, "GET", "/health").status_code == 200)
        env["EVENT_SERVICE_URL"] = urls["event-service"]
        env["USER_SERVICE_URL"] = urls["user-service"]
        event_id = str(uuid4())
        for database in ("events", "notifications"):
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
